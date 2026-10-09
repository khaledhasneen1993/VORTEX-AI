"""Collect verified realized funding/aggregated depth/OI and real filter snapshots.

Archives are evidence, NOT fabricated execution snapshots or pre-settlement forecasts.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from vortex.local_data import digest, identity
from vortex.locks import ProcessLock
from vortex.risk import Filters

VISION = "https://data.binance.vision/data/futures/um"
EXCHANGE = "https://fapi.binance.com/fapi/v1/exchangeInfo"


def validate_csv(path, kind, symbol, period):
    rows = 0
    previous = None
    first = last = None
    non_minute = 0
    unordered = 0
    seen = set()
    duplicates = 0
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "fundingRate": {"calc_time", "funding_interval_hours", "last_funding_rate"},
            "bookDepth": {"timestamp", "percentage", "depth", "notional"},
            "metrics": {"create_time", "symbol", "sum_open_interest", "sum_open_interest_value"},
        }[kind]
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Archive schema mismatch")
        for row in reader:
            if kind == "fundingRate":
                stamp = int(row["calc_time"])
                interval = float(row["funding_interval_hours"])
                rate = float(row["last_funding_rate"])
                if not math.isfinite(rate) or abs(rate) > 1 or not 0 < interval <= 24:
                    raise ValueError("Invalid funding row")
                if previous is not None and stamp <= previous:
                    raise ValueError("Duplicated/unordered funding events")
                non_minute += bool(stamp % 60000)
            else:
                key = "timestamp" if kind == "bookDepth" else "create_time"
                stamp = int(
                    datetime.strptime(row[key], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                    * 1000
                )
                if previous is not None and stamp < previous:
                    if kind == "bookDepth":
                        raise ValueError("Unordered observation")
                    unordered += 1
                if kind == "metrics":
                    if row["symbol"] != symbol:
                        raise ValueError("Invalid OI symbol/duplicate observation")
                    fields = ["sum_open_interest", "sum_open_interest_value"]
                else:
                    percentage = float(row["percentage"])
                    if not math.isfinite(percentage) or percentage == 0:
                        raise ValueError("Invalid depth percentage")
                    fields = ["depth", "notional"]
                if any(not math.isfinite(float(row[k])) or float(row[k]) < 0 for k in fields):
                    raise ValueError("Invalid observation values")
            actual = datetime.fromtimestamp(stamp / 1000, timezone.utc).date().isoformat()
            if not actual.startswith(period):
                raise ValueError("Archive timestamp outside requested period")
            if kind == "metrics":
                duplicates += stamp in seen
                seen.add(stamp)
            first = stamp if first is None else min(first, stamp)
            last = stamp if last is None else max(last, stamp)
            previous = stamp
            rows += 1
    if not rows:
        raise ValueError("Empty supplemental archive")
    return dict(
        rows=rows,
        first_ms=first,
        last_ms=last,
        non_minute_timestamps=non_minute,
        unordered_transitions=unordered,
        duplicate_timestamps=duplicates,
        continuous_coverage_proven=False,
    )


def archive(root, symbol, kind, period, session):
    identity(symbol, "1m")
    if kind not in {"fundingRate", "bookDepth", "metrics"}:
        raise ValueError("Unsupported supplemental kind")
    date.fromisoformat(period + "-01" if kind == "fundingRate" else period)
    frequency = "monthly" if kind == "fundingRate" else "daily"
    name = f"{symbol}-{kind}-{period}"
    url = f"{VISION}/{frequency}/{kind}/{symbol}/{name}.zip"
    folder = Path(root) / "supplemental" / symbol / kind
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (name + ".csv")
    manifest = target.with_suffix(".json")
    with ProcessLock(folder / (name + ".lock")):
        if target.exists() or manifest.exists():
            if not (target.exists() and manifest.exists()):
                raise ValueError("Partial supplemental cache; refusing overwrite")
            record = json.loads(manifest.read_text())
            if digest(target) != record["csv_sha256"]:
                raise ValueError("Supplemental cache hash mismatch")
            return record
        checksum = session.get(url + ".CHECKSUM", timeout=25)
        checksum.raise_for_status()
        expected = checksum.text.split()[0].lower()
        if len(expected) != 64 or any(x not in "0123456789abcdef" for x in expected):
            raise ValueError("Invalid publisher checksum")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            zipped = Path(tmp) / "archive.zip"
            with session.get(url, stream=True, timeout=25) as response:
                response.raise_for_status()
                with zipped.open("wb") as f:
                    size = 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 20000000:
                            raise ValueError("Archive exceeds low-memory size cap")
                        f.write(chunk)
            if digest(zipped) != expected:
                raise ValueError("Supplemental publisher SHA256 mismatch")
            staged = Path(tmp) / "archive.csv"
            with zipfile.ZipFile(zipped) as z:
                if z.namelist() != [name + ".csv"] or z.infolist()[0].file_size > 50000000:
                    raise ValueError("Unsafe/unexpected archive member")
                with z.open(name + ".csv") as src, staged.open("wb") as out:
                    while chunk := src.read(65536):
                        out.write(chunk)
            quality = validate_csv(staged, kind, symbol, period)
            record = dict(
                url=url,
                archive_sha256=expected,
                csv_sha256=digest(staged),
                fetched_utc=datetime.now(timezone.utc).isoformat(),
                kind=kind,
                symbol=symbol,
                period=period,
                **quality,
            )
            record["use_limitations"] = {
                "fundingRate": "Realized rates only; no settlement mark or prior forecast. Preserve raw timestamps.",
                "bookDepth": "Aggregated percent bands, not price-level book/bid/ask or proven 20bps liquidity.",
                "metrics": "Sparse OI observations; do not fabricate freshness or fill gaps.",
            }[kind]
            meta = Path(tmp) / "manifest.json"
            meta.write_text(json.dumps(record, indent=2) + "\n")
            os.replace(staged, target)
            os.replace(meta, manifest)
            return record


def fetch_filters(root, symbols, session):
    """Current genuine filters only; NEVER claim this is historical as-of data."""
    path = Path(root) / "exchange_info.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with ProcessLock(path.with_suffix(".lock")):
        if path.exists() or path.with_suffix(".manifest.json").exists():
            raise ValueError("Filter snapshot exists; preserve it, choose a separate output directory")
        response = session.get(EXCHANGE, timeout=25)
        response.raise_for_status()
        data = response.json()
        selected = {x["symbol"]: x for x in data["symbols"]}
        for symbol in symbols:
            identity(symbol, "1m")
            info = selected[symbol]
            if info.get("quoteAsset") != "USDT" or info.get("contractType") != "PERPETUAL":
                raise ValueError("Wrong contract type")
            kinds = {x["filterType"] for x in info["filters"]}
            if not {"PRICE_FILTER", "LOT_SIZE", "MIN_NOTIONAL"} <= kinds:
                raise ValueError("Incomplete actual exchange filters")
            f = Filters.from_exchange(info)
            if not all(math.isfinite(x) and x > 0 for x in (f.tick, f.step, f.min_qty, f.min_notional)):
                raise ValueError("Invalid actual exchange filters")
        record = dict(
            url=EXCHANGE,
            fetched_utc=datetime.now(timezone.utc).isoformat(),
            sha256=None,
            historical_asof_proven=False,
            limitation="Current snapshot only, not historical filter changes",
        )
        with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
            staged = Path(tmp) / "exchange.json"
            staged.write_bytes(response.content)
            record["sha256"] = digest(staged)
            meta = Path(tmp) / "manifest.json"
            meta.write_text(json.dumps(record, indent=2) + "\n")
            os.replace(staged, path)
            os.replace(meta, path.with_suffix(".manifest.json"))
        return record


def fetch_funding(root, symbol, start, end, session):
    """Read public realized settlement rates/marks, preserving every raw page."""
    identity(symbol, "1m")
    if not 0 < (end - start).days <= 110:
        raise ValueError("Funding REST range must be 1..110 days")
    begin = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp() * 1000)
    finish = int(datetime.combine(end, datetime.min.time(), timezone.utc).timestamp() * 1000)
    folder = Path(root) / "supplemental" / symbol / "fundingREST" / f"{start}_{end}"
    folder.mkdir(parents=True, exist_ok=False)
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    rows, pages = [], []
    cursor = begin
    for number in range(20):
        params = dict(symbol=symbol, startTime=cursor, endTime=finish - 1, limit=1000)
        response = session.get(url, params=params, timeout=25)
        page = folder / f"page-{number:02d}.json"
        page.write_bytes(response.content)
        pages.append(dict(url=url, params=params, file=page.name, sha256=digest(page)))
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Invalid funding response")
        previous = cursor - 1
        for item in batch:
            stamp = int(item["fundingTime"])
            rate, mark = float(item["fundingRate"]), float(item["markPrice"])
            if (
                item["symbol"] != symbol
                or not previous < stamp < finish
                or not math.isfinite(rate)
                or abs(rate) > 1
                or not math.isfinite(mark)
                or mark <= 0
            ):
                raise ValueError("Invalid funding settlement row")
            previous = stamp
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = previous + 1
    else:
        raise ValueError("Funding pagination cap reached; partial data preserved")
    if not rows:
        raise ValueError("No funding settlements returned")
    record = dict(
        url=url,
        symbol=symbol,
        start_ms=begin,
        end_exclusive_ms=finish,
        fetched_utc=datetime.now(timezone.utc).isoformat(),
        rows=len(rows),
        first_ms=int(rows[0]["fundingTime"]),
        last_ms=int(rows[-1]["fundingTime"]),
        pages=pages,
        pagination_complete=True,
        continuous_coverage_proven=False,
        use_limitations="Realized funding and settlement marks only; not pre-event forecasts",
    )
    (folder / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    p.add_argument("--funding-months", nargs="*", default=[])
    p.add_argument("--metrics-dates", nargs="*", default=[])
    p.add_argument("--depth-dates", nargs="*", default=[])
    p.add_argument("--fetch-filters", action="store_true")
    p.add_argument("--funding-rest-start", type=date.fromisoformat)
    p.add_argument("--funding-rest-end", type=date.fromisoformat, help="Exclusive UTC date")
    p.add_argument("--output", default="data/ohlcv")
    p.add_argument("--evidence", required=True, help="New JSON report; never overwrite")
    args = p.parse_args()
    if bool(args.funding_rest_start) != bool(args.funding_rest_end):
        p.error("Supply both funding REST dates")
    if args.funding_rest_start and not 0 < (args.funding_rest_end - args.funding_rest_start).days <= 110:
        p.error("Funding REST range must be 1..110 days")
    requests_to_make = sum(map(len, [args.funding_months, args.metrics_dates, args.depth_dates])) * len(
        args.symbols
    )
    requests_to_make += len(args.symbols) if args.funding_rest_start else 0
    if requests_to_make > 300 or not (requests_to_make or args.fetch_filters):
        p.error("Request 1..300 archives and/or filters")
    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with (
        evidence.open("x") as f,
        ProcessLock(Path(args.output) / "supplemental-collection.lock"),
        requests.Session() as session,
    ):

        def collect(label, action):
            try:
                result = dict(request=label, status="downloaded_verified", source=action())
            except (requests.RequestException, ValueError, KeyError, zipfile.BadZipFile) as exc:
                response = getattr(exc, "response", None)
                result = dict(
                    request=label,
                    status="unavailable_or_invalid",
                    error=type(exc).__name__,
                    message=str(exc),
                    http_status=getattr(response, "status_code", None),
                )
            results.append(result)
            f.seek(0)
            json.dump(
                dict(
                    collected_utc=datetime.now(timezone.utc).isoformat(),
                    results=results,
                    full_baseline_ready=False,
                    performance_metrics=None,
                ),
                f,
                indent=2,
            )
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
            print(label, result["status"], result.get("http_status"), flush=True)

        if args.funding_rest_start:
            for symbol in args.symbols:
                collect(
                    f"{symbol} funding REST",
                    lambda s=symbol: fetch_funding(
                        args.output, s, args.funding_rest_start, args.funding_rest_end, session
                    ),
                )
        if args.fetch_filters:
            collect("exchangeInfo current filters", lambda: fetch_filters(args.output, args.symbols, session))
        for kind, periods in [
            ("fundingRate", args.funding_months),
            ("metrics", args.metrics_dates),
            ("bookDepth", args.depth_dates),
        ]:
            for symbol in args.symbols:
                for period in periods:
                    collect(
                        f"{symbol} {kind} {period}",
                        lambda s=symbol, k=kind, t=period: archive(args.output, s, k, t, session),
                    )


if __name__ == "__main__":
    main()
