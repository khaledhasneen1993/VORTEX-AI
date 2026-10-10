"""Small completed-candle voters; no stand-alone execution or fitted model."""

from math import isfinite


def volume_spike(bars, atr_value, relative_volume, adx5, adx15, policy):
    if not policy.volume_spike_enabled:
        return 0, "VOLUME_SPIKE_DISABLED"
    if len(bars) < policy.breakout_lookback + 1 or not isfinite(atr_value) or atr_value <= 0:
        return 0, "VOLUME_SPIKE_ABSTAIN_HISTORY"
    if adx15 < policy.trend_adx or adx5 < policy.breakout_adx:
        return 0, "VOLUME_SPIKE_ABSTAIN_REGIME"
    current, prior = bars[-1], bars[-policy.breakout_lookback - 1 : -1]
    span = current.high - current.low
    if span <= 0 or relative_volume < policy.volume_spike_min_volume:
        return 0, "VOLUME_SPIKE_ABSTAIN_VOLUME"
    for sign, boundary in ((1, max(b.high for b in prior)), (-1, min(b.low for b in prior))):
        location = (
            (current.close - current.low) / span if sign == 1 else (current.high - current.close) / span
        )
        if (
            (current.close - boundary) * sign > 0
            and (current.close - current.open) * sign / atr_value >= policy.volume_spike_min_body_atr
            and location >= policy.volume_spike_close_fraction
        ):
            return sign, "VOLUME_SPIKE_UP" if sign == 1 else "VOLUME_SPIKE_DOWN"
    return 0, "VOLUME_SPIKE_ABSTAIN_NO_CLOSE_BREAKOUT"


def liquidity_sweep(bars, atr_value, relative_volume, policy):
    """Wick beyond a prior swing plus close reclaim; no liquidation claims."""
    if not policy.liquidity_sweep_enabled:
        return 0, "SWEEP_DISABLED"
    if (
        len(bars) < policy.sweep_lookback + 1
        or not isfinite(atr_value)
        or atr_value <= 0
        or not isfinite(relative_volume)
        or relative_volume < policy.sweep_min_volume
    ):
        return 0, "SWEEP_ABSTAIN_HISTORY_OR_VOLUME"
    current, prior = bars[-1], bars[-policy.sweep_lookback - 1 : -1]
    low, high = min(b.low for b in prior), max(b.high for b in prior)
    extension = policy.sweep_min_atr * atr_value
    below, above = current.low < low - extension, current.high > high + extension
    if below and above:
        return 0, "SWEEP_ABSTAIN_BOTH_SIDES"
    span = current.high - current.low
    if span <= 0:
        return 0, "SWEEP_ABSTAIN_INVALID_RANGE"
    if (
        below
        and current.close > low + extension
        and current.close > current.open
        and (min(current.open, current.close) - current.low) / span >= policy.sweep_min_wick_fraction
    ):
        return 1, "SWEEP_LOW_RECLAIM"
    if (
        above
        and current.close < high - extension
        and current.close < current.open
        and (current.high - max(current.open, current.close)) / span >= policy.sweep_min_wick_fraction
    ):
        return -1, "SWEEP_HIGH_RECLAIM"
    return 0, "SWEEP_ABSTAIN_NO_RECLAIM"
