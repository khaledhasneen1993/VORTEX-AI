"""Completed-price regime labels; no model fitting or forward observations."""

from dataclasses import dataclass
from math import isfinite, sqrt


@dataclass(frozen=True)
class Regime:
    name: str
    reason: str
    bb_width: float | None = None
    efficiency: float | None = None


def classify(bars, percentile, adx5, adx15, policy):
    if not policy.regime_enabled:
        return Regime("disabled", "REGIME_DISABLED")
    if len(bars) < policy.regime_window or percentile is None:
        return Regime("unknown", "REGIME_ABSTAIN_MISSING")
    closes = [b.close for b in bars[-policy.regime_window :]]
    if (
        any(not isfinite(x) or x <= 0 for x in closes)
        or not all(isfinite(x) for x in (percentile, adx5, adx15))
        or not 0 <= percentile <= 100
        or min(adx5, adx15) < 0
    ):
        return Regime("unknown", "REGIME_ABSTAIN_INVALID")
    center = sum(closes) / len(closes)
    width = 4 * sqrt(sum((x - center) ** 2 for x in closes) / len(closes)) / center
    traveled = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    efficiency = abs(closes[-1] - closes[0]) / traveled if traveled else 0.0
    if percentile < policy.regime_dead_percentile and width < policy.regime_min_bb_width:
        return Regime("dead", "REGIME_DEAD_LOW_ATR_NARROW_BB", width, efficiency)
    if (
        adx15 >= policy.trend_adx
        and adx5 >= policy.breakout_adx
        and efficiency >= policy.regime_trend_efficiency
    ):
        return Regime("trend", "REGIME_TREND_DIRECTIONAL", width, efficiency)
    if adx5 < policy.range_adx and adx15 < policy.range_adx and efficiency < policy.regime_trend_efficiency:
        return Regime("range", "REGIME_RANGE_LOW_ADX", width, efficiency)
    return Regime("chop", "REGIME_CHOP_UNCLEAR", width, efficiency)
