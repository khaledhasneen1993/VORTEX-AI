"""Opt-in entry hypothesis for historical research; production defaults unchanged."""
from dataclasses import replace
from math import isfinite, sqrt
from .models import Signal
from .exits import ExitStep
from .models import Position
from .indicators import adx, atr, ema, rsi
from .reversal import confirm as confirm_1m


def filter_signal(signal: Signal | None, policy: str) -> Signal | None:
    if policy not in {'baseline', 'extension-cap', 'cost-floor', 'invert-direction'}:
        raise ValueError('Unknown research entry policy')
    if signal is None or policy == 'baseline':
        return signal
    if policy == 'invert-direction':
        sign = 1 if signal.side == 'LONG' else -1
        risk = abs(signal.entry - signal.stop)
        reward = abs(signal.target - signal.entry)
        opposite = -sign
        return replace(
            signal,
            side='LONG' if opposite == 1 else 'SHORT',
            stop=signal.entry - opposite * risk,
            target=signal.entry + opposite * reward,
            reason=signal.reason + '; CONTRARIAN_RESEARCH_DIRECTION_INVERTED',
            votes=tuple(f'contrarian:{vote}' for vote in signal.votes),
            features={**signal.features, 'source_direction': float(sign)},
        )
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


def fixed_r_levels(position: Position, low: float, high: float, opening: float,
                   target_r: float) -> list[ExitStep]:
    """Research-only full-size fixed target; stop wins an ambiguous minute."""
    if min(low, high, opening) <= 0 or low > high or position.qty <= 0:
        raise ValueError('Invalid fixed-exit inputs')
    sign = 1 if position.side == 'LONG' else -1
    if low <= position.stop if sign == 1 else high >= position.stop:
        price = min(opening, position.stop) if sign == 1 else max(opening, position.stop)
        return [ExitStep(position.qty, price, 'stop', True)]
    target = position.entry + sign * position.initial_risk * target_r
    if high >= target if sign == 1 else low <= target:
        return [ExitStep(position.qty, target, f'target_{target_r:g}r', True)]
    return []


def fixed_3r_levels(position: Position, low: float, high: float, opening: float) -> list[ExitStep]:
    return fixed_r_levels(position, low, high, opening, 3.0)


def trend_pullback(symbol, bars, higher, min_score, *, macro=None, **_options) -> Signal | None:
    """Research: trend-aligned decision-timeframe EMA9 reclaim."""
    if len(bars) < 70 or len(higher) < 70 or macro is None or len(macro) < 210:
        return None
    current, previous = bars[-1], bars[-2]
    if higher[-1].close_ts > current.close_ts or macro[-1].close_ts > current.close_ts:
        return None
    closes = [bar.close for bar in bars]
    higher_closes = [bar.close for bar in higher]
    macro_closes = [bar.close for bar in macro]
    volatility = atr(bars)
    if volatility <= 0 or not 0.0008 <= volatility / current.close <= 0.045:
        return None
    average_volume = sum(bar.volume for bar in bars[-21:-1]) / 20
    if average_volume <= 0 or current.volume / average_volume < 0.8:
        return None
    macro_direction = (1 if ema(macro_closes, 50) > ema(macro_closes, 200)
                       else -1 if ema(macro_closes, 50) < ema(macro_closes, 200) else 0)
    higher_direction = (1 if ema(higher_closes, 9) > ema(higher_closes, 21)
                        else -1 if ema(higher_closes, 9) < ema(higher_closes, 21) else 0)
    if macro_direction == 0 or macro_direction != higher_direction or adx(higher) < 25:
        return None
    previous_ema9 = ema(closes[:-1], 9)
    current_ema9 = ema(closes, 9)
    current_ema21 = ema(closes, 21)
    momentum = rsi(closes, 14)
    if macro_direction == 1:
        accepted = (previous.close <= previous_ema9 and current.close > current_ema9
                    and current.close > current.open and current_ema9 > current_ema21
                    and 50 <= momentum <= 70)
    else:
        accepted = (previous.close >= previous_ema9 and current.close < current_ema9
                    and current.close < current.open and current_ema9 < current_ema21
                    and 30 <= momentum <= 50)
    if not accepted:
        return None
    stop = current.close - macro_direction * 1.5 * volatility
    target = current.close + macro_direction * 4.5 * volatility
    return Signal(
        symbol, 'LONG' if macro_direction == 1 else 'SHORT', current.ts,
        current.close, stop, target, max(min_score, 7),
        'TREND_PULLBACK EMA9 reclaim; higher/macro aligned; completed candles',
        features={'relative_volume': current.volume / average_volume,
                  'adx_higher': adx(higher), 'rsi_decision': momentum,
                  'ema9_distance_atr': abs(current.close-current_ema9)/volatility,
                  'macro_direction': float(macro_direction)},
        votes=('trend_pullback',), atr_value=volatility,
    )


def range_reversion(symbol, bars, higher, min_score, *, minute=None,
                    require_minute_confirmation=True, **_options) -> Signal | None:
    """E011: frozen-band reclaim in a low-ADX range, confirmed on completed 1m."""
    if len(bars) < 70 or len(higher) < 30 or minute is None or len(minute) < 85:
        return None
    current, setup = bars[-1], bars[-2]
    if higher[-1].close_ts > current.close_ts or minute[-1].close_ts > current.close_ts:
        return None
    reference = [bar.close for bar in bars[-22:-2]]
    if len(reference) != 20:
        return None
    mean = sum(reference) / len(reference)
    deviation = sqrt(sum((price - mean) ** 2 for price in reference) / len(reference))
    if deviation <= 0:
        return None
    lower, upper = mean - 2 * deviation, mean + 2 * deviation
    volatility = atr(bars)
    if volatility <= 0 or not 0.0008 <= volatility / current.close <= 0.045:
        return None
    adx_small, adx_higher = adx(bars), adx(higher)
    if adx_small >= 20 or adx_higher >= 20:
        return None
    average_volume = sum(bar.volume for bar in bars[-21:-1]) / 20
    if average_volume <= 0:
        return None
    relative_volume = current.volume / average_volume
    if not 0.8 <= relative_volume <= 1.5:
        return None
    momentum = rsi([bar.close for bar in bars], 7)
    if setup.close < lower and current.close >= lower and current.close > current.open:
        direction = 1
        accepted = momentum <= 40
    elif setup.close > upper and current.close <= upper and current.close < current.open:
        direction = -1
        accepted = momentum >= 60
    else:
        return None
    if not accepted or (require_minute_confirmation and
                        not confirm_1m(minute, direction, current.close_ts)):
        return None
    stop = current.close - direction * 1.5 * volatility
    target = current.close + direction * 3.0 * volatility
    return Signal(
        symbol, 'LONG' if direction == 1 else 'SHORT', current.ts,
        current.close, stop, target, max(min_score, 7),
        ('RANGE_REVERSION frozen 20x2SD band reclaim; low ADX; '
         + ('completed 1m confirmation' if require_minute_confirmation
            else 'E012 minute-confirmation ablation')),
        features={'band_mean': mean, 'band_lower': lower, 'band_upper': upper,
                  'band_setup_close': setup.close, 'relative_volume': relative_volume,
                  'adx_5m': adx_small, 'adx_15m': adx_higher,
                  'rsi7_decision': momentum,
                  'minute_confirmation_required': float(require_minute_confirmation)},
        votes=('range_reversion',), atr_value=volatility,
    )
