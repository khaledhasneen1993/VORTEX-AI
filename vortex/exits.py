"""Paper/OHLC staged exits: 25% at +1R, 25% at +1.5R, ATR trailing.

The historical engine checks the EXISTING stop before considering this bar's
range. Newly tightened stops apply only to subsequent completed bars.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, isclose
from .models import Position
from .operations import OperationsPolicy
from .risk import floor_step, trailing_stop


@dataclass(frozen=True)
class ExitStep:
    qty: float
    price: float
    reason: str
    final: bool


def _risk(p: Position) -> float:
    return p.initial_risk or abs(p.entry - p.stop)


def _entry(p: Position) -> float:
    return p.anchor_entry or p.entry


def _sign(p: Position) -> int:
    return 1 if p.side == "LONG" else -1


def _atr(p: Position, latest: float | None) -> float:
    fallback = p.atr_value if p.atr_value > 0 else _risk(p) / 1.5
    a = latest if latest is not None else fallback
    if not isfinite(a) or a <= 0:
        raise ValueError("Missing real ATR for trailing")
    p.atr_value = a
    return a


def _move_stop(p: Position, current_atr: float | None = None, multiplier: float = 1.0, policy: OperationsPolicy = OperationsPolicy()) -> None:
    if not p.tp1_done and not (policy.enabled and ((p.peak - _entry(p)) * _sign(p) >= policy.break_even_r * _risk(p) or isclose((p.peak - _entry(p)) * _sign(p), policy.break_even_r * _risk(p), rel_tol=1e-12))):
        return
    sign = _sign(p)
    atr_value = _atr(p, current_atr)
    peak = p.peak or _entry(p)
    risk = _risk(p)
    protected = _entry(p)  # breakeven after TP1
    if p.tp2_done and (peak - _entry(p)) * sign >= 2 * risk:
        protected = trailing_stop(_entry(p), peak, risk, atr_value, multiplier, p.side)
    p.stop = max(p.stop, protected) if sign == 1 else min(p.stop, protected)


def _fraction(p: Position, fraction: float = .25) -> float:
    if p.step <= 0:
        return 0.0
    qty = floor_step((p.initial_qty or p.qty) * fraction, p.step)
    return qty if 0 < qty < p.qty else 0.0


def decide_tick(p: Position, price: float, *, atr_value: float | None = None,
                trailing_atr_mult: float = 1.0, policy: OperationsPolicy = OperationsPolicy(),
                now_ms: int | None = None) -> ExitStep | None:
    if not (p.qty > 0 and price > 0):
        raise ValueError("Bad position or executable quote")
    sign = _sign(p)
    if p.peak <= 0:
        p.peak = _entry(p)
    p.peak = max(p.peak, price) if sign == 1 else min(p.peak, price)
    # Existing stop executes BEFORE any new stop adjustment.
    if (price - p.stop) * sign <= 0:
        return ExitStep(p.qty, price, "stop", True)
    # A sudden tick past the terminal objective must close all remaining size,
    # not just a 25% stage and risk losing the target in the next quote.
    if (not policy.enabled or policy.terminal_target) and (price - p.target) * sign >= 0:
        return ExitStep(p.qty, price, "target", True)
    if policy.enabled and now_ms is not None and now_ms-p.opened_ts >= policy.stagnant_minutes*60000 and (p.peak-_entry(p))*sign < policy.stagnant_r*_risk(p):
        return ExitStep(p.qty, price, 'time_stagnation', True)
    favorable = (price - _entry(p)) * sign
    risk = _risk(p)
    if risk <= 0:
        raise ValueError("Missing original risk distance")
    if not p.tp1_done and favorable >= risk:
        qty = _fraction(p, policy.tp1_fraction if policy.enabled else .25)
        p.tp1_done = True
        _move_stop(p, atr_value, trailing_atr_mult, policy)
        if qty:
            return ExitStep(qty, price, "tp1", False)
    if not p.tp2_done and favorable >= 1.5 * risk and p.tp1_done:
        qty = _fraction(p, policy.tp2_fraction if policy.enabled else .25)
        p.tp2_done = True
        _move_stop(p, atr_value, trailing_atr_mult, policy)
        if qty:
            return ExitStep(qty, price, "tp2", False)
    _move_stop(p, atr_value, trailing_atr_mult, policy)
    return None


def levels_for_bar(p: Position, low: float, high: float, opening: float,
                   *, atr_value: float | None = None,
                   trailing_atr_mult: float = 1.0, policy: OperationsPolicy = OperationsPolicy(),
                   now_ms: int | None = None) -> list[ExitStep]:
    """Stop wins ambiguous OHLC bars; partial fills occur at thresholds."""
    if min(low, high, opening) <= 0 or low > high:
        raise ValueError("Invalid OHLC")
    sign = _sign(p)
    if (low <= p.stop if sign == 1 else high >= p.stop):
        raw = min(opening, p.stop) if sign == 1 else max(opening, p.stop)
        return [ExitStep(p.qty, raw, "stop", True)]
    # Time decision uses only peaks already observed BEFORE this bar.
    if policy.enabled and now_ms is not None and now_ms-p.opened_ts >= policy.stagnant_minutes*60000 and ((p.peak or _entry(p))-_entry(p))*sign < policy.stagnant_r*_risk(p):
        return [ExitStep(p.qty, opening, 'time_stagnation', True)]
    risk = _risk(p)
    if risk <= 0:
        raise ValueError("Missing original risk")
    best = high if sign == 1 else low
    reach = (best - _entry(p)) * sign
    steps: list[ExitStep] = []
    remaining = p.qty
    if not p.tp1_done and reach >= risk:
        q = _fraction(p, policy.tp1_fraction if policy.enabled else .25)
        if q:
            steps.append(ExitStep(q, _entry(p) + sign * risk, "tp1", False))
            remaining -= q
        p.tp1_done = True
    if not p.tp2_done and reach >= 1.5 * risk and p.tp1_done:
        q = floor_step((p.initial_qty or p.qty) * (policy.tp2_fraction if policy.enabled else .25), p.step) if p.step > 0 else 0
        if 0 < q < remaining:
            steps.append(ExitStep(q, _entry(p) + sign * 1.5 * risk, "tp2", False))
            remaining -= q
        p.tp2_done = True
    if (not policy.enabled or policy.terminal_target) and (best - p.target) * sign >= 0:
        steps.append(ExitStep(remaining, p.target, "target", True))
    # Current bar's favorable extreme cannot retroactively trigger its new stop.
    p.peak = max(p.peak or _entry(p), best) if sign == 1 else min(p.peak or _entry(p), best)
    _move_stop(p, atr_value, trailing_atr_mult, policy)
    return steps
