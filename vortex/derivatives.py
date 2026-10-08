"""Exchange-timestamped funding rate and independent open-interest observations.

Do NOT interpolate missing exchange observations, infer liquidation events from
ticker volume, or mark a derivative vote from an old cached premium index.
"""
from __future__ import annotations
from math import isfinite
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
        # Both public endpoints expose exchange observation times. Missing
        # timestamps are not permission to pretend a reading is fresh.
        index_ms, oi_ms = int(index["time"]), int(oi["time"])
        if (not isfinite(funding) or not isfinite(current)
                or current <= 0 or
                not (-1000 <= now_ms - index_ms <= 15000)
                or not (-1000 <= now_ms - oi_ms <= 15000)):
            return None
        previous = self.last.get(symbol)
        if previous is not None and oi_ms <= previous[0]:
            return None  # duplicate or out-of-order open-interest event
        self.last[symbol] = (oi_ms, current)
        if not previous or previous[1] <= 0:
            return None
        gap = oi_ms - previous[0]
        if not 60_000 <= gap <= 30 * 60_000:
            return None
        return Derivatives(funding, (current / previous[1] - 1) * 100, min(index_ms, oi_ms))
