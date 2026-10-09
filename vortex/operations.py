"""Opt-in execution/protection policy. Public observations, never order submission."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class OperationsPolicy:
    enabled: bool = False
    profile: str = "aggressive"
    break_even_r: float = 0.8
    tp1_fraction: float = 0.30
    tp2_fraction: float = 0.30
    terminal_target: bool = False
    stagnant_minutes: int = 60
    stagnant_r: float = 0.5
    funding_guard: bool = True
    funding_window_seconds: int = 300
    funding_rate_threshold: float = 0.001
    liquidity_guard: bool = True
    min_depth_usdt: float = 10000
    depth_band_bps: float = 20
    max_depth_participation: float = 0.02
    max_observation_age_ms: int = 15000
    volatility_slip_factor: float = 0.02
    max_slippage_bps: float = 30
    modeled_latency_ms: int = 500
    cost_multiplier: float = 1.0
    streak_start: int = 2
    streak_cooldown_minutes: int = 30
    streak_max_minutes: int = 120
    drawdown_1h: float = 0.12
    drawdown_2h: float = 0.18
    daily_warning_fraction: float = 0.75
    telegram_alerts: bool = False
    focus_symbol: str = ""

    def __post_init__(self):
        if self.profile not in {"aggressive", "conservative"}:
            raise ValueError("OPS_PROFILE must be aggressive or conservative")
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, (int, float)) and (not isfinite(value) or value < 0):
                raise ValueError("Invalid OPS_" + field.name.upper())
        if not (
            0 < self.break_even_r <= 1
            and 0 < self.tp1_fraction < 1
            and 0 < self.tp2_fraction < 1
            and self.tp1_fraction + self.tp2_fraction < 1
        ):
            raise ValueError("Invalid exit fractions / break-even")
        if not (
            1 <= self.stagnant_minutes <= 1440
            and 0 < self.stagnant_r <= 1
            and 0 < self.drawdown_1h <= self.drawdown_2h <= 0.30
            and 0 < self.max_depth_participation <= 0.1
            and self.min_depth_usdt > 0
            and 0 < self.depth_band_bps <= 100
            and 1 <= self.max_observation_age_ms <= 15000
            and 0 < self.daily_warning_fraction < 1
            and 0 < self.max_slippage_bps <= 30
            and 1 <= self.cost_multiplier <= 3
            and 0 <= self.modeled_latency_ms <= 60000
            and 0 < self.funding_rate_threshold <= 0.1
            and 1 <= self.funding_window_seconds <= 3600
            and self.streak_start >= 2
            and 1 <= self.streak_cooldown_minutes <= self.streak_max_minutes <= 1440
        ):
            raise ValueError("Invalid execution/protection policy")
        if self.focus_symbol and (not self.focus_symbol.isalnum() or not self.focus_symbol.endswith("USDT")):
            raise ValueError("OPS_FOCUS_SYMBOL requires USDT symbol")

    @classmethod
    def from_env(cls):
        values = {}
        for field in fields(cls):
            raw = os.getenv("OPS_" + field.name.upper())
            if raw is None:
                continue
            default = getattr(cls(), field.name)
            if isinstance(default, bool):
                if raw.lower() not in {"true", "false"}:
                    raise ValueError("OPS boolean must be true or false")
                values[field.name] = raw.lower() == "true"
            elif isinstance(default, int):
                values[field.name] = int(raw)
            elif isinstance(default, float):
                values[field.name] = float(raw)
            else:
                values[field.name] = raw.strip().lower() if field.name == "profile" else raw.strip().upper()
        return cls(**values)


def slippage_bps(base, atr_pct, spread_bps, policy):
    """Adverse model, not a measured fill; ATR uses completed observations only."""
    if not policy.enabled:
        return base
    if not all(isfinite(x) and x >= 0 for x in (base, atr_pct, spread_bps)):
        raise ValueError("Invalid slippage inputs")
    # Never make base costs cheaper, including if a configured cap is below base.
    return (
        max(
            base,
            min(
                policy.max_slippage_bps,
                base
                + atr_pct
                * 10000
                * (policy.volatility_slip_factor + (policy.modeled_latency_ms / 60000) ** 0.5 * 0.01)
                + spread_bps * 0.5,
            ),
        )
        * policy.cost_multiplier
    )


def funding_gate(snapshot, now_ms, policy):
    if not policy.enabled or not policy.funding_guard:
        return True, "funding guard disabled"
    if not snapshot:
        return False, "missing funding timing observation"
    observed, rate, next_ms = snapshot
    if not isfinite(rate) or not 0 <= now_ms - observed <= policy.max_observation_age_ms or next_ms <= now_ms:
        return False, "stale or invalid funding timing observation"
    if (
        next_ms - now_ms <= policy.funding_window_seconds * 1000
        and abs(rate) >= policy.funding_rate_threshold
    ):
        return False, "imminent large funding event"
    return True, "funding timing passed"


def depth_capacity(depth, bid, ask, now_ms, policy):
    """Both sides must be liquid inside a narrow band; snapshot timestamp required."""
    if not policy.enabled or not policy.liquidity_guard:
        return float("inf"), "liquidity guard disabled"
    try:
        stamp = int(depth["T"])
        if not 0 <= now_ms - stamp <= policy.max_observation_age_ms or not 0 < bid <= ask:
            return 0.0, "stale depth / invalid quote"
        mid = (bid + ask) / 2
        band = policy.depth_band_bps / 10000
        totals = []
        for side in ("bids", "asks"):
            total = 0.0
            for price, qty in depth[side]:
                price, qty = float(price), float(qty)
                if not isfinite(price + qty) or price <= 0 or qty < 0:
                    return 0.0, "invalid depth levels"
                if abs(price / mid - 1) <= band:
                    total += price * qty
            totals.append(total)
        available = min(totals)
        if available < policy.min_depth_usdt:
            return 0.0, "insufficient near-price liquidity"
        return available * policy.max_depth_participation, "liquidity passed"
    except (KeyError, TypeError, ValueError):
        return 0.0, "missing depth observation"


class Protection:
    """Persisted trailing-window peak drawdown latch and progressive loss cooldown."""

    def __init__(self, policy, state=None):
        self.policy = policy
        state = state or {}
        self.samples = state.get("samples", [])
        self.blocked = state.get("blocked", False)
        self.reason = state.get("reason", "")
        self.streak = state.get("streak", 0)
        self.cooldown_until = state.get("cooldown_until", 0)
        self.warning_day = state.get("warning_day", "")

    def state(self):
        return {
            "samples": self.samples,
            "blocked": self.blocked,
            "reason": self.reason,
            "streak": self.streak,
            "cooldown_until": self.cooldown_until,
            "warning_day": self.warning_day,
        }

    def observe(self, now_ms, equity):
        if not self.policy.enabled:
            return
        if not isfinite(equity) or equity <= 0:
            self.blocked, self.reason = True, "invalid/nonpositive equity"
            return
        if self.samples and now_ms < self.samples[-1][0]:
            raise ValueError("Out-of-order protection clock")
        self.samples = [s for s in self.samples if now_ms - s[0] <= 7200000]
        self.samples.append([now_ms, equity])
        for window, limit in ((3600000, self.policy.drawdown_1h), (7200000, self.policy.drawdown_2h)):
            peak = max(s[1] for s in self.samples if now_ms - s[0] <= window)
            if (peak - equity) / peak >= limit - 1e-12:
                self.blocked, self.reason = True, f"rolling {window // 3600000}h drawdown halt"

    def closed(self, net, now_ms):
        if not self.policy.enabled:
            return
        self.streak = self.streak + 1 if net < 0 else 0
        if self.streak >= self.policy.streak_start:
            minutes = min(
                self.policy.streak_max_minutes,
                self.policy.streak_cooldown_minutes * (self.streak - self.policy.streak_start + 1),
            )
            self.cooldown_until = max(self.cooldown_until, now_ms + minutes * 60000)

    def allow(self, now_ms):
        if not self.policy.enabled:
            return True, "operations disabled"
        if self.blocked:
            return False, self.reason
        if now_ms < self.cooldown_until:
            return False, "progressive losing-streak cooldown"
        return True, "operations passed"


class DecisionJournal(logging.Handler):
    """Append every emitted rejection/skip with original diagnostic explanation."""

    def __init__(self, folder):
        super().__init__(logging.DEBUG)
        self.path = folder / "decisions.jsonl"
        self.count = 0

    def emit(self, record):
        message = record.getMessage()
        if any(
            tag in message
            for tag in (
                "REJECT",
                "ENTRY_SKIP",
                "accepted=False",
                "CARD_SKIP",
                "FILTER",
                "rejected",
                "failed closed",
            )
        ):
            row = {
                "ts_ms": int(record.created * 1000),
                "level": record.levelname,
                "logger": record.name,
                "reason": message,
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.count += 1


def historical_context(observations, symbol, now_ms, policy):
    """Require as-of snapshots; realized future funding is not an entry input."""
    context = (observations or {}).get((symbol, now_ms), {})
    bid, ask = context.get("bid", 0.0), context.get("ask", 0.0)
    allowed, reason = funding_gate(context.get("funding"), now_ms, policy)
    if not allowed:
        return False, reason, 0.0, 0.0
    capacity, reason = depth_capacity(context.get("depth"), bid, ask, now_ms, policy)
    if capacity <= 0:
        return False, reason, 0.0, 0.0
    spread = (ask - bid) / ((ask + bid) / 2) * 10000 if 0 < bid <= ask else 0.0
    return True, reason, capacity, spread


def require_history(observations, policy):
    if policy.enabled and (policy.funding_guard or policy.liquidity_guard) and observations is None:
        raise ValueError(
            "Operations replay requires timestamped funding/depth observations; explicitly disable unavailable guards for an incomplete-model experiment"
        )
