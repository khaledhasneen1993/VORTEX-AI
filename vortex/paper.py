"""Persistent paper trading with fee-aware fills, strict risk and crash recovery."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .config import Settings
from .models import Position, Signal
from .operations import Protection, depth_capacity, funding_gate, slippage_bps
from .phase2 import (
    ProfitReserve,
    apply_pyramid,
    correlation_gate,
    initialize_position,
    pyramid_plan,
    risk_fraction,
    stop_exposure,
)
from .risk import Filters, RiskGate, size_trade


class PaperBroker:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.folder = cfg.data_dir
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_file = self.folder / "paper_state.json"
        self.trades_file = self.folder / "closed_trades.jsonl"
        self.events_file = self.folder / "partial_exits.jsonl"
        self.wallet = cfg.starting_equity
        self.reserve = ProfitReserve(cfg)
        self.entries_file = self.folder / "entries.jsonl"
        self.pyramids_file = self.folder / "pyramids.jsonl"
        self.positions: dict[str, Position] = {}
        self.last_trade_ts: dict[str, int] = {}
        self.last_signal: dict[str, int] = {}
        self.gate = RiskGate(cfg, self.wallet)
        self.protection = Protection(cfg.operations)
        self.closed_count = 0
        self.pending_journal = None
        if self.state_file.exists():
            self.load()

    def load(self) -> None:
        raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        if raw.get("version") != 1 or raw.get("mode") != "paper":
            raise ValueError("Unsupported saved state; refuse to reset balance")
        saved_ops = raw.get("operations_policy")
        if saved_ops is not None:
            legacy_ops = "short_loss_cooldown" not in saved_ops
            saved_ops.setdefault("short_loss_cooldown", False)
            if (
                legacy_ops
                and saved_ops.get("profile") == "aggressive"
                and self.cfg.operations.profile == "default"
            ):
                # The old 'aggressive' label meant unchanged defaults, not this preset.
                saved_ops["profile"] = "default"
        if saved_ops != (asdict(self.cfg.operations) if self.cfg.operations.enabled else None):
            raise ValueError("Operations policy changed: use a new isolated session")
        saved_entry = raw.get(
            "opportunity_policy",
            {
                "strict_votes": True,
                "allow_single_strong_vote": False,
                "min_strong_score": 7,
            },
        )
        saved_entry.setdefault("flow_policy", self._flow_policy(defaults=True))
        if saved_entry != self._opportunity_policy():
            raise ValueError("Entry policy changed: use a new isolated session")
        self.protection = Protection(self.cfg.operations, raw.get("protection"))
        saved_policy = raw.get("phase2_policy")
        if saved_policy is not None:
            # Existing default sessions predate the opt-in; absent means disabled.
            saved_policy["policy"].setdefault("aggressive_strong_risk", False)
        if saved_policy is not None and saved_policy != self._phase2_policy():
            raise ValueError("Phase2 policy changed: use a new isolated session")
        if saved_policy is None and self.cfg.phase2.enabled and raw["positions"]:
            raise ValueError("Cannot migrate active legacy exposure into phase2")
        self.reserve = ProfitReserve(self.cfg, float(raw.get("reserved_profit", 0)))
        self.wallet = float(raw["wallet"])
        self.positions = {k: Position(**v) for k, v in raw["positions"].items()}
        self.last_trade_ts = {k: int(v) for k, v in raw.get("last_trade_ts", {}).items()}
        self.last_signal = {k: int(v) for k, v in raw.get("last_signal", {}).items()}
        self.closed_count = int(raw.get("closed_count", 0))
        self.pending_journal = raw.get("pending_journal")
        risk = raw["risk"]
        self.gate.date = risk["date"]
        self.gate.day_start_equity = float(risk["day_start_equity"])
        self.gate.consecutive_losses = int(risk["consecutive_losses"])
        self.gate.blocked = bool(risk["blocked"])
        # Recovery is idempotent if a crash occurs between state commit and log append.
        if self.pending_journal is not None:
            self._write_journal(self.pending_journal)
            self.pending_journal = None
            self.save()

    def _write_journal(self, event: dict) -> None:
        target = (
            self.entries_file
            if event.get("kind") == "entry"
            else self.pyramids_file
            if event.get("kind") == "pyramid"
            else self.trades_file
            if event.get("final", True)
            else self.events_file
        )
        existing = set()
        if target.exists():
            with target.open("r", encoding="utf-8") as fp:
                for line in fp:
                    if line.strip():
                        old = json.loads(line)
                        if old.get("event_id"):
                            existing.add(old["event_id"])
        if event["event_id"] not in existing:
            with target.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(event) + "\n")
                fp.flush()
                os.fsync(fp.fileno())

    def _finish_pending(self):
        # Do not overwrite a saved exit/add event after an append failure.
        if self.pending_journal is not None:
            self._write_journal(self.pending_journal)
            self.pending_journal = None
            self.save()

    def _phase2_policy(self):
        return (
            {
                "policy": asdict(self.cfg.phase2),
                "risk_per_trade": self.cfg.risk_per_trade,
                "daily_loss": self.cfg.max_daily_loss,
                "positions": self.cfg.max_positions,
                "trailing": self.cfg.trailing_atr_mult,
            }
            if self.cfg.phase2.enabled
            else None
        )

    def _opportunity_policy(self):
        return {
            "strict_votes": self.cfg.phase1.strict_votes,
            "allow_single_strong_vote": self.cfg.phase1.allow_single_strong_vote,
            "min_strong_score": self.cfg.min_strong_score,
            "flow_policy": self._flow_policy(),
        }

    def _flow_policy(self, defaults=False):
        from .phase1_config import StrategyPolicy

        policy = StrategyPolicy() if defaults else self.cfg.phase1
        return {k: v for k, v in asdict(policy).items() if k.startswith("flow_")}

    def save(self) -> None:
        obj = {
            "version": 1,
            "mode": "paper",
            "wallet": self.wallet,
            "reserved_profit": self.reserve.reserved,
            "phase2_policy": self._phase2_policy(),
            "opportunity_policy": self._opportunity_policy(),
            "operations_policy": asdict(self.cfg.operations) if self.cfg.operations.enabled else None,
            "protection": self.protection.state(),
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "last_trade_ts": self.last_trade_ts,
            "last_signal": self.last_signal,
            "closed_count": self.closed_count,
            "pending_journal": self.pending_journal,
            "risk": {
                "date": self.gate.date,
                "day_start_equity": self.gate.day_start_equity,
                "consecutive_losses": self.gate.consecutive_losses,
                "blocked": self.gate.blocked,
            },
        }
        tmp = self.state_file.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.state_file)

    def equity(self, quotes: dict[str, tuple[float, float]]) -> float:
        unrealized = 0.0
        for symbol, p in self.positions.items():
            if symbol not in quotes:
                raise ValueError("Missing quote for open position: freeze new trades")
            bid, ask = quotes[symbol]
            px = bid if p.side == "LONG" else ask
            sign = 1 if p.side == "LONG" else -1
            unrealized += sign * (px - p.entry) * p.qty - px * p.qty * self.cfg.fee_rate
        return self.wallet + unrealized

    def open(
        self,
        signal: Signal,
        bid: float,
        ask: float,
        filters: Filters,
        quotes: dict[str, tuple[float, float]],
        now_ms: int,
        histories=None,
        funding=None,
        depth=None,
    ) -> tuple[bool, str]:
        self._finish_pending()
        if signal.symbol in self.positions:
            return False, "position exists"
        if signal.ts == self.last_signal.get(signal.symbol):
            return False, "duplicate signal"
        equity = self.equity(quotes)
        self.protection.observe(now_ms, equity)
        allowed, reason = self.protection.allow(now_ms)
        if not allowed:
            self.save()
            return False, reason
        allowed, reason = funding_gate(funding, now_ms, self.cfg.operations)
        if not allowed:
            return False, reason
        capacity, reason = depth_capacity(depth, bid, ask, now_ms, self.cfg.operations)
        if capacity <= 0:
            return False, reason
        allowed, reason = self.gate.can_open(equity, len(self.positions))
        if not allowed:
            return False, reason
        if (
            signal.symbol in self.last_trade_ts
            and now_ms - self.last_trade_ts[signal.symbol] < self.cfg.cooldown_minutes * 60000
        ):
            return False, "cooldown"
        if not (0 < bid <= ask):
            return False, "invalid quote"
        if (ask - bid) / ((bid + ask) / 2) * 10000 > self.cfg.max_spread_bps:
            return False, "excessive spread"
        spread = (ask - bid) / ((ask + bid) / 2) * 10000
        modeled_slip = slippage_bps(
            self.cfg.slippage_bps, signal.atr_value / signal.entry, spread, self.cfg.operations
        )
        slip = modeled_slip / 10000
        entry = ask * (1 + slip) if signal.side == "LONG" else bid * (1 - slip)
        stop_gap = abs(signal.entry - signal.stop)
        target_gap = abs(signal.target - signal.entry)
        if stop_gap <= 0 or abs(entry - signal.entry) > stop_gap * 0.35:
            return False, "price ran too far from signal"
        sign = 1 if signal.side == "LONG" else -1
        # Preserve all entry-time metadata after adapting to executable prices.
        from dataclasses import replace

        adjusted = replace(
            signal, entry=entry, stop=entry - sign * stop_gap, target=entry + sign * target_gap
        )
        corr_ok, corr_reason = correlation_gate(
            signal, self.positions, histories or {}, now_ms, self.cfg.phase2
        )
        if not corr_ok:
            return False, corr_reason
        capital = self.reserve.capital(self.wallet, equity)
        margin_in_use = sum(p.margin for p in self.positions.values())
        committed_risk = sum(stop_exposure(p, self.cfg) for p in self.positions.values())
        from dataclasses import replace

        cost_cfg = replace(self.cfg, slippage_bps=modeled_slip)
        sized = size_trade(adjusted, capital, cost_cfg, filters, margin_in_use, committed_risk=committed_risk)
        if sized is None:
            return False, "min notional / risk cap prevents entry"
        qty, margin = sized
        if qty * entry > capacity:
            return False, "order exceeds observed depth participation limit"
        fee = qty * entry * self.cfg.fee_rate
        self.wallet -= fee
        self.positions[signal.symbol] = Position(
            signal.symbol,
            signal.side,
            now_ms,
            entry,
            adjusted.stop,
            adjusted.target,
            qty,
            fee,
            margin,
            features=dict(signal.features),
            initial_qty=qty,
            initial_risk=stop_gap,
            peak=entry,
            step=filters.step,
            votes=list(signal.votes),
            initial_stop=adjusted.stop,
            initial_target=adjusted.target,
            atr_value=signal.atr_value or stop_gap / 1.5,
        )
        initialize_position(self.positions[signal.symbol], signal, capital, self.cfg)
        if self.cfg.phase2.enabled:
            self.positions[signal.symbol].features["selected_risk_fraction"] = risk_fraction(signal, self.cfg)
        self.last_trade_ts[signal.symbol] = now_ms
        self.last_signal[signal.symbol] = signal.ts
        if self.cfg.operations.enabled:
            self.pending_journal = dict(
                kind="entry",
                event_id=f"{signal.symbol}:{now_ms}:entry",
                source="paper",
                score=signal.score,
                reason=signal.reason,
                modeled_slippage_bps=modeled_slip,
                position=asdict(self.positions[signal.symbol]),
            )
        self.save()
        self._finish_pending()
        return (
            True,
            f"{signal.side} quantity={qty:g} entry={entry:.6g} SL={adjusted.stop:.6g} TP={adjusted.target:.6g}",
        )

    def mark(
        self,
        quotes: dict[str, tuple[float, float]],
        now_ms: int,
        atr_by_symbol: dict[str, float] | None = None,
    ) -> list[dict]:
        """Paper close and partial stages; each journal event survives a crash."""
        self._finish_pending()
        from .exits import decide_tick

        events: list[dict] = []
        for symbol, p in list(self.positions.items()):
            if symbol not in quotes:
                continue
            bid, ask = quotes[symbol]
            raw = bid if p.side == "LONG" else ask
            action = decide_tick(
                p,
                raw,
                atr_value=(atr_by_symbol or {}).get(symbol),
                trailing_atr_mult=self.cfg.trailing_atr_mult,
                policy=self.cfg.operations,
                now_ms=now_ms,
            )
            if action is None:
                # May have raised the trailing stop.
                self.save()
                continue
            qty = action.qty
            if qty <= 0 or qty > p.qty:
                raise ValueError("Invalid exit quantity")
            slip = (
                slippage_bps(
                    self.cfg.slippage_bps,
                    p.atr_value / p.entry,
                    (ask - bid) / ((ask + bid) / 2) * 10000,
                    self.cfg.operations,
                )
                / 10000
            )
            px = action.price * (1 - slip if p.side == "LONG" else 1 + slip)
            sign = 1 if p.side == "LONG" else -1
            ratio = qty / p.qty
            entry_cost = p.entry_fee * ratio
            exit_cost = px * qty * self.cfg.fee_rate
            gross = sign * (px - p.entry) * qty
            stage_net = gross - entry_cost - exit_cost
            self.wallet += gross - exit_cost
            self.reserve.record(stage_net)
            p.entry_fee -= entry_cost
            p.margin *= max(0, 1 - ratio)
            p.qty = max(0.0, p.qty - qty)
            p.accumulated_net += stage_net
            p.filled_stage_count += 1
            final = action.final or p.qty < max(1e-12, p.step * 0.5)
            if final and p.qty > p.step * 0.5:
                raise ValueError("Final exit must flatten the entire position")
            all_net = p.accumulated_net
            event = {
                "event_id": f"{symbol}:{p.opened_ts}:{p.filled_stage_count}",
                "symbol": symbol,
                "side": p.side,
                "opened_ts": p.opened_ts,
                "closed_ts": now_ms,
                "entry": p.entry,
                "exit": px,
                "quantity": qty,
                "net_pnl": round(all_net if final else stage_net, 8),
                "stage_net_pnl": round(stage_net, 8),
                "final": bool(final),
                "gross_pnl": gross,
                "exit_fee": exit_cost,
                "allocated_entry_fee": entry_cost,
                "remaining_qty": p.qty,
                "modeled_slippage_bps": slip * 10000,
                "stop_at_exit": p.stop,
                "entry_ts": p.opened_ts,
                "exit_ts": now_ms,
                "features": dict(p.features),
                "entry_indicators": dict(p.features),
                "votes": list(p.votes),
                "approved_votes": list(p.votes),
                "initial_stop": p.initial_stop or p.entry - (1 if p.side == "LONG" else -1) * p.initial_risk,
                "initial_target": p.initial_target or p.target,
                "r_multiple": round(all_net / ((p.initial_qty or qty) * p.initial_risk), 6)
                if p.initial_risk > 0
                else None,
                "source": "paper",
                "pyramid_count": p.pyramid_count,
                "total_entry_qty": p.total_entry_qty or p.initial_qty,
                "risk_fraction": p.risk_fraction,
                "reserved_profit": self.reserve.reserved,
                "reason": action.reason,
                "wallet": round(self.wallet, 8),
            }
            if final:
                event["y"] = int(all_net > 0)
                self.closed_count += 1
                self.gate.closed(all_net)
                self.protection.closed(all_net, now_ms)
                del self.positions[symbol]
            self.pending_journal = event
            self.save()
            self._write_journal(event)
            self.pending_journal = None
            self.save()
            events.append(event)
        return events

    def pyramid(self, symbol, bid, ask, filters, quotes, now_ms, histories=None, funding=None, depth=None):
        """Call only AFTER normal exit management with fresh completed histories."""
        self._finish_pending()
        if symbol not in self.positions or not self.cfg.phase2.enabled:
            return None
        equity = self.equity(quotes)
        self.protection.observe(now_ms, equity)
        if not self.protection.allow(now_ms)[0] or not funding_gate(funding, now_ms, self.cfg.operations)[0]:
            return None
        capacity, _ = depth_capacity(depth, bid, ask, now_ms, self.cfg.operations)
        if capacity <= 0:
            return None
        # Position count doesn't prohibit bounded additions, daily loss does.
        self.gate.can_open(equity, 0)
        if self.gate.blocked or not (0 < bid <= ask):
            return None
        if (ask - bid) / ((ask + bid) / 2) * 10000 > self.cfg.max_spread_bps:
            return None
        p = self.positions[symbol]
        bars = (histories or {}).get(symbol, [])
        if not bars or not 0 <= now_ms - bars[-1].close_ts <= 390000:
            return None
        observed = bars[-1].close
        slip = (
            slippage_bps(
                self.cfg.slippage_bps,
                p.atr_value / p.entry,
                (ask - bid) / ((ask + bid) / 2) * 10000,
                self.cfg.operations,
            )
            / 10000
        )
        price = ask * (1 + slip) if p.side == "LONG" else bid * (1 - slip)
        candidate = Signal(symbol, p.side, now_ms, price, p.stop, p.target, 10, "pyramid")
        allowed, _ = correlation_gate(candidate, self.positions, histories or {}, now_ms, self.cfg.phase2)
        if not allowed:
            return None
        from dataclasses import replace

        cost_cfg = replace(self.cfg, slippage_bps=slip * 10000)
        plan = pyramid_plan(
            p,
            price,
            now_ms,
            cost_cfg,
            filters,
            self.reserve.capital(self.wallet, equity),
            sum(x.margin for x in self.positions.values()),
            sum(stop_exposure(x, self.cfg) for x in self.positions.values()),
            observed,
        )
        if plan is None:
            return None
        qty, margin, fee = plan
        if qty * price > capacity:
            return None
        old_stop = p.stop
        apply_pyramid(p, price, qty, margin, fee, now_ms)
        self.wallet -= fee
        event = dict(
            kind="pyramid",
            event_id=f"{symbol}:{p.opened_ts}:add:{p.pyramid_count}",
            symbol=symbol,
            side=p.side,
            ts=now_ms,
            qty=qty,
            price=price,
            fee=fee,
            margin=margin,
            stop=old_stop,
            target=p.target,
            anchor_entry=p.anchor_entry,
            weighted_entry=p.entry,
            pyramid_count=p.pyramid_count,
            source="paper",
        )
        self.pending_journal = event
        self.save()
        self._write_journal(event)
        self.pending_journal = None
        self.save()
        return event

    def reset_halt(self, acknowledge: bool) -> None:
        """Explicit local operator action; does NOT reset wallet or daily loss floor."""
        if not acknowledge or self.positions:
            raise ValueError("Risk reset needs operator acknowledgement and zero open positions")
        self.protection = Protection(self.cfg.operations)
        self.gate.blocked = False
        self.gate.consecutive_losses = 0
        self.save()
