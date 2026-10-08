"""Staged paper position management shared with deterministic OHLC evaluation.

Stages: 25% at +1R, 25% at +1.5R, remaining at 2.5-3R target.
After TP1, stop moves to entry (never backwards). After TP2, trail
1 initial risk behind best observed bid/ask. No averaging or martingale.
"""
from __future__ import annotations
from dataclasses import dataclass
from .models import Position
from .risk import floor_step


@dataclass(frozen=True)
class ExitStep:
    qty: float
    price: float
    reason: str
    final: bool


def _risk(p: Position) -> float:
    return p.initial_risk or abs(p.entry - p.stop)


def _initial_qty(p: Position) -> float:
    return p.initial_qty or p.qty


def _sign(p: Position) -> int:
    return 1 if p.side == "LONG" else -1


def _move_stop(p: Position, price: float) -> None:
    if not p.tp1_done:
        return
    sign = _sign(p)
    if p.peak == 0:
        p.peak = p.entry
    favorable = (p.peak - p.entry) * sign
    protected = p.entry
    if p.tp2_done and favorable >= 2 * _risk(p):
        protected = p.peak - sign * _risk(p)
    p.stop = max(p.stop, protected) if sign == 1 else min(p.stop, protected)


def _fraction(p: Position) -> float:
    # Never round a minimum-lot partial UP; skip a stage if it cannot be placed.
    if p.step <= 0:
        return 0.
    quantity = floor_step(_initial_qty(p) * .25, p.step)
    if quantity <= 0 or quantity >= p.qty:
        return 0.
    return quantity


def decide_tick(p: Position, price: float) -> ExitStep | None:
    if not (p.qty > 0 and price > 0):
        raise ValueError("Bad position or executable quote")
    sign = _sign(p)
    if p.peak <= 0:
        p.peak = p.entry
    p.peak = max(p.peak, price) if sign == 1 else min(p.peak, price)
    # Apply EXISTING stop first, before changing trailing level.
    if (price - p.stop) * sign <= 0:
        return ExitStep(p.qty, price, "stop", True)
    if (price - p.target) * sign >= 0:
        return ExitStep(p.qty, price, "target", True)
    favorable = (price - p.entry) * sign
    risk = _risk(p)
    if risk <= 0:
        raise ValueError("Missing original risk distance")
    if not p.tp1_done and favorable >= risk:
        qty = _fraction(p)
        if qty:
            p.tp1_done = True
            _move_stop(p, price)
            return ExitStep(qty, price, "tp1", False)
        p.tp1_done = True
    if not p.tp2_done and favorable >= 1.5 * risk and p.tp1_done:
        qty = _fraction(p)
        if qty:
            p.tp2_done = True
            _move_stop(p, price)
            return ExitStep(qty, price, "tp2", False)
        p.tp2_done = True
    _move_stop(p, price)
    return None


def levels_for_bar(p: Position, low: float, high: float, opening: float) -> list[ExitStep]:
    """Stop always wins ambiguous OHLC high/low ordering.

    Staged target touches are filled at their threshold (not bar high),
    and trailing updates become active ONLY on the next completed bar.
    """
    if min(low, high, opening) <= 0 or low > high:
        raise ValueError("Invalid OHLC")
    sign = _sign(p)
    if (low - p.stop) * sign <= 0 if sign == 1 else (high - p.stop) * sign >= 0:
        raw = min(opening, p.stop) if sign == 1 else max(opening, p.stop)
        return [ExitStep(p.qty, raw, "stop", True)]
    risk = _risk(p)
    if risk <= 0:
        raise ValueError("Missing original risk")
    best = high if sign == 1 else low
    reach = (best - p.entry) * sign
    steps: list[ExitStep] = []
    remaining = p.qty
    if not p.tp1_done and reach >= risk:
        q = _fraction(p)
        if q:
            steps.append(ExitStep(q, p.entry + sign * risk, "tp1", False))
            remaining -= q
        p.tp1_done = True
    if not p.tp2_done and reach >= 1.5 * risk and p.tp1_done:
        q = floor_step(_initial_qty(p) * .25, p.step) if p.step > 0 else 0
        if 0 < q < remaining:
            steps.append(ExitStep(q, p.entry + sign * 1.5 * risk, "tp2", False))
            remaining -= q
        p.tp2_done = True
    if (best - p.target) * sign >= 0:
        steps.append(ExitStep(remaining, p.target, "target", True))
    # Do not modify p.qty here. The caller applies fills in order.
    p.peak = max(p.peak or p.entry, best) if sign == 1 else min(p.peak or p.entry, best)
    _move_stop(p, best)
    return steps
