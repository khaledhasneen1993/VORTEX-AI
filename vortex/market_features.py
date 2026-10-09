"""Observed derivative snapshot and shared market mathematics."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from .indicators import ema
from .models import Candle


@dataclass(frozen=True)
class Derivatives:
    funding_rate: float
    oi_change_pct: float
    observed_ms: int
    price_change_pct: float | None = None
    interval_ms: int | None = None

    def valid(self, decision_ms: int) -> bool:
        return (
            isfinite(self.funding_rate)
            and isfinite(self.oi_change_pct)
            and (0 <= decision_ms - self.observed_ms <= 5 * 60000)
        )


def _macd_hist(prices: list[float]) -> float:
    if len(prices) < 36:
        return 0.0
    a12, a26 = (ema(prices[:26], 12), sum(prices[:26]) / 26)
    xs = []
    for i, x in enumerate(prices[26:], 26):
        a12 = x * (2 / 13) + a12 * (11 / 13)
        a26 = x * (2 / 27) + a26 * (25 / 27)
        xs.append(a12 - a26)
    if len(xs) < 10:
        return 0.0
    signal = ema(xs, 9)
    return xs[-1] - signal


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sqrt(sum(((x - mean) ** 2 for x in values)) / len(values))


def _vwap(bars: list[Candle]) -> float:
    denom = sum((c.volume for c in bars))
    return sum((c.close * c.volume for c in bars)) / denom if denom > 0 else 0.0
