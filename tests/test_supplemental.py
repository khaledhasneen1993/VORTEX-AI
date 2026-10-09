"""Supplemental sources preserve limitations; no market performance claims."""

import hashlib
import io
import json
import zipfile
from datetime import date

import pytest
from research.download_supplemental import archive, fetch_filters, validate_csv


class Response:
    def __init__(self, content):
        self.content = content
        self.text = content.decode() if not content.startswith(b"PK") else ""

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)

    def iter_content(self, _):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class Session:
    def __init__(self, body, bad=False):
        self.body, self.bad, self.calls = body, bad, []

    def get(self, url, **_):
        self.calls.append(url)
        if url.endswith(".CHECKSUM"):
            sha = "0" * 64 if self.bad else hashlib.sha256(self.body).hexdigest()
            return Response((sha + " file.zip").encode())
        return Response(self.body)


FUNDING = (
    "calc_time,funding_interval_hours,last_funding_rate\n1788220800005,8,0.0001\n1788249600000,8,0.0002\n"
)


def zip_body(name, text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def test_funding_verified_cache_keeps_realized_and_raw_time(tmp_path):
    session = Session(zip_body("BTCUSDT-fundingRate-2026-09.csv", FUNDING))
    report = archive(tmp_path, "BTCUSDT", "fundingRate", "2026-09", session)
    assert report["rows"] == 2 and report["non_minute_timestamps"] == 1
    assert report["first_ms"] == 1788220800005
    assert not report["continuous_coverage_proven"]
    assert "no settlement mark or prior forecast" in report["use_limitations"]
    assert archive(tmp_path, "BTCUSDT", "fundingRate", "2026-09", session) == report
    assert len(session.calls) == 2
    csv = next(tmp_path.rglob("*.csv"))
    csv.write_text("tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        archive(tmp_path, "BTCUSDT", "fundingRate", "2026-09", session)


@pytest.mark.parametrize("kind", ["hash", "member", "duplicate"])
def test_bad_supplemental_not_published(tmp_path, kind):
    name = "../bad.csv" if kind == "member" else "BTCUSDT-fundingRate-2026-09.csv"
    text = FUNDING + FUNDING.splitlines(True)[-1] if kind == "duplicate" else FUNDING
    session = Session(zip_body(name, text), bad=kind == "hash")
    with pytest.raises(ValueError):
        archive(tmp_path, "BTCUSDT", "fundingRate", "2026-09", session)
    assert not list(tmp_path.rglob("*.csv"))


def test_sparse_metrics_and_aggregated_depth_are_not_execution_book(tmp_path):
    p = tmp_path / "metrics.csv"
    p.write_text(
        "create_time,symbol,sum_open_interest,sum_open_interest_value\n2026-10-08 00:15:00,BTCUSDT,10,100\n2026-10-08 01:10:00,BTCUSDT,11,110\n"
    )
    result = validate_csv(p, "metrics", "BTCUSDT", "2026-10-08")
    assert result["rows"] == 2 and not result["continuous_coverage_proven"]
    p.write_text(
        "timestamp,percentage,depth,notional\n2026-10-08 00:15:00,-1,10,100\n2026-10-08 00:15:00,1,11,110\n"
    )
    assert validate_csv(p, "bookDepth", "BTCUSDT", "2026-10-08")["rows"] == 2
    p.write_text(p.read_text().replace(",100", ",-100"))
    with pytest.raises(ValueError, match="values"):
        validate_csv(p, "bookDepth", "BTCUSDT", "2026-10-08")


def filters():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }


def test_actual_filter_snapshot_not_historical_and_never_overwritten(tmp_path):
    session = Session(json.dumps(filters()).encode())
    report = fetch_filters(tmp_path, ["BTCUSDT"], session)
    assert not report["historical_asof_proven"]
    assert session.calls == ["https://fapi.binance.com/fapi/v1/exchangeInfo"]
    assert (tmp_path / "exchange_info.json").exists()
    with pytest.raises(ValueError, match="exists"):
        fetch_filters(tmp_path, ["BTCUSDT"], session)


def test_missing_filter_is_not_guessed(tmp_path):
    data = filters()
    data["symbols"][0]["filters"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        fetch_filters(tmp_path, ["BTCUSDT"], Session(json.dumps(data).encode()))
    assert not (tmp_path / "exchange_info.json").exists()


def test_raw_unordered_metrics_are_preserved_with_warning(tmp_path):
    p = tmp_path / "metrics.csv"
    p.write_text(
        "create_time,symbol,sum_open_interest,sum_open_interest_value\n2026-10-08 01:10:00,BTCUSDT,10,100\n2026-10-08 00:15:00,BTCUSDT,11,110\n"
    )
    r = validate_csv(p, "metrics", "BTCUSDT", "2026-10-08")
    assert r["unordered_transitions"] == 1
    assert r["first_ms"] < r["last_ms"]
    assert not r["continuous_coverage_proven"]
    assert p.read_text().splitlines()[1].startswith("2026-10-08 01:10")


def test_local_filter_manifest_detects_tampering(tmp_path):
    from vortex.local_data import LocalMarket
    from vortex.binance import MarketError

    fetch_filters(tmp_path, ["BTCUSDT"], Session(json.dumps(filters()).encode()))
    m = LocalMarket(tmp_path, 1791504000000)
    assert "BTCUSDT" in m.metadata()
    p = tmp_path / "exchange_info.json"
    p.write_text(p.read_text() + " ")
    with pytest.raises(MarketError, match="hash mismatch"):
        m.metadata()


def test_rest_funding_preserves_published_settlement_mark(tmp_path):
    from datetime import date
    from research.download_supplemental import fetch_funding

    rows = [{"symbol": "BTCUSDT", "fundingTime": 1790812800000, "fundingRate": "0.0001", "markPrice": "100"}]
    result = fetch_funding(
        tmp_path, "BTCUSDT", date(2026, 10, 1), date(2026, 10, 9), Session(json.dumps(rows).encode())
    )
    assert result["rows"] == 1 and result["pagination_complete"]
    assert not result["continuous_coverage_proven"]
    path = next(tmp_path.rglob("page-00.json"))
    assert json.loads(path.read_text())[0]["markPrice"] == "100"
    with pytest.raises(FileExistsError):
        fetch_funding(
            tmp_path, "BTCUSDT", date(2026, 10, 1), date(2026, 10, 9), Session(json.dumps(rows).encode())
        )


def test_rest_funding_rejects_missing_or_fabricated_mark(tmp_path):
    from datetime import date
    from research.download_supplemental import fetch_funding

    rows = [{"symbol": "BTCUSDT", "fundingTime": 1790812800000, "fundingRate": "0.0001", "markPrice": "0"}]
    with pytest.raises(ValueError, match="settlement"):
        fetch_funding(
            tmp_path, "BTCUSDT", date(2026, 10, 1), date(2026, 10, 9), Session(json.dumps(rows).encode())
        )
    assert not list(tmp_path.rglob("manifest.json"))


def test_rest_funding_pagination_advances_without_duplicates(tmp_path):
    from datetime import date
    from research.download_supplemental import fetch_funding

    start = 1790812800000
    rows = [
        dict(symbol="BTCUSDT", fundingTime=start + i * 60000, fundingRate="0.0001", markPrice="100")
        for i in range(1001)
    ]

    class Paged:
        def __init__(self):
            self.cursors = []

        def get(self, url, params, **kwargs):
            self.cursors.append(params["startTime"])
            batch = [r for r in rows if r["fundingTime"] >= params["startTime"]][:1000]
            return Response(json.dumps(batch).encode())

    session = Paged()
    result = fetch_funding(tmp_path, "BTCUSDT", date(2026, 10, 1), date(2026, 10, 9), session)
    assert result["rows"] == 1001 and len(result["pages"]) == 2
    assert session.cursors[1] == rows[999]["fundingTime"] + 1
