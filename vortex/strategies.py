"""Four independent strategy votes, inspired by the reviewed Quant bot.

No claim of copied third-party code. No future candle or fabricated funding/OI.
Vote sources: 15m trend-following, 5m mean-reversion, 5m volume breakout,
and optional contemporaneous extreme funding + rising OI fade.
At least TWO genuinely distinct votes must agree and 1h macro cannot oppose.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, sqrt
from .models import Candle, Signal
from .indicators import ema, rsi, atr, adx


@dataclass(frozen=True)
class Derivatives:
    funding_rate: float
    oi_change_pct: float
    observed_ms: int

    def valid(self, decision_ms: int) -> bool:
        return (isfinite(self.funding_rate) and isfinite(self.oi_change_pct)
                and 0 <= decision_ms - self.observed_ms <= 5 * 60_000)


def _macd_hist(prices: list[float]) -> float:
    if len(prices) < 36:
        return 0.0
    # MACD histogram with real EMA9 on macd series, no future values.
    a12, a26 = ema(prices[:26], 12), sum(prices[:26]) / 26
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
    return sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def _vwap(bars: list[Candle]) -> float:
    denom = sum(c.volume for c in bars)
    return (sum(c.close * c.volume for c in bars) / denom) if denom > 0 else 0.0


def vote(symbol: str, small: list[Candle], higher: list[Candle],
         macro: list[Candle] | None = None, deriv: Derivatives | None = None,
         *, min_score: int = 5) -> Signal | None:
    if len(small) < 70 or len(higher) < 70:
        return None
    s, h = small[-1], higher[-1]
    if s.close_ts <= 0 or h.close_ts > s.close_ts:
        return None
    if macro and (len(macro) < 50 or macro[-1].close_ts > s.close_ts):
        return None
    if any(b.ts <= a.ts for a, b in zip(small[-70:], small[-69:])):
        return None
    p = [x.close for x in small]
    hp = [x.close for x in higher]
    mp = [x.close for x in macro] if macro else hp
    if len(mp) < 36:
        return None
    trend = 1 if ema(mp, 9) > ema(mp, 21) else -1 if ema(mp, 9) < ema(mp, 21) else 0
    volatility = atr(small)
    vol_pct = volatility / s.close
    if not (0.0008 <= vol_pct <= 0.045):
        return None
    avg_vol = sum(c.volume for c in small[-21:-1]) / 20
    if avg_vol <= 0:
        return None
    relative_vol = s.volume / avg_vol
    votes: dict[str, int] = {}
    # Trend following: 15m trend, momentum, ADX and macro bias.
    a = adx(higher)
    if a > 25 and trend:
        long_bias = ema(hp, 9) > ema(hp, 21) and _macd_hist(hp) > 0
        short_bias = ema(hp, 9) < ema(hp, 21) and _macd_hist(hp) < 0
        if long_bias and trend == 1:
            votes["trend"] = 1
        if short_bias and trend == -1:
            votes["trend"] = -1
    # Mean reversion: a reversal near 20-period Bollinger extremum and VWAP.
    last20 = p[-20:]
    center = sum(last20) / 20
    std = _std(last20)
    rv = rsi(p, 7)
    last = small[-1]
    prev = small[-2]
    if std > 0 and adx(small) < 26 and relative_vol >= 0.8:
        if prev.close < center - 1.6 * std and last.close > prev.close and rv < 48 and last.close < _vwap(small[-20:]):
            votes["reversion"] = 1
        if prev.close > center + 1.6 * std and last.close < prev.close and rv > 52 and last.close > _vwap(small[-20:]):
            votes["reversion"] = -1
    # Volume breakout: 20-bar extreme, >2x volume, directional OBV.
    if relative_vol >= 2.0 and adx(small) >= 18:
        lookback = small[-21:-1]
        obv = sum(x.volume * (1 if x.close > older.close else -1 if x.close < older.close else 0)
                  for older, x in zip(small[-9:-1], small[-8:]))
        if s.close > max(c.high for c in lookback) and obv > 0:
            votes["breakout"] = 1
        if s.close < min(c.low for c in lookback) and obv < 0:
            votes["breakout"] = -1
    # Funding fade only from real timestamped exchange derivative readings.
    if deriv and deriv.valid(s.close_ts) and deriv.oi_change_pct > 0:
        if deriv.funding_rate <= -0.0015:
            votes["funding_fade"] = 1
        if deriv.funding_rate >= 0.0015:
            votes["funding_fade"] = -1
    longs = sorted(k for k, direction in votes.items() if direction == 1)
    shorts = sorted(k for k, direction in votes.items() if direction == -1)
    if len(longs) >= 2 and len(longs) > len(shorts) and trend != -1:
        side, agreed, sign = "LONG", longs, 1
    elif len(shorts) >= 2 and len(shorts) > len(longs) and trend != 1:
        side, agreed, sign = "SHORT", shorts, -1
    else:
        return None
    # Strong historical ATR protection, not excessive notional.
    stop = s.close - sign * 1.5 * volatility
    target = s.close + sign * 3.0 * volatility
    score = min(10, 4 + len(agreed) + (1 if relative_vol >= 2 else 0) + (1 if a >= 30 else 0))
    if score < min_score or stop <= 0 or target <= 0:
        return None
    return Signal(symbol, side, s.ts, s.close, stop, target, score,
                  f"2+ confirmations={','.join(agreed)}; macro={trend}; vol={relative_vol:.2f}x")
