"""Opt-in entry hypothesis for historical research; production defaults unchanged."""
from math import isfinite
from .models import Signal


def filter_signal(signal: Signal | None, policy: str) -> Signal | None:
    if policy not in {'baseline', 'extension-cap'}:
        raise ValueError('Unknown research entry policy')
    if signal is None or policy == 'baseline':
        return signal
    # Frozen E002 hypothesis: avoid chasing a close beyond two ATR from EMA9.
    # Do not tune the threshold using the same validation period.
    distance = signal.features.get('ema9_distance_atr')
    if distance is None or not isfinite(distance) or distance > 2.0:
        return None
    return signal
