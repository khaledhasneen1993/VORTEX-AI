"""Download official daily USD-M archives, verify publisher checksum, stream CSV."""

from __future__ import annotations
import argparse
import json
import os
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from vortex.local_data import digest, identity, read_csv
from vortex.locks import ProcessLock

BASE = "https://data.binance.vision/data/futures/um/daily/klines"


def download_day(root, symbol, interval, day, session):
    identity(symbol, interval)
    name = f"{symbol}-{interval}-{day.isoformat()}"
    folder = Path(root) / symbol / interval
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / (name + ".csv")
    manifest = folder / (name + ".json")
    with ProcessLock(folder / (name + ".lock")):
        if csv_path.exists() or manifest.exists():
            if not (csv_path.exists() and manifest.exists()):
                raise ValueError("Partial cache; preserve and inspect before retry")
            record = json.loads(manifest.read_text())
            if digest(csv_path) != record["csv_sha256"]:
                raise ValueError("Cached CSV hash mismatch; refusing overwrite")
            return record
        url = f"{BASE}/{symbol}/{interval}/{name}.zip"
        checksum = session.get(url + ".CHECKSUM", timeout=30)
        checksum.raise_for_status()
        expected = checksum.text.split()[0]
        if len(expected) != 64 or any(x not in "0123456789abcdef" for x in expected.lower()):
            raise ValueError("Invalid publisher checksum")
        # Temporary files avoid holding ZIP/CSV contents in RAM; never extract paths.
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            archive = Path(tmp) / (name + ".zip")
            with session.get(url, timeout=30, stream=True) as response:
                response.raise_for_status()
                with archive.open("wb") as f:
                    size = 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 20000000:
                            raise ValueError("Daily archive exceeds size cap")
                        f.write(chunk)
            if digest(archive).lower() != expected.lower():
                raise ValueError("Publisher SHA256 mismatch")
            staged = Path(tmp) / (name + ".csv")
            with zipfile.ZipFile(archive) as z:
                if z.namelist() != [name + ".csv"] or z.infolist()[0].file_size > 50000000:
                    raise ValueError("Unexpected archive contents")
                with z.open(name + ".csv") as source, staged.open("wb") as target:
                    while chunk := source.read(65536):
                        target.write(chunk)
            first = last = None
            count = 0
            for bar in read_csv(staged, interval):
                first = bar.ts if first is None else first
                last = bar.close_ts
                count += 1
            start = int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp() * 1000)
            if first != start or last != start + 86400000 - 1:
                raise ValueError("Incomplete archive day")
            record = dict(
                url=url,
                downloaded_utc=datetime.now(timezone.utc).isoformat(),
                archive_sha256=expected,
                csv_sha256=digest(staged),
                symbol=symbol,
                interval=interval,
                rows=count,
                first_ms=first,
                last_ms=last,
            )
            staged_manifest = Path(tmp) / "manifest.json"
            staged_manifest.write_text(json.dumps(record, indent=2) + "\n")
            os.replace(staged, csv_path)
            os.replace(staged_manifest, manifest)
        return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    p.add_argument("--intervals", nargs="+", default=["1m", "5m", "15m", "1h"])
    p.add_argument("--start", required=True, type=date.fromisoformat)
    p.add_argument("--end", required=True, type=date.fromisoformat, help="Exclusive UTC date")
    p.add_argument("--output", default="data/ohlcv")
    args = p.parse_args()
    if not 0 < (args.end - args.start).days <= 110:
        p.error("Range must be 1..110 days, including warmup")
    with requests.Session() as session:
        for symbol in args.symbols:
            for interval in args.intervals:
                identity(symbol, interval)
                day = args.start
                while day < args.end:
                    r = download_day(args.output, symbol, interval, day, session)
                    print(symbol, interval, day, r["rows"], flush=True)
                    day += timedelta(days=1)


if __name__ == "__main__":
    main()
