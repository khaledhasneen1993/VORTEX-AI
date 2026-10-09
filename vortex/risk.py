"""Independent risk gate and exchange-filter-aware sizing."""
from __future__ import annotations
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from .config import Settings
from .models import Signal


@dataclass(frozen=True)
class Filters:
    step: float
    min_qty: float
    min_notional: float
    tick: float

    @classmethod
    def from_exchange(cls, info: dict) -> "Filters":
        f = {x["filterType"]: x for x in info["filters"]}
        lot = f.get("MARKET_LOT_SIZE", {})
        if float(lot.get("stepSize", "0")) <= 0:
            lot = f["LOT_SIZE"]
        return cls(float(lot["stepSize"]), float(lot["minQty"]),
                   float(f.get("MIN_NOTIONAL", {}).get("notional", 5)), float(f["PRICE_FILTER"]["tickSize"]))


def floor_step(value: float, step: float) -> float:
    if value <= 0 or step <= 0:
        return 0.0
    d = Decimal(str(step))
    return float((Decimal(str(value)) / d).to_integral_value(rounding=ROUND_DOWN) * d)


def size_trade(signal: Signal, equity: float, cfg: Settings, filt: Filters,
               committed_margin: float = 0,
               max_new_margin: float | None = None, *,
               committed_risk: float = 0, risk_fraction_override: float | None = None) -> tuple[float, float] | None:
    stop_gap = abs(signal.entry - signal.stop)
    if equity <= 0 or stop_gap <= 0 or not math.isfinite(stop_gap):
        return None
    # Fee and slippage across entry AND exit are charged against the risk budget.
    # Charge entry and conservative STOP-side exit costs. SHORT stops may be
    # above entry, so using entry-only fees would understate planned risk.
    per_side_cost = cfg.fee_rate + cfg.slippage_bps / 10000
    worst_exit_basis = max(signal.entry, signal.stop)
    cost_per_unit = per_side_cost * (signal.entry + worst_exit_basis)
    from .phase2 import risk_fraction
    fraction = risk_fraction(signal,cfg)
    if risk_fraction_override is not None:
        if not math.isfinite(risk_fraction_override) or risk_fraction_override <= 0:
            return None
        fraction = min(fraction,risk_fraction_override)
    budget = equity*fraction
    if cfg.phase2.enabled:
        if not math.isfinite(committed_risk) or committed_risk < 0:
            return None
        budget = min(budget,max(0.,equity*cfg.phase2.portfolio_stop_risk-committed_risk))
    if budget <= 0:
        return None
    max_by_risk = budget / (stop_gap + cost_per_unit)
    # Config accepts 1..10 but this bot's trading policy never exceeds 5x.
    leverage = min(cfg.max_leverage, 5)
    max_by_margin = max(0.0, equity * cfg.max_margin_fraction - committed_margin)
    if cfg.phase2.enabled:
        max_by_margin = min(max_by_margin,equity*cfg.phase2.entry_margin_fraction)
    if max_new_margin is not None:
        if not math.isfinite(max_new_margin) or max_new_margin <= 0:
            return None
        max_by_margin = min(max_by_margin, max_new_margin)
    max_by_leverage = max_by_margin * leverage / signal.entry
    qty = floor_step(min(max_by_risk, max_by_leverage), filt.step)
    if qty < filt.min_qty or qty * signal.entry < filt.min_notional:
        return None  # NEVER round upward across allowed risk to meet min notional
    margin = qty * signal.entry / leverage
    return qty, margin


class RiskGate:
    def __init__(self, cfg: Settings, start_equity: float):
        self.cfg = cfg
        self.date = datetime.now(timezone.utc).date().isoformat()
        self.day_start_equity = start_equity
        self.consecutive_losses = 0
        self.blocked = False

    def can_open(self, equity: float, count: int) -> tuple[bool, str]:
        if not math.isfinite(equity):
            return False, "invalid equity"
        if self.blocked:
            return False, "portfolio daily loss halt: operator reset required"
        threshold = self.day_start_equity * (1 - self.cfg.max_daily_loss)
        if equity <= 0 or equity <= threshold or math.isclose(equity,threshold,rel_tol=1e-12,abs_tol=1e-9):
            self.blocked = True
            return False, "daily loss circuit breaker"
        if count >= self.cfg.max_positions:
            return False, "max positions"
        return True, "ok"

    def closed(self, pnl: float) -> None:
        # Diagnostic count only; losing streaks do NOT trigger a portfolio halt.
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

    def new_day(self, today: str, equity: float) -> None:
        if today != self.date:
            self.date = today
            self.day_start_equity = equity
            # A halt remains latched until the process is explicitly restarted.


def trailing_stop(entry: float, peak: float, initial_risk: float,
                  atr_value: float, multiplier: float, side: str) -> float:
    """After +2R, guarantee at least +1R plus a tiny ATR buffer.

    ATR measures latest *completed* candles. Stops may tighten, never widen.
    """
    if side not in {"LONG", "SHORT"} or min(entry, initial_risk, atr_value, multiplier) <= 0:
        raise ValueError("Trailing requires positive observed ATR, entry and risk")
    sign = 1 if side == "LONG" else -1
    if (peak - entry) * sign < 2 * initial_risk:
        return entry
    buffer = 0.02 * atr_value
    one_r = entry + sign * (initial_risk + buffer)
    atr_trail = peak - sign * (atr_value * multiplier)
    return max(one_r, atr_trail) if sign == 1 else min(one_r, atr_trail)
