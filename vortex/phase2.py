"""Aggressive PAPER research risk policy and deterministic account controls.

No exchange I/O. All additions remain bounded by cash, margin and stop risk.
"""

import os
from dataclasses import dataclass, fields
from itertools import pairwise
from math import isfinite, sqrt


@dataclass(frozen=True)
class RiskPolicy:
    enabled: bool = True
    normal_min: float = 0.08
    normal_max: float = 0.10
    strong_min: float = 0.12
    strong_max: float = 0.15
    portfolio_stop_risk: float = 0.30
    entry_margin_fraction: float = 0.0625
    compounding_fraction: float = 0.50
    pyramiding: bool = True
    pyramid_trigger_r: float = 2.0
    pyramid_spacing_r: float = 0.5
    pyramid_max_adds: int = 1
    pyramid_size_fraction: float = 0.25
    pyramid_risk_fraction: float = 0.02
    pyramid_min_interval_ms: int = 300000
    correlation_filter: bool = True
    correlation_lookback: int = 60
    correlation_max: float = 0.80

    def __post_init__(self):
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and (not isfinite(v) or v < 0):
                raise ValueError("Invalid PHASE2_" + f.name.upper())
        if not 0.08 <= self.normal_min <= self.normal_max <= 0.10:
            raise ValueError("Normal risk must be 8–10%")
        if not 0.12 <= self.strong_min <= self.strong_max <= 0.15:
            raise ValueError("Strong risk must be 12–15%")
        if not 0 < self.entry_margin_fraction <= 0.25:
            raise ValueError("Invalid per-entry margin cap")
        if not 0 < self.portfolio_stop_risk <= 0.60 or not 0 <= self.compounding_fraction <= 1:
            raise ValueError("Invalid portfolio risk / compounding")
        if not 1.5 <= self.pyramid_trigger_r <= 3 or not 1 <= self.pyramid_max_adds <= 3:
            raise ValueError("Invalid pyramid trigger / limit")
        if not 0 < self.pyramid_size_fraction <= 0.5 or not 0 < self.pyramid_risk_fraction <= 0.05:
            raise ValueError("Invalid pyramid size / risk")
        if self.pyramid_spacing_r <= 0 or self.pyramid_min_interval_ms < 60000:
            raise ValueError("Pyramid spacing / interval invalid")
        if not 20 <= self.correlation_lookback <= 200 or not 0 < self.correlation_max < 1:
            raise ValueError("Invalid correlation bounds")

    @classmethod
    def from_env(cls):
        defaults, values = cls(), {}
        for f in fields(cls):
            raw = os.getenv("PHASE2_" + f.name.upper())
            if raw is None:
                continue
            v = getattr(defaults, f.name)
            if isinstance(v, bool):
                if raw.strip().lower() not in {"true", "false"}:
                    raise ValueError("Invalid PHASE2 boolean")
                values[f.name] = raw.strip().lower() == "true"
            else:
                values[f.name] = type(v)(raw.strip())
        return cls(**values)


def risk_fraction(signal, cfg):
    """RISK_PER_TRADE is the strong baseline; absolute policy bands cap budgets."""
    if not cfg.phase2.enabled:
        return cfg.risk_per_trade
    if not isfinite(signal.score) or signal.score < cfg.min_score:
        return 0.0
    p = cfg.phase2
    strong = signal.features.get("strong_signal") == 1 and signal.score >= cfg.min_strong_score
    if strong:
        strength = min(
            1.0, max(0.0, (signal.score - cfg.min_strong_score) / max(1, 10 - cfg.min_strong_score))
        )
        value = p.strong_min + strength * (p.strong_max - p.strong_min)
    else:
        strength = min(1.0, max(0.0, (signal.score - cfg.min_score) / max(1, 10 - cfg.min_score)))
        value = p.normal_min + strength * (p.normal_max - p.normal_min)
    if strong:
        return min(p.strong_max, cfg.risk_per_trade * value / p.strong_min)
    return min(cfg.risk_per_trade, value)


class ProfitReserve:
    """Reserve only realized AFTER-COST positive stages; never compound marks.

    The reserve is bookkeeping inside virtual wallet, not a withdrawal. Losses
    never release it automatically. A zero tradable balance blocks new risk.
    """

    def __init__(self, cfg, reserved=0.0):
        self.cfg = cfg
        if not isfinite(reserved) or reserved < 0:
            raise ValueError("Invalid saved profit reserve")
        self.reserved = reserved

    def record(self, stage_net):
        if not isfinite(stage_net):
            raise ValueError("Invalid realized PnL")
        if self.cfg.phase2.enabled:
            self.reserved += max(0.0, stage_net) * (1 - self.cfg.phase2.compounding_fraction)

    def capital(self, wallet, marked_equity):
        # Mark-to-market losses reduce buying power; unrealized wins do not raise it.
        return (
            max(0.0, min(wallet, marked_equity) - self.reserved) if self.cfg.phase2.enabled else marked_equity
        )


def correlation_gate(signal, positions, histories, decision_ms, policy):
    """Pearson of aligned completed 5m returns, adjusted for exposure direction."""
    if not policy.enabled or not policy.correlation_filter or not positions:
        return True, "correlation disabled / no other exposure"

    def closes(symbol):
        bars = histories.get(symbol, [])
        if (
            not bars
            or not 0 <= decision_ms - bars[-1].close_ts <= 390000
            or any(b.close_ts > decision_ms for b in bars)
        ):
            return None
        eligible = [b for b in bars if b.close_ts <= decision_ms]
        if len(eligible) < policy.correlation_lookback + 1:
            return None
        eligible = eligible[-policy.correlation_lookback - 1 :]
        if any(b.ts - a.ts != 300000 for a, b in pairwise(eligible)):
            return None
        if any(not isfinite(b.close) or b.close <= 0 or b.close_ts != b.ts + 299999 for b in eligible):
            return None
        return {b.ts: b.close for b in eligible}

    candidate = closes(signal.symbol)
    if candidate is None:
        return False, "missing/stale candidate correlation history"
    for symbol, p in positions.items():
        if symbol == signal.symbol:
            continue
        other = closes(symbol)
        if other is None or set(candidate) != set(other):
            return False, "missing/stale/unaligned correlation history: " + symbol
        stamps = sorted(candidate)
        x = [candidate[b] / candidate[a] - 1 for a, b in pairwise(stamps)]
        y = [other[b] / other[a] - 1 for a, b in pairwise(stamps)]
        mx, my = sum(x) / len(x), sum(y) / len(y)
        vx, vy = sum((v - mx) ** 2 for v in x), sum((v - my) ** 2 for v in y)
        if min(vx, vy) <= 1e-24:
            return False, "undefined correlation: " + symbol
        rho = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sqrt(vx * vy)
        exposure_rho = rho * (1 if signal.side == p.side else -1)
        if exposure_rho >= policy.correlation_max:
            return False, f"correlated exposure {symbol}: rho={rho:.4f}"
    return True, "correlation approved"


def stop_exposure(position, cfg):
    sign = 1 if position.side == "LONG" else -1
    from .operations import slippage_bps

    modeled = slippage_bps(
        cfg.slippage_bps, position.atr_value / position.entry, cfg.max_spread_bps, cfg.operations
    )
    cost = cfg.fee_rate + modeled / 10000
    return (
        max(0.0, (position.entry - position.stop) * sign) * position.qty
        + cost * max(position.entry, position.stop) * position.qty
    )


def initialize_position(p, signal, capital, cfg):
    if cfg.phase2.enabled:
        p.anchor_entry = p.entry
        p.risk_fraction = risk_fraction(signal, cfg)
        p.trade_risk_cap = capital * p.risk_fraction
        p.total_entry_qty = p.initial_qty


def pyramid_plan(
    p, price, decision_ms, cfg, filters, capital, committed_margin, portfolio_risk, observed_price=None
):
    """Observed prior close for OHLC, executable current quote for PAPER.

    Existing target/stop remain fixed. Combined trade must still be profitable
    at the unchanged stop INCLUDING allocated fees, realized stages and slippage.
    """
    from .models import Signal
    from .risk import floor_step, size_trade

    pol = cfg.phase2
    if not pol.enabled or not pol.pyramiding or p.trade_risk_cap <= 0:
        return None
    anchor = p.anchor_entry or p.entry
    sign = 1 if p.side == "LONG" else -1
    trigger = pol.pyramid_trigger_r + p.pyramid_count * pol.pyramid_spacing_r
    observed = price if observed_price is None else observed_price
    if (
        not all(
            isfinite(v)
            for v in (
                price,
                observed,
                capital,
                committed_margin,
                portfolio_risk,
                p.entry,
                p.stop,
                p.target,
                p.initial_risk,
                p.accumulated_net,
                p.entry_fee,
            )
        )
        or min(price, observed, p.entry, p.stop, p.target, p.initial_risk) <= 0
        or min(committed_margin, portfolio_risk) < 0
    ):
        return None
    if (
        p.pyramid_count >= pol.pyramid_max_adds
        or not p.tp2_done
        or decision_ms - max(p.opened_ts, p.last_pyramid_ms) < pol.pyramid_min_interval_ms
        or (observed - anchor) * sign < trigger * p.initial_risk
        or (price - anchor) * sign < trigger * p.initial_risk
        or (price - p.target) * sign >= 0
        or (price - p.stop) * sign <= 0
        or (price - p.entry) * sign <= 0
        or capital <= 0
    ):
        return None
    budget = min(capital * pol.pyramid_risk_fraction, p.trade_risk_cap)
    sig = Signal(p.symbol, p.side, decision_ms, price, p.stop, p.target, 10, "pyramid")
    sized = size_trade(
        sig,
        capital,
        cfg,
        filters,
        committed_margin,
        committed_risk=portfolio_risk,
        risk_fraction_override=budget / capital,
        max_new_margin=max(0.0, capital * pol.entry_margin_fraction - p.margin),
    )
    if sized is None:
        return None
    qty = floor_step(min(sized[0], p.initial_qty * pol.pyramid_size_fraction), filters.step)
    if qty < filters.min_qty or price * qty < filters.min_notional:
        return None
    remaining_budget = min(
        p.trade_risk_cap - stop_exposure(p, cfg), capital * pol.portfolio_stop_risk - portfolio_risk
    )
    per_unit = (price - p.stop) * sign + (cfg.fee_rate + cfg.slippage_bps / 10000) * (
        price + max(price, p.stop)
    )
    qty = floor_step(min(qty, max(0.0, remaining_budget) / per_unit), filters.step)
    if qty < filters.min_qty or price * qty < filters.min_notional:
        return None
    exit_price = p.stop * (1 - sign * cfg.slippage_bps / 10000)
    existing_net = (
        p.accumulated_net
        + (exit_price - p.entry) * sign * p.qty
        - p.entry_fee
        - exit_price * p.qty * cfg.fee_rate
    )
    added_net = (exit_price - price) * sign * qty - (price + exit_price) * qty * cfg.fee_rate
    if existing_net + added_net < 0:
        return None
    margin = qty * price / min(cfg.max_leverage, 5)
    return qty, margin, qty * price * cfg.fee_rate


def apply_pyramid(p, price, qty, margin, fee, decision_ms):
    # Weighted-average cost basis permits ordinary partial/final exit accounting.
    p.entry = (p.entry * p.qty + price * qty) / (p.qty + qty)
    p.qty += qty
    p.entry_fee += fee
    p.margin += margin
    p.total_entry_qty += qty
    p.pyramid_count += 1
    p.last_pyramid_ms = decision_ms
