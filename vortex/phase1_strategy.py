"""Phase 1: completed-candle consensus with actual taker volume, no lookahead."""

import logging
from datetime import datetime, timezone
from math import isfinite

from .indicators import adx, atr, ema, rsi
from .market_features import _macd_hist, _std, _vwap
from .models import Signal
from .orderflow import flow_direction
from .regime import classify
from .extra_voters import liquidity_sweep, volume_spike
from .reversal import confirm as confirm_1m

log = logging.getLogger("vortex.votes")


def session_allowed(policy, decision_ms):
    if not policy.session_filter:
        return True
    hour = datetime.fromtimestamp(decision_ms / 1000, timezone.utc).hour
    for name in policy.sessions.split(","):
        start, end = getattr(policy, name + "_start"), getattr(policy, name + "_end")
        if (start <= hour < end) if start < end else (hour >= start or hour < end):
            return True
    return False


def atr_percentile(bars, lookback):
    """Current Wilder ATR ranks against preceding ATRs; current is excluded."""
    if len(bars) < lookback + 15:
        return None
    # One chronological Wilder pass rather than recomputing every prefix.
    ranges = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(bars, bars[1:])
    ]
    value = sum(ranges[:14]) / 14
    series = [value]
    for tr in ranges[14:]:
        value = (13 * value + tr) / 14
        series.append(value)
    reference = series[-lookback - 1 : -1]
    return 100 * sum(x <= series[-1] for x in reference) / lookback


def cvd_ratio(bars, window):
    """Rolling taker-buy minus taker-sell BASE volume / total base volume."""
    if len(bars) < window:
        return None
    window_bars = bars[-window:]
    if any(
        b.taker_buy_volume is None
        or not isfinite(b.taker_buy_volume)
        or not 0 <= b.taker_buy_volume <= b.volume
        for b in window_bars
    ):
        return None
    total = sum(b.volume for b in window_bars)
    return sum(2 * b.taker_buy_volume - b.volume for b in window_bars) / total if total > 0 else None


def funding_direction(deriv, decision, policy):
    if deriv is None or not deriv.valid(decision):
        return 0
    if not 0 <= decision - deriv.observed_ms <= policy.funding_max_age_ms:
        return 0
    price, interval = deriv.price_change_pct, deriv.interval_ms
    if price is None or interval is None or not isfinite(price):
        return 0
    if not policy.funding_interval_min_ms <= interval <= policy.funding_interval_max_ms:
        return 0
    if deriv.oi_change_pct < policy.funding_oi_min_pct:
        return 0
    if deriv.funding_rate <= -policy.funding_extreme and price >= policy.funding_price_min_pct:
        return 1
    if deriv.funding_rate >= policy.funding_extreme and price <= -policy.funding_price_min_pct:
        return -1
    return 0


def reversion_direction(bars, minute, relative_volume):
    """Existing Bollinger/VWAP + completed minute reversal; caller gates regime."""
    closes = [b.close for b in bars]
    center, std = sum(closes[-20:]) / 20, _std(closes[-20:])
    rv = rsi(closes, 7)
    previous, current = bars[-2:]
    if std <= 0 or relative_volume < 0.8 or minute is None:
        return 0
    for sign in (1, -1):
        qualified = (
            (
                previous.close < center - 1.6 * std
                and current.close > previous.close
                and rv < 48
                and current.close < _vwap(bars[-20:])
            )
            if sign == 1
            else (
                previous.close > center + 1.6 * std
                and current.close < previous.close
                and rv > 52
                and current.close > _vwap(bars[-20:])
            )
        )
        if qualified and confirm_1m(minute, sign, current.close_ts):
            return sign
    return 0


def weighted_selection(votes, weights, macro, strong, policy, *, clear_single=False):
    """Primary strategy required; ties and opposing votes veto single-vote path."""
    totals = {d: sum(weights[k] for k, v in votes.items() if v == d) for d in (1, -1)}
    direction = 1 if totals[1] > totals[-1] else -1 if totals[-1] > totals[1] else 0
    approved = tuple(sorted(k for k, v in votes.items() if v == direction))
    primary_names = ("trend", "breakout") + (("volume_spike",) if policy.volume_spike_enabled else ())
    primary = any(k in approved for k in primary_names)
    normal_weight = policy.normal_weight if policy.strict_votes else min(policy.normal_weight, 3.0)
    normal = len(approved) >= policy.normal_votes and totals.get(direction, 0) >= normal_weight
    exceptional = (
        policy.strong_enabled
        and strong
        and not totals.get(-direction, 0)
        and totals.get(direction, 0) >= policy.strong_weight
    )
    single = (
        policy.strong_enabled
        and policy.allow_single_strong_vote
        and clear_single
        and len(approved) == 1
        and not any(v == -direction for v in votes.values())
        and totals.get(direction, 0) >= min(policy.strong_weight, 2.0)
    )
    return (
        (direction, approved, totals)
        if direction == macro and primary and (normal or exceptional or single)
        else (0, (), totals)
    )


def phase1_vote(symbol, small, higher, *, macro, deriv, decision_ms, minute, min_score, policy, flow=None):
    flow_code = "FLOW_DISABLED" if not policy.flow_enabled else "FLOW_ABSTAIN_NOT_EVALUATED"
    regime_code = "REGIME_DISABLED" if not policy.regime_enabled else "REGIME_ABSTAIN_NOT_EVALUATED"

    def reject(reason):
        log.debug(
            "REJECT %s code=%s phase1=%s flow=%s regime=%s",
            symbol,
            reason.upper(),
            reason,
            flow_code,
            regime_code,
        )
        return None

    if len(small) < max(70, policy.atr_lookback + 15) or len(higher) < 70 or not macro or len(macro) < 210:
        return reject("insufficient_history")
    decision = decision_ms if decision_ms is not None else small[-1].close_ts
    flow_sign, flow_code = flow_direction(flow, symbol, decision, policy)
    for bars, duration in ((small, 300000), (higher, 900000), (macro, 3600000)):
        # Reject future, missing, duplicate, unordered and stale completed histories.
        if any(
            b.close_ts != b.ts + duration - 1
            or b.close_ts > decision
            or not all(isfinite(v) for v in (b.open, b.high, b.low, b.close, b.volume))
            or min(b.open, b.high, b.low, b.close) <= 0
            or b.volume < 0
            or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            for b in bars
        ):
            return reject("malformed_or_future_history")
        if any(b.ts - a.ts != duration for a, b in zip(bars, bars[1:])):
            return reject("wrong_timeframe_or_history_gap")
        if decision - bars[-1].close_ts > duration + policy.max_signal_age_ms:
            return reject("stale_mtf_history")
    if decision - small[-1].close_ts > policy.max_signal_age_ms:
        return reject("stale_signal")
    if not session_allowed(policy, decision):
        return reject("disabled_utc_session")
    current = small[-1]
    a = atr(small)
    if not policy.atr_pct_min <= a / current.close <= policy.atr_pct_max:
        return reject("atr_absolute_limits")
    percentile = atr_percentile(small, policy.atr_lookback)
    adx5, adx15 = adx(small), adx(higher)
    regime = classify(small, percentile, adx5, adx15, policy)
    regime_code = regime.reason
    if policy.regime_enabled and regime.name in {"dead", "chop", "unknown"}:
        return reject("regime_" + regime.name)
    # A clear completed-price trend may bypass only the optional percentile floor.
    # Absolute ATR, freshness, sessions, MTF and execution protections remain.
    if (
        policy.volatility_filter
        and not (policy.regime_enabled and regime.name == "trend")
        and (percentile is None or percentile < policy.atr_percentile_min)
    ):
        return reject("atr_percentile")
    cvd = cvd_ratio(small, policy.cvd_window)
    closes, hc, mc = [b.close for b in small], [b.close for b in higher], [b.close for b in macro]

    def direction(fast, slow):
        return 1 if fast > slow else -1 if fast < slow else 0

    macro_dir = direction(ema(mc, 50), ema(mc, 200))
    mid_dir = direction(ema(hc, 9), ema(hc, 21))
    short_dir = direction(ema(closes, 9), ema(closes, 21))
    hist = _macd_hist(hc)
    if not macro_dir or not macro_dir == mid_dir == short_dir or hist * macro_dir <= 0:
        return reject("mtf_disagreement")
    if policy.flow_enabled and policy.flow_mode == "confirm":
        if flow_code == "FLOW_NEUTRAL":
            return reject("flow_neutral")
        if flow_sign and flow_sign != macro_dir:
            flow_code = "FLOW_OPPOSED"
            return reject("flow_opposed")
        if flow_sign == macro_dir:
            flow_code = "FLOW_ALIGNED"
    if policy.cvd_filter and (cvd is None or cvd * macro_dir < policy.cvd_min):
        return reject("missing_or_opposing_cvd")
    mean_vol = sum(b.volume for b in small[-21:-1]) / 20
    relvol = current.volume / mean_vol if mean_vol > 0 else 0
    votes = {}
    if policy.flow_enabled and policy.flow_mode == "voter" and flow_sign:
        votes["order_flow"] = flow_sign
    if adx15 >= policy.trend_adx and (not policy.regime_enabled or regime.name == "trend"):
        votes["trend"] = macro_dir
    prior = small[-policy.breakout_lookback - 1 : -1]
    if adx5 >= policy.breakout_adx and relvol >= policy.breakout_volume:
        if current.close > max(b.high for b in prior):
            votes["breakout"] = 1
        elif current.close < min(b.low for b in prior):
            votes["breakout"] = -1
    spike_sign, spike_code = volume_spike(small, a, relvol, adx5, adx15, policy)
    if spike_sign:
        # Same price/volume evidence: replace the breakout vote, never double it.
        votes.pop("breakout", None)
        votes["volume_spike"] = spike_sign
    sweep_sign, sweep_code = liquidity_sweep(small, a, relvol, policy)
    if sweep_sign:
        votes["liquidity_sweep"] = sweep_sign
    # Independent auxiliary vote alongside the primary strategies.
    if (
        adx5 < policy.range_adx
        and adx15 < policy.range_adx
        and policy.reversion_weight > 0
        and (not policy.regime_enabled or regime.name == "range")
    ):
        rv = reversion_direction(small, minute, relvol)
        if rv:
            votes["reversion"] = rv
    funding = funding_direction(deriv, decision, policy)
    if funding:
        votes["funding_fade"] = funding
    for name in (
        "trend",
        "breakout",
        "reversion",
        "funding_fade",
        "volume_spike",
        "liquidity_sweep",
        "order_flow",
    ):
        value = votes.get(name, 0)
        log.debug(
            "VOTE %s %s=%s reason=phase1 regime_adx=%.1f funding_freshness_and_price_required",
            symbol,
            name,
            "LONG" if value == 1 else "SHORT" if value == -1 else "ABSTAIN",
            adx15,
        )
    boost = policy.trend_boost if adx15 >= policy.trend_adx else 0
    weights = dict(
        trend=policy.trend_weight + boost,
        breakout=policy.breakout_weight + boost,
        reversion=policy.reversion_weight,
        funding_fade=policy.funding_weight,
        order_flow=policy.flow_weight,
        volume_spike=policy.volume_spike_weight + boost,
        liquidity_sweep=policy.sweep_weight,
    )
    strong = (
        adx15 >= policy.strong_adx
        and relvol >= policy.strong_volume
        and (current.close - current.open) * macro_dir / a >= policy.strong_body_atr
    )
    # Opt-in alternative: less ADX restriction, but MORE volume/body evidence.
    # Existing MTF, data freshness, volatility and CVD gates above still apply.
    clear_single = (
        policy.strong_enabled
        and policy.allow_single_strong_vote
        and adx15 >= max(policy.trend_adx, policy.strong_adx - 5.0)
        and relvol >= policy.strong_volume + 1.0
        and (current.close - current.open) * macro_dir / a >= policy.strong_body_atr + 0.2
    )
    sign, approved, totals = weighted_selection(
        votes, weights, macro_dir, strong, policy, clear_single=clear_single
    )
    log.debug(
        "PHASE1_VOTES %s votes=%s weights=%s totals=%s strong=%s atr_percentile=%.1f cvd=%s",
        symbol,
        votes,
        weights,
        totals,
        strong,
        percentile,
        cvd,
    )
    if not sign:
        return reject("weighted_consensus")
    score = min(
        10, 4 + len(approved) + int(relvol >= policy.breakout_volume) + int(adx15 >= policy.strong_adx)
    )
    if score < min_score:
        return reject("score")
    single_override = (
        clear_single and len(approved) == 1 and not (strong and totals[sign] >= policy.strong_weight)
    )
    if single_override and score < policy.min_strong_score:
        return reject("single_strong_score")
    strong = strong or single_override
    features = dict(
        relative_volume=relvol,
        adx_15m=adx15,
        adx_5m=adx5,
        atr_percentile=percentile,
        cvd_ratio=cvd if cvd is not None else 0,
        cvd_available=float(cvd is not None),
        weighted_long=totals[1],
        weighted_short=totals[-1],
        strong_signal=float(strong),
        macro_direction=float(macro_dir),
        rsi_5m=rsi(closes, 7),
        utc_session_hour=float(datetime.fromtimestamp(decision / 1000, timezone.utc).hour),
        funding_observed=float(deriv is not None and deriv.valid(decision)),
        funding_rate=deriv.funding_rate if deriv and deriv.valid(decision) else 0,
        oi_change_pct=deriv.oi_change_pct if deriv and deriv.valid(decision) else 0,
        signal_range_atr=(current.high - current.low) / a,
        signal_body_atr=abs(current.close - current.open) / a,
        ema9_distance_atr=abs(current.close - ema(closes, 9)) / a,
    )
    if policy.flow_enabled:
        valid_flow = flow_code in {"FLOW_BUY", "FLOW_SELL", "FLOW_ALIGNED", "FLOW_NEUTRAL"}
        features["flow_available"] = float(valid_flow)
        if valid_flow:
            features.update(
                flow_cvd_base=flow.cvd_base,
                flow_base_imbalance=flow.base_imbalance,
                flow_aggression=flow.aggression,
                flow_trade_count=float(flow.trade_count),
                flow_end_ms=float(flow.end_ms),
                flow_latest_ms=float(flow.latest_ms),
            )
    if policy.regime_enabled:
        features.update(
            regime_id=float({"trend": 1, "range": 2}[regime.name]),
            regime_bb_width=regime.bb_width,
            regime_efficiency=regime.efficiency,
        )
    reason = "PHASE1 " + ("STRONG" if strong else "NORMAL") + " votes=" + ",".join(approved)
    reason += " flow=" + flow_code + " regime=" + regime_code
    if policy.volume_spike_enabled:
        reason += " spike=" + spike_code
    if policy.liquidity_sweep_enabled:
        reason += " sweep=" + sweep_code
    log.info(
        "ACCEPT %s code=SIGNAL_ACCEPTED %s %s score=%d",
        symbol,
        reason,
        "LONG" if sign == 1 else "SHORT",
        score,
    )
    return Signal(
        symbol,
        "LONG" if sign == 1 else "SHORT",
        current.ts,
        current.close,
        current.close - sign * 1.5 * a,
        current.close + sign * 4.5 * a,
        score,
        reason,
        features,
        approved,
        a,
    )
