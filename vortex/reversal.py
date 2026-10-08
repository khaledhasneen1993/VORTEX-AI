"""Completed 1-minute RSI divergence + Stochastic RSI confirmation.

A single observation of RSI under 30 is NOT a divergence. Compare two
non-overlapping swing extremums and actual RSI at each extremum. No future bars.
"""
from __future__ import annotations
from .models import Candle
from .indicators import rsi


def stoch_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < 2 * period + 2:
        raise ValueError("Insufficient Stochastic RSI candles")
    rs = [rsi(prices[:i], period) for i in range(len(prices) - period, len(prices) + 1)]
    low, high = min(rs), max(rs)
    return 50.0 if high == low else 100 * (rs[-1] - low) / (high - low)


def confirm(bars: list[Candle], direction: int, close_ms: int) -> bool:
    """Divergence from known extrema, corroborated by StochRSI reversal."""
    if direction not in {-1, 1}:
        raise ValueError("direction must be +1 or -1")
    recent = [b for b in bars if b.close_ts <= close_ms][-85:]
    if len(recent) < 85 or any(b.ts >= a.ts for b, a in zip(recent, recent[1:])):
        return False
    prior = recent[-34:-18]
    latest = recent[-17:-1]
    if direction == 1:
        i1 = min(range(len(prior)), key=lambda j: prior[j].low)
        i2 = min(range(len(latest)), key=lambda j: latest[j].low)
        first, second = prior[i1], latest[i2]
        extreme_ok = second.low < first.low
    else:
        i1 = max(range(len(prior)), key=lambda j: prior[j].high)
        i2 = max(range(len(latest)), key=lambda j: latest[j].high)
        first, second = prior[i1], latest[i2]
        extreme_ok = second.high > first.high
    if not extreme_ok:
        return False
    prices = [b.close for b in recent]
    idx1 = len(recent) - 34 + i1
    idx2 = len(recent) - 17 + i2
    r1, r2 = rsi(prices[:idx1 + 1]), rsi(prices[:idx2 + 1])
    bullish = direction == 1 and r2 > r1 + 1.0
    bearish = direction == -1 and r2 < r1 - 1.0
    if not (bullish or bearish):
        return False
    oscillator = stoch_rsi(prices)
    prev_oscillator = stoch_rsi(prices[:-1])
    return (oscillator > prev_oscillator and 15 < oscillator < 65) if direction == 1 else (
        oscillator < prev_oscillator and 35 < oscillator < 85)
