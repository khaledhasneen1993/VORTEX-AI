"""Read-only Binance USD-M public market data gateway."""

from __future__ import annotations

import time
from math import isfinite

import requests

from . import __version__
from .models import Candle
from .risk import Filters

BASE = "https://fapi.binance.com"
TESTNET = "https://testnet.binancefuture.com"


class MarketError(RuntimeError):
    pass


class Market:
    def __init__(self, base: str = BASE, session: requests.Session | None = None, *, resilient: bool = False):
        if base not in {BASE, TESTNET}:
            raise ValueError("Exchange endpoint must be allowlisted")
        self.base = base
        self.resilient = resilient
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": f"VortexAI-paper/{__version__}"})
        self._exchange: dict | None = None

    def get(self, path: str, params: dict | None = None):
        if path not in {
            "/fapi/v1/time",
            "/fapi/v1/exchangeInfo",
            "/fapi/v1/klines",
            "/fapi/v1/ticker/bookTicker",
            "/fapi/v1/depth",
            "/fapi/v1/aggTrades",
            "/fapi/v1/ticker/24hr",
            "/fapi/v1/premiumIndex",
            "/fapi/v1/openInterest",
        }:
            raise MarketError("Public endpoints only")
        for n in range(3):
            try:
                response = self.http.get(
                    self.base + path, params=params, timeout=(3, 6) if self.resilient else 12
                )
                if response.status_code in {418, 429}:
                    wait = min(30, int(response.headers.get("Retry-After", "2")))
                    time.sleep(max(1, wait))
                    continue
                if response.status_code >= 500:
                    time.sleep(2**n)
                    continue
                response.raise_for_status()
                result = response.json()
                if isinstance(result, dict) and result.get("code", 0) < 0:
                    raise MarketError(str(result))
                return result
            except (requests.RequestException, ValueError) as exc:
                if n == 2:
                    raise MarketError(f"Binance request failed: {path}") from exc
                time.sleep(2**n)
        raise MarketError("Binance unavailable; no market decisions")

    def server_ms(self) -> int:
        return int(self.get("/fapi/v1/time")["serverTime"])

    def metadata(self) -> dict:
        if self._exchange is None:
            self._exchange = {
                s["symbol"]: s
                for s in self.get("/fapi/v1/exchangeInfo")["symbols"]
                if s.get("status") == "TRADING"
                and s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
            }
        return self._exchange

    def symbol_filters(self, symbol: str) -> Filters:
        return Filters.from_exchange(self.metadata()[symbol])

    def candles(self, symbol: str, interval: str, limit: int, now_ms: int) -> list[Candle]:
        if (
            symbol not in self.metadata()
            or interval not in {"1m", "5m", "15m", "1h"}
            or not 1 <= limit <= 1500
        ):
            raise MarketError("Invalid symbol, timeframe or limit")
        raw = self.get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        data = [Candle.from_binance(row) for row in raw]
        closed = [c for c in data if c.close_ts < now_ms]
        if any(x.ts >= y.ts for x, y in zip(closed, closed[1:])):
            raise MarketError("Non-monotone candles; reject market data")
        return closed

    def quotes(self, *, now_ms: int | None = None, max_age_ms: int = 4000) -> dict[str, tuple[float, float]]:
        """Return ONLY fresh exchange-timestamped executable REST quotes.

        Do not silently accept a stale cached bookTicker from an idle contract.
        The USD-M endpoint publishes exchange transaction time in `time`.
        """
        if not 500 <= max_age_ms <= 10000:
            raise ValueError("Invalid market data freshness bound")
        now = self.server_ms() if now_ms is None else now_ms
        raw = self.get("/fapi/v1/ticker/bookTicker")
        if isinstance(raw, dict):
            raw = [raw]
        if self.resilient:
            now = self.server_ms()  # Validate after the quote request, not the old cycle clock.
        out: dict[str, tuple[float, float]] = {}
        for row in raw:
            try:
                bid, ask = float(row["bidPrice"]), float(row["askPrice"])
                event_ms = int(row["time"])
                lag = now - event_ms
                if isfinite(bid) and isfinite(ask) and 0 < bid <= ask and -1000 <= lag <= max_age_ms:
                    out[row["symbol"]] = (bid, ask)
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def history(self, symbol: str, interval: str, days: int, now_ms: int) -> list[Candle]:
        """Paginate completed candles over 1..45 days with indicator warmup.

        Binance rows must be strictly contiguous (fail rather than silently mask gaps).
        """
        if symbol not in self.metadata() or interval not in {"1m", "5m", "15m", "1h"} or not 1 <= days <= 45:
            raise MarketError("Invalid history request")
        step = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}[interval]
        # EMA200 on completed 1h candles needs >= 200 hours of pre-roll.
        # Two days is insufficient and silently discards first-week signals.
        warmup_days = 10 if interval == "1h" else 2
        start = ((now_ms - (days + warmup_days) * 86_400_000) // step) * step
        cursor = start
        end = now_ms - 1
        candles: list[Candle] = []
        while cursor < end:
            raw = self.get(
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end, "limit": 1500},
            )
            if not raw:
                break
            batch = [Candle.from_binance(row) for row in raw]
            batch = [c for c in batch if c.close_ts < now_ms and c.ts >= cursor]
            if not batch:
                break
            if candles and batch[0].ts != candles[-1].ts + step:
                raise MarketError("Historical candle gap / overlap")
            if any(y.ts != x.ts + step for x, y in zip(batch, batch[1:])):
                raise MarketError("Incomplete historical candles")
            candles.extend(batch)
            nxt = batch[-1].ts + step
            if nxt <= cursor:
                raise MarketError("Pagination stalled")
            cursor = nxt
            if len(raw) < 1500:
                break
        if len(candles) < 100:
            raise MarketError("Insufficient historical data; cannot infer backtest profitability")
        return candles
