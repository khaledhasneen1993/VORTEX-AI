"""Opt-in entry hypothesis for historical research; production defaults unchanged."""
from math import isfinite
from .models import Signal


def filter_signal(signal: Signal | None, policy: str) -> Signal | None:
    if policy not in {'baseline', 'extension-cap', 'cost-floor'}:
        raise ValueError('Unknown research entry policy')
    if signal is None or policy == 'baseline':
        return signal
    if policy == 'cost-floor':
        # E004 freezes normal configured costs; stress does NOT change entry selection.
        if not all(isfinite(v) and v > 0 for v in (signal.entry,signal.stop)):
            return None
        modeled_cost = (signal.entry + max(signal.entry,signal.stop)) * (.0005 + 3 / 10000)
        return signal if abs(signal.entry-signal.stop) >= 3 * modeled_cost else None
    # Frozen E002 hypothesis: avoid chasing a close beyond two ATR from EMA9.
    # Do not tune the threshold using the same validation period.
    distance = signal.features.get('ema9_distance_atr')
    if distance is None or not isfinite(distance) or distance > 2.0:
        return None
    return signal


def confirmed_breakout(analyze, symbol, bars, higher, min_score, **options):
    """E003: wait one completed 5m continuation candle, then enter next open.

    Re-evaluate the previous candidate using histories cut at its own close.
    Current confirmation can only act AFTER it closes; no lookahead.
    """
    from dataclasses import replace
    if len(bars) < 71:
        return None
    previous, current = bars[-2:]
    if current.ts - previous.ts != 300000:
        return None
    limit = previous.close_ts
    prior_options = dict(options)
    for key in ('macro', 'minute'):
        if prior_options.get(key) is not None:
            prior_options[key] = [c for c in prior_options[key] if c.close_ts <= limit]
    signal = analyze(symbol, bars[:-1], [c for c in higher if c.close_ts <= limit],
                     min_score, **prior_options)
    if signal is None or 'breakout' not in signal.votes:
        return None
    if signal.side == 'LONG':
        confirmed = current.close >= previous.close and current.close > current.open
        sign = 1
    else:
        confirmed = current.close <= previous.close and current.close < current.open
        sign = -1
    if not confirmed:
        return None
    # A freshly completed hourly regime may have flipped since the candidate.
    macro = options.get('macro')
    if macro:
        from .indicators import ema
        closes = [c.close for c in macro]
        direction = 1 if ema(closes,50) > ema(closes,200) else -1
        if direction != sign:
            return None
    gap, objective = abs(signal.entry-signal.stop), abs(signal.target-signal.entry)
    return replace(signal, ts=current.ts, entry=current.close,
                   stop=current.close-sign*gap, target=current.close+sign*objective,
                   features={**signal.features,'confirmation_delay_bars':1.0},
                   reason=signal.reason+'; completed continuation confirmation')
