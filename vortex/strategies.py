"""Four independent strategy votes, inspired by the reviewed Quant bot.

No claim of copied third-party code. No future candle or fabricated funding/OI.
Vote sources: 15m trend-following, 5m mean-reversion, 5m volume breakout,
and optional contemporaneous extreme funding + rising OI fade.
At least TWO genuinely distinct votes must agree and 1h macro cannot oppose.
"""
from __future__ import annotations
from dataclasses import dataclass
import logging

log = logging.getLogger("vortex.votes")
from math import isfinite, sqrt
from .models import Candle, Signal
from .indicators import ema, rsi, atr, adx
from .reversal import confirm as confirm_1m


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
         *, min_score: int = 5, decision_ms: int | None = None,
         minute: list[Candle] | None = None, strict_votes: bool = True,
         min_strong_score: int = 7) -> Signal | None:
    if len(small) < 70 or len(higher) < 70:
        return None
    s, h = small[-1], higher[-1]
    if s.close_ts <= 0 or h.close_ts > s.close_ts:
        return None
    if macro is not None and (len(macro) < 210 or macro[-1].close_ts > s.close_ts):
        return None
    if any(b.ts <= a.ts for a, b in zip(small[-70:], small[-69:])):
        return None
    p = [x.close for x in small]
    hp = [x.close for x in higher]
    mp = [x.close for x in macro] if macro else hp
    if len(mp) < 36:
        return None
    # Literal original Quant macro filter: hourly EMA50 versus EMA200.
    if macro is not None:
        short_macro, long_macro = ema(mp, 50), ema(mp, 200)
    else:
        short_macro, long_macro = ema(mp, 9), ema(mp, 21)
    trend = 1 if short_macro > long_macro else -1 if short_macro < long_macro else 0
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
        if (prev.close < center - 1.6 * std and last.close > prev.close and rv < 48
                and last.close < _vwap(small[-20:]) and minute is not None
                and confirm_1m(minute, 1, s.close_ts)):
            votes["reversion"] = 1
        if (prev.close > center + 1.6 * std and last.close < prev.close and rv > 52
                and last.close > _vwap(small[-20:]) and minute is not None
                and confirm_1m(minute, -1, s.close_ts)):
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
    if deriv and deriv.valid(decision_ms if decision_ms is not None else s.close_ts) and deriv.oi_change_pct > 0:
        if deriv.funding_rate <= -0.0015:
            votes["funding_fade"] = 1
        if deriv.funding_rate >= 0.0015:
            votes["funding_fade"] = -1
    # Explain every individual vote, including abstentions, to the debug log.
    details = {
        "trend": f"15m EMA9/21 + MACD direction; ADX={a:.1f}; hourly={trend}",
        "reversion": f"5m RSI7={rv:.1f}, Bollinger/VWAP and completed 1m divergence/StochRSI",
        "breakout": f"20-bar extreme, OBV direction, 5m ADX={adx(small):.1f}, volume={relative_vol:.2f}x",
        "funding_fade": ("fresh funding and rising OI confirmed"
                         if deriv and deriv.valid(decision_ms if decision_ms is not None else s.close_ts)
                         else "missing or stale actual funding/OI observations"),
    }
    for name in ("trend", "reversion", "breakout", "funding_fade"):
        detail = ("LONG" if votes[name] == 1 else "SHORT") if name in votes else "ABSTAIN"
        log.debug("VOTE %s %s=%s reason=%s", symbol, name, detail, details[name])
    longs = sorted(k for k, direction in votes.items() if direction == 1)
    shorts = sorted(k for k, direction in votes.items() if direction == -1)
    score = min(10, 4 + max(len(longs), len(shorts)) +
                (1 if relative_vol >= 2 else 0) + (1 if a >= 30 else 0))
    # Two-vote consensus remains the default. Relaxed mode accepts a single
    # high-scoring, uncontested vote ONLY with the requested extra confirmation.
    agreed: list[str] = []
    side = ""
    for direction, group, other, macro_opposition in (
        ("LONG", longs, shorts, trend == -1),
        ("SHORT", shorts, longs, trend == 1),
    ):
        if macro_opposition or not group:
            continue
        # Preserve the original two-vote majority rule (e.g. 2:1).
        if len(group) >= 2 and len(group) > len(other) and score >= min_score:
            side, agreed = direction, group
            break
        if (not strict_votes and len(group) == 1 and not other and
                score >= max(min_score, min_strong_score) and
                (relative_vol >= 1.5 or a >= 25)):
            side, agreed = direction, group
            break
    if not side:
        log.debug("REJECT %s: votes=%s score=%d strict=%s macro=%d vol=%.2f adx=%.1f",
                  symbol, votes, score, strict_votes, trend, relative_vol, a)
        return None
    sign = 1 if side == "LONG" else -1
    stop = s.close - sign * 1.5 * volatility
    target = s.close + sign * 4.5 * volatility
    if stop <= 0 or target <= 0:
        log.warning("REJECT %s: invalid ATR protective levels", symbol)
        return None
    kind = "CONSENSUS" if len(agreed) >= 2 else "STRONG_SINGLE"
    log.info("ACCEPT %s %s %s votes=%s score=%d relative_vol=%.2f ADX=%.1f macro=%d",
             symbol, kind, side, agreed, score, relative_vol, a, trend)
    return Signal(symbol, side, s.ts, s.close, stop, target, score,
                  f"{kind} votes={','.join(agreed)}; macro={trend}; vol={relative_vol:.2f}x; "
                  f"ADX={a:.1f}", votes=tuple(agreed), atr_value=volatility,
                  features={"relative_volume": relative_vol, "adx_15m": a,
                            "adx_5m": adx(small), "rsi_5m": rv,
                            "signal_range_atr": (s.high - s.low) / volatility,
                            "signal_body_atr": abs(s.close - s.open) / volatility,
                            "ema9_distance_atr": abs(s.close - ema(p, 9)) / volatility,
                            "macro_direction": float(trend)})
