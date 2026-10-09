"""Strict, read-only USD-M archive candles; no network or invented metadata."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from .binance import MarketError
from .models import Candle
from .risk import Filters

STEPS = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}


def identity(symbol, interval):
    if not re.fullmatch(r"[A-Z0-9_]+USDT", symbol) or interval not in STEPS:
        raise MarketError("Invalid archive symbol/interval")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path, interval):
    """Stream rows, rejecting bad OHLC, non-finite values and time gaps."""
    step = STEPS[interval]
    previous = None
    with Path(path).open(newline="") as f:
        for row in csv.reader(f):
            if row and row[0] == "open_time":
                if previous is not None:
                    raise MarketError("Unexpected repeated CSV header")
                continue
            try:
                c = Candle.from_binance(row)
                values = [c.open, c.high, c.low, c.close, c.volume, c.taker_buy_volume]
                if (
                    not all(v is not None and math.isfinite(v) for v in values)
                    or not c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high
                    or c.volume < 0
                    or not 0 <= c.taker_buy_volume <= c.volume
                    or c.ts % step
                    or c.close_ts != c.ts + step - 1
                    or (previous is not None and c.ts != previous + step)
                ):
                    raise ValueError("Invalid OHLCV/time sequence")
            except (ValueError, TypeError, IndexError) as exc:
                raise MarketError(f"Malformed archive CSV: {path}") from exc
            previous = c.ts
            yield c


class LocalMarket:
    def __init__(self, root, end_ms):
        self.root = Path(root)
        self.end_ms = end_ms
        self.sources = {}
        if end_ms <= 0 or end_ms % 86400000:
            raise MarketError("Local end must be a UTC midnight (exclusive)")

    def server_ms(self):
        return self.end_ms

    def metadata(self):
        path = self.root / "exchange_info.json"
        if not path.exists():
            raise MarketError("Missing local exchange_info.json: real exchange filters required")
        data = json.loads(path.read_text())
        self.sources[str(path)] = {
            "sha256": digest(path),
            "kind": "exchange_filters",
            "asof_validated": False,
        }
        return {
            s["symbol"]: s
            for s in data["symbols"]
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
        }

    def symbol_filters(self, symbol):
        return Filters.from_exchange(self.metadata()[symbol])

    def history(self, symbol, interval, days, now_ms):
        identity(symbol, interval)
        if not 1 <= days <= 90 or now_ms != self.end_ms:
            raise MarketError("Invalid local history range")
        warmup = 10 if interval == "1h" else 2
        start = now_ms - (days + warmup) * 86400000
        cursor = start
        bars = []
        while cursor < now_ms:
            day = datetime.fromtimestamp(cursor / 1000, timezone.utc).date().isoformat()
            path = self.root / symbol / interval / f"{symbol}-{interval}-{day}.csv"
            manifest = path.with_suffix(".json")
            if not path.exists() or not manifest.exists():
                raise MarketError(f"Missing verified archive day: {path}")
            record = json.loads(manifest.read_text())
            if record["csv_sha256"] != digest(path):
                raise MarketError(f"Archive hash mismatch: {path}")
            self.sources[str(path)] = record
            daily = list(read_csv(path, interval))
            if not daily or daily[0].ts != cursor or daily[-1].close_ts != cursor + 86400000 - 1:
                raise MarketError(f"Incomplete archive day: {path}")
            bars.extend(daily)
            cursor += 86400000
        return bars
