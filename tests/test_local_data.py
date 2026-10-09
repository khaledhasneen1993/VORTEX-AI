"""Archive integrity and offline routing, not profitability tests."""

import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from research.download_ohlcv import download_day
from vortex.binance import MarketError
from vortex.local_data import LocalMarket, digest, read_csv


def daily(day, interval="1h"):
    from vortex.local_data import STEPS

    step = STEPS[interval]
    start = int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp() * 1000)
    return (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,quote_buy,ignore\n"
        + "".join(
            f"{t},10,12,9,11,100,{t + step - 1},1000,5,40,400,0\n"
            for t in range(start, start + 86400000, step)
        )
    )


class Response:
    def __init__(self, body):
        self.body = body
        self.text = body.decode() if isinstance(body, bytes) and not body.startswith(b"PK") else ""

    def raise_for_status(self):
        pass

    def iter_content(self, _):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class Session:
    def __init__(self, day, csv=None, bad_checksum=False, member=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(member or f"BTCUSDT-1h-{day}.csv", csv or daily(day))
        self.archive = buf.getvalue()
        self.bad_checksum = bad_checksum
        self.calls = []

    def get(self, url, **_):
        self.calls.append(url)
        if url.endswith(".CHECKSUM"):
            checksum = "0" * 64 if self.bad_checksum else hashlib.sha256(self.archive).hexdigest()
            return Response((checksum + "  file.zip").encode())
        return Response(self.archive)


def test_download_verified_cache_and_tamper(tmp_path):
    day = date(2026, 10, 8)
    session = Session(day)
    record = download_day(tmp_path, "BTCUSDT", "1h", day, session)
    assert record["rows"] == 24 and len(session.calls) == 2
    assert all(url.startswith("https://data.binance.vision/") for url in session.calls)
    assert download_day(tmp_path, "BTCUSDT", "1h", day, session) == record
    assert len(session.calls) == 2
    csv = next(tmp_path.rglob("*.csv"))
    csv.write_text(csv.read_text().replace(",11,", ",10,"))
    with pytest.raises(ValueError, match="hash mismatch"):
        download_day(tmp_path, "BTCUSDT", "1h", day, session)


@pytest.mark.parametrize("kind", ["checksum", "path", "gap"])
def test_bad_archive_never_published(tmp_path, kind):
    day = date(2026, 10, 8)
    rows = daily(day).splitlines(True)
    session = Session(
        day,
        csv="".join(rows[:2] + rows[3:]) if kind == "gap" else None,
        bad_checksum=kind == "checksum",
        member="../bad.csv" if kind == "path" else None,
    )
    with pytest.raises((ValueError, MarketError)):
        download_day(tmp_path, "BTCUSDT", "1h", day, session)
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.parametrize("change", [",12,9,", ",nan,", ",999,"])
def test_malformed_csv(tmp_path, change):
    p = tmp_path / "bad.csv"
    text = daily(date(2026, 10, 8))
    if change == ",12,9,":
        text = text.replace(change, ",9,12,")
    elif change == ",nan,":
        text = text.replace(",11,", change)
    else:
        text = text.replace(",40,", change)
    p.write_text(text)
    with pytest.raises(MarketError):
        list(read_csv(p, "1h"))


def test_local_range_missing_hash_and_metadata(tmp_path):
    from datetime import timedelta

    end = date(2026, 10, 9)
    end_ms = int(datetime.combine(end, datetime.min.time(), timezone.utc).timestamp() * 1000)
    market = LocalMarket(tmp_path, end_ms)
    with pytest.raises(MarketError, match="Missing verified"):
        market.history("BTCUSDT", "1h", 1, end_ms)
    for offset in range(11, 0, -1):
        day = end - timedelta(days=offset)
        folder = tmp_path / "BTCUSDT" / "1h"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"BTCUSDT-1h-{day}.csv"
        p.write_text(daily(day))
        p.with_suffix(".json").write_text(json.dumps({"csv_sha256": digest(p)}))
    bars = market.history("BTCUSDT", "1h", 1, end_ms)
    assert len(bars) == 264 and bars[-1].close_ts == end_ms - 1
    with pytest.raises(MarketError, match="exchange_info"):
        market.metadata()
    p.write_text(p.read_text() + "\n")
    with pytest.raises(MarketError, match="hash mismatch"):
        market.history("BTCUSDT", "1h", 1, end_ms)
    with pytest.raises(MarketError, match="midnight"):
        LocalMarket(tmp_path, end_ms + 1)


def test_cli_local_guard_has_no_network(monkeypatch, tmp_path):
    from vortex import cli

    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)

    monkeypatch.setattr(cli, "Market", lambda: pytest.fail("Unexpected REST fallback"))
    with pytest.raises(SystemExit):
        cli.main(["paper", "--ohlcv-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli.main(["backtest", "--days", "30", "--ohlcv-dir", str(tmp_path)])
    with pytest.raises(MarketError, match="exchange_info"):
        cli.main(["backtest", "--days", "30", "--ohlcv-dir", str(tmp_path), "--end-utc", "2026-10-09"])
