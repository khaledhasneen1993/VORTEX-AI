"""Aggressive but deterministic multi-timeframe breakout + momentum scoring.

Signals are formed using CLOSED 5m candles; 15m bias is restricted to candles
whose close occurred on/before the 5m signal close (no future data).
Whale/liquidation claims and untrained AI scoring are intentionally excluded.
"""
from __future__ import annotations
from .indicators import ema, rsi, atr, adx
from .models import Candle, Signal


def analyze(symbol: str, candles: list[Candle], higher: list[Candle], min_score: int = 5) -> Signal | None:
    if len(candles) < 65 or len(higher) < 35:
        return None
    latest = candles[-1]
    if latest.close_ts <= 0 or higher[-1].close_ts > latest.close_ts:
        return None
    if candles[-2].ts >= latest.ts:
        return None
    prices = [c.close for c in candles]
    hp = [c.close for c in higher]
    fast, slow = ema(prices, 9), ema(prices, 21)
    hi_fast, hi_slow = ema(hp, 9), ema(hp, 21)
    v_avg = sum(c.volume for c in candles[-21:-1]) / 20
    if v_avg <= 0:
        return None
    relative_volume = latest.volume / v_avg
    volatility = atr(candles, 14)
    volatility_pct = volatility / latest.close
    if not (0.0008 <= volatility_pct <= 0.045) or relative_volume < 1.15:
        return None
    strength = adx(candles, 14)
    if strength < 18:
        return None
    oscillator = rsi(prices, 7)
    prev_high = max(c.high for c in candles[-13:-1])
    prev_low = min(c.low for c in candles[-13:-1])
    trend_long = fast > slow and hi_fast > hi_slow
    trend_short = fast < slow and hi_fast < hi_slow
    momentum = (prices[-1] / prices[-4] - 1) if prices[-4] else 0
    if trend_long and latest.close > prev_high and 52 <= oscillator <= 82 and momentum > 0:
        side = "LONG"
        score = 3 + (2 if relative_volume >= 1.7 else 1) + (1 if strength >= 25 else 0) + (1 if momentum >= volatility_pct else 0)
        reason = f"LONG breakout, vol={relative_volume:.2f}x, ADX={strength:.1f}, RSI={oscillator:.1f}"
        stop = latest.close - 1.5 * volatility
        target = latest.close + 2.5 * volatility
    elif trend_short and latest.close < prev_low and 18 <= oscillator <= 48 and momentum < 0:
        side = "SHORT"
        score = 3 + (2 if relative_volume >= 1.7 else 1) + (1 if strength >= 25 else 0) + (1 if -momentum >= volatility_pct else 0)
        reason = f"SHORT breakout, vol={relative_volume:.2f}x, ADX={strength:.1f}, RSI={oscillator:.1f}"
        stop = latest.close + 1.5 * volatility
        target = latest.close - 2.5 * volatility
    else:
        return None
    if score < min_score or target <= 0:
        return None
    return Signal(symbol, side, latest.ts, latest.close, stop, target, score, reason)
