"""Indicators operate on completed candles only; no external TA dependencies."""
from __future__ import annotations
from math import isfinite
from .models import Candle


def ema(series: list[float], period: int) -> float:
    if len(series) < period or period < 1:
        raise ValueError("Insufficient EMA history")
    value = sum(series[:period]) / period
    a = 2.0 / (period + 1)
    for x in series[period:]:
        value = x * a + value * (1 - a)
    return value


def rsi(series: list[float], period: int = 14) -> float:
    if len(series) <= period:
        raise ValueError("Insufficient RSI history")
    changes = [series[i] - series[i - 1] for i in range(1, len(series))]
    gain = sum(max(x, 0) for x in changes[:period]) / period
    loss = sum(max(-x, 0) for x in changes[:period]) / period
    for x in changes[period:]:
        gain = (gain * (period - 1) + max(x, 0)) / period
        loss = (loss * (period - 1) + max(-x, 0)) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) <= period:
        raise ValueError("Insufficient ATR history")
    true_ranges = [
        max(c.high - c.low, abs(c.high - candles[i - 1].close),
            abs(c.low - candles[i - 1].close))
        for i, c in enumerate(candles) if i
    ]
    result = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        result = ((period - 1) * result + tr) / period
    return result


def adx(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period * 2 + 1:
        raise ValueError("Insufficient ADX history")
    tr, pos, neg = [], [], []
    for old, new in zip(candles[:-1], candles[1:]):
        up, down = new.high - old.high, old.low - new.low
        tr.append(max(new.high - new.low, abs(new.high - old.close), abs(new.low - old.close)))
        pos.append(up if up > down and up > 0 else 0.0)
        neg.append(down if down > up and down > 0 else 0.0)
    t, p, n = sum(tr[:period]), sum(pos[:period]), sum(neg[:period])
    dx: list[float] = []
    for i in range(period - 1, len(tr)):
        if i != period - 1:
            t = t - t / period + tr[i]
            p = p - p / period + pos[i]
            n = n - n / period + neg[i]
        plus, minus = 100 * p / t if t else 0, 100 * n / t if t else 0
        dx.append(100 * abs(plus - minus) / (plus + minus) if plus + minus else 0)
    value = sum(dx[:period]) / period
    for x in dx[period:]:
        value = (value * (period - 1) + x) / period
    return value if isfinite(value) else 0.0
