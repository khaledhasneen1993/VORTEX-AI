"""Explicit PAPER-only hypothesis; not a validated trading improvement."""

import os
from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class PaperExperiment:
    enabled: bool = False
    capture_enabled: bool = True
    average_enabled: bool = True
    profit_margin: float = 0.04
    stop_price: float = 0.10
    account_loss: float = 0.25
    average_trigger: float = 0.05
    average_fraction: float = 0.50

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool):
                continue
            if not isfinite(value) or value <= 0:
                raise ValueError("Invalid PAPER_EXP_" + f.name.upper())
        if not 0.03 <= self.profit_margin <= 0.05:
            raise ValueError("PAPER_EXP_PROFIT_MARGIN must be 0.03..0.05")
        if not 0 < self.average_trigger < self.stop_price <= 0.10:
            raise ValueError("Average trigger must precede the price stop (at most 10%)")
        if not 0 < self.average_fraction <= 0.50 or not 0 < self.account_loss <= 0.25:
            raise ValueError("Averaging/account loss bounds exceeded")

    @classmethod
    def from_env(cls):
        defaults, values = cls(), {}
        for f in fields(cls):
            raw = os.getenv("PAPER_EXP_" + f.name.upper())
            value = getattr(defaults, f.name)
            if raw is not None:
                if isinstance(value, bool):
                    if raw.strip().lower() not in {"true", "false"}:
                        raise ValueError("Invalid PAPER_EXP boolean")
                    value = raw.strip().lower() == "true"
                else:
                    value = float(raw)
            values[f.name] = value
        return cls(**values)


def net_margin_target(p, fee_rate, slip, policy):
    """Raw executable price yielding requested net PnL / total posted margin.

    Margin already incorporates leverage. Do not multiply returns by leverage
    again. Entry fees include the one optional add; funding is not simulated.
    """
    sign = 1 if p.side == "LONG" else -1
    cost = p.entry_fee + policy.profit_margin * p.margin - p.accumulated_net
    fill = (sign * p.entry + cost / p.qty) / (sign - fee_rate)
    return fill / (1 - sign * slip)


def average_plan(p, price, now_ms, cfg, filters, capital, committed_margin, portfolio_risk):
    """One adverse add, never widen the immutable original stop or risk caps."""
    from .models import Signal
    from .phase2 import stop_exposure
    from .risk import floor_step, size_trade

    policy = cfg.experiment
    sign = 1 if p.side == "LONG" else -1
    if (
        not policy.enabled
        or not policy.average_enabled
        or p.average_count
        or now_ms - p.opened_ts < 60000
        or (price - p.anchor_entry) * sign > -policy.average_trigger * p.anchor_entry
        or (price - p.stop) * sign <= 0
        or capital <= 0
    ):
        return None
    budget = min(capital * cfg.phase2.pyramid_risk_fraction, p.trade_risk_cap - stop_exposure(p, cfg))
    if budget <= 0:
        return None
    signal = Signal(
        p.symbol,
        p.side,
        now_ms,
        price,
        p.stop,
        p.target,
        10,
        "adverse_average",
        {"strong_signal": float(p.features.get("strong_signal", 0))},
    )
    sized = size_trade(
        signal,
        capital,
        cfg,
        filters,
        committed_margin,
        committed_risk=portfolio_risk,
        risk_fraction_override=budget / capital,
    )
    if sized is None:
        return None
    qty = floor_step(min(sized[0], p.initial_qty * policy.average_fraction), filters.step)
    if qty < filters.min_qty or price * qty < filters.min_notional:
        return None
    return qty, qty * price / min(cfg.max_leverage, 5), qty * price * cfg.fee_rate
