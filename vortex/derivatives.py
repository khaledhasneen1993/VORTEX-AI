"""Time-bounded funding-rate / open-interest snapshots for fourth strategy.

Never infer open interest change from price, liquidation estimates or a single
snapshot. Funding and OI must be actual USD-M public endpoint readings.
"""
from __future__ import annotations
from dataclasses import dataclass
from .strategies import Derivatives


class DerivativesTracker:
    def __init__(self):
        self.last: dict[str, tuple[int, float]] = {}

    def sample(self, market, symbol: str, now_ms: int) -> Derivatives | None:
        index = market.get("/fapi/v1/premiumIndex", {"symbol": symbol})
        oi = market.get("/fapi/v1/openInterest", {"symbol": symbol})
        if index.get("symbol") != symbol or oi.get("symbol") != symbol:
            raise ValueError("Derivative response symbol mismatch")
        funding = float(index["lastFundingRate"])
        current = float(oi["openInterest"])
        previous = self.last.get(symbol)
        self.last[symbol] = (now_ms, current)
        if current <= 0 or not previous or previous[1] <= 0:
            return None
        gap = now_ms - previous[0]
        # Compare genuinely time-separated observations, not same-moment noise.
        if gap < 60_000 or gap > 30 * 60_000:
            return None
        return Derivatives(funding, (current / previous[1] - 1) * 100, now_ms)
