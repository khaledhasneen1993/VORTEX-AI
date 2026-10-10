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
