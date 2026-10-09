"""Exchange-timestamped funding rate and independent open-interest observations.

Do NOT interpolate missing exchange observations, infer liquidation events from
ticker volume, or mark a derivative vote from an old cached premium index.
"""
from __future__ import annotations
from math import isfinite
import logging
from .strategies import Derivatives

log = logging.getLogger("vortex.votes")


class DerivativesTracker:
    def __init__(self):
        self.last: dict[str, tuple[int, float]] = {}
        self.funding_timing = {}
        self.prices: dict[str, float] = {}
        self.checked_ms: int | None = None

    def timing(self, market, symbol: str):
        """Refresh funding timing without changing the independent OI vote interval."""
        index = market.get('/fapi/v1/premiumIndex', {'symbol': symbol})
        checked = market.server_ms()
        self.funding_timing.pop(symbol, None)
        rate = float(index['lastFundingRate'])
        stamp, next_ms = int(index['time']), int(index['nextFundingTime'])
        if index.get('symbol') != symbol or not isfinite(rate):
            return None
        if not 0 <= checked-stamp <= 15000 or next_ms <= checked:
            return None
        snapshot = (stamp, rate, next_ms)
        self.funding_timing[symbol] = snapshot
        return snapshot

    def sample(self, market, symbol: str, now_ms: int) -> Derivatives | None:
        self.checked_ms = None
        def abstain(reason):
            log.debug("DERIVATIVE %s status=ABSTAIN reason=%s", symbol, reason)
            return None

        index = market.get("/fapi/v1/premiumIndex", {"symbol": symbol})
        oi = market.get("/fapi/v1/openInterest", {"symbol": symbol})
        # The cycle-start clock predates these sequential requests. Validate
        # against exchange time observed AFTER both responses, never their own
        # timestamps or a fabricated local offset.
        self.checked_ms = market.server_ms()
        checked = self.checked_ms
        if index.get("symbol") != symbol or oi.get("symbol") != symbol:
            raise ValueError("Derivative response symbol mismatch")
        funding = float(index["lastFundingRate"])
        current = float(oi["openInterest"])
        # Both public endpoints expose exchange observation times. Missing
        # timestamps are not permission to pretend a reading is fresh.
        index_ms, oi_ms = int(index["time"]), int(oi["time"])
        if not isfinite(funding) or not isfinite(current) or current <= 0:
            return abstain("invalid_funding_or_open_interest")
        for name, stamp in (("funding", index_ms), ("open_interest", oi_ms)):
            age = checked - stamp
            if age < -1000:
                return abstain(f"future_{name}_timestamp age_ms={age}")
            if age > 15000:
                return abstain(f"stale_{name}_timestamp age_ms={age}")
        next_funding = int(index.get('nextFundingTime', 0))
        if next_funding > checked:
            self.funding_timing[symbol] = (index_ms, funding, next_funding)
        previous = self.last.get(symbol)
        if previous is not None and oi_ms <= previous[0]:
            return abstain("duplicate_or_out_of_order_open_interest")
        old_price = self.prices.get(symbol)
        mark = float(index.get("markPrice", "nan"))
        if isfinite(mark) and mark > 0:
            self.prices[symbol] = mark
        else:
            self.prices.pop(symbol, None)
        self.last[symbol] = (oi_ms, current)
        if not previous or previous[1] <= 0:
            return abstain("first_open_interest_observation")
        gap = oi_ms - previous[0]
        if not 60_000 <= gap <= 30 * 60_000:
            return abstain(f"open_interest_interval_outside_bounds gap_ms={gap}")
        change = (current / previous[1] - 1) * 100
        log.debug("DERIVATIVE %s status=VALID funding_rate=%.6f oi_change_pct=%.4f checked_ms=%d cycle_ms=%d",
                  symbol, funding, change, checked, now_ms)
        price_change = ((mark / old_price - 1) * 100
                        if old_price and isfinite(mark) and mark > 0 else None)
        return Derivatives(funding, change, min(index_ms, oi_ms), price_change, gap)
