"""Persistent paper trading with fee-aware fills, strict risk and crash recovery."""
from __future__ import annotations
import json
import os
from dataclasses import asdict
from .config import Settings
from .models import Position, Signal
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
        self.positions: dict[str, Position] = {}
        self.last_trade_ts: dict[str, int] = {}
        self.last_signal: dict[str, int] = {}
        self.gate = RiskGate(cfg, self.wallet)
        self.closed_count = 0
        self.pending_journal = None
        if self.state_file.exists():
            self.load()

    def load(self) -> None:
        raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        if raw.get("version") != 1 or raw.get("mode") != "paper":
            raise ValueError("Unsupported saved state; refuse to reset balance")
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
        target = self.trades_file if event.get("final", True) else self.events_file
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

    def save(self) -> None:
        obj = {"version": 1, "mode": "paper", "wallet": self.wallet,
               "positions": {k: asdict(v) for k, v in self.positions.items()},
               "last_trade_ts": self.last_trade_ts, "last_signal": self.last_signal,
               "closed_count": self.closed_count, "pending_journal": self.pending_journal,
               "risk": {"date": self.gate.date, "day_start_equity": self.gate.day_start_equity,
                        "consecutive_losses": self.gate.consecutive_losses, "blocked": self.gate.blocked}}
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

    def open(self, signal: Signal, bid: float, ask: float, filters: Filters,
             quotes: dict[str, tuple[float, float]], now_ms: int) -> tuple[bool, str]:
        if signal.symbol in self.positions:
            return False, "position exists"
        if signal.ts == self.last_signal.get(signal.symbol):
            return False, "duplicate signal"
        equity = self.equity(quotes)
        allowed, reason = self.gate.can_open(equity, len(self.positions))
        if not allowed:
            return False, reason
        if signal.symbol in self.last_trade_ts and now_ms - self.last_trade_ts[signal.symbol] < self.cfg.cooldown_minutes * 60000:
            return False, "cooldown"
        if not (0 < bid <= ask):
            return False, "invalid quote"
        if (ask - bid) / ((bid + ask) / 2) * 10000 > self.cfg.max_spread_bps:
            return False, "excessive spread"
        slip = self.cfg.slippage_bps / 10000
        entry = ask * (1 + slip) if signal.side == "LONG" else bid * (1 - slip)
        stop_gap = abs(signal.entry - signal.stop)
        target_gap = abs(signal.target - signal.entry)
        if stop_gap <= 0 or abs(entry - signal.entry) > stop_gap * 0.35:
            return False, "price ran too far from signal"
        sign = 1 if signal.side == "LONG" else -1
        # Preserve all entry-time metadata after adapting to executable prices.
        from dataclasses import replace
        adjusted = replace(signal, entry=entry,
                           stop=entry - sign * stop_gap,
                           target=entry + sign * target_gap)
        margin_in_use = sum(p.margin for p in self.positions.values())
        sized = size_trade(adjusted, equity, self.cfg, filters, margin_in_use)
        if sized is None:
            return False, "min notional / risk cap prevents entry"
        qty, margin = sized
        fee = qty * entry * self.cfg.fee_rate
        self.wallet -= fee
        self.positions[signal.symbol] = Position(signal.symbol, signal.side, now_ms,
                                                 entry, adjusted.stop, adjusted.target,
                                                 qty, fee, margin,
                                                 features=dict(signal.features),
                                                 initial_qty=qty, initial_risk=stop_gap, peak=entry,
                                                 step=filters.step, votes=list(signal.votes),
                                                 initial_stop=adjusted.stop, initial_target=adjusted.target,
                                                 atr_value=signal.atr_value or stop_gap / 1.5)
        self.last_trade_ts[signal.symbol] = now_ms
        self.last_signal[signal.symbol] = signal.ts
        self.save()
        return True, f"{signal.side} quantity={qty:g} entry={entry:.6g} SL={adjusted.stop:.6g} TP={adjusted.target:.6g}"

    def mark(self, quotes: dict[str, tuple[float, float]], now_ms: int,
             atr_by_symbol: dict[str, float] | None = None) -> list[dict]:
        """Paper close and partial stages; each journal event survives a crash."""
        from .exits import decide_tick
        events: list[dict] = []
        for symbol, p in list(self.positions.items()):
            if symbol not in quotes:
                continue
            bid, ask = quotes[symbol]
            raw = bid if p.side == "LONG" else ask
            action = decide_tick(p, raw,
                                 atr_value=(atr_by_symbol or {}).get(symbol),
                                 trailing_atr_mult=self.cfg.trailing_atr_mult)
            if action is None:
                # May have raised the trailing stop.
                self.save()
                continue
            qty = action.qty
            if qty <= 0 or qty > p.qty:
                raise ValueError("Invalid exit quantity")
            slip = self.cfg.slippage_bps / 10000
            px = action.price * (1 - slip if p.side == "LONG" else 1 + slip)
            sign = 1 if p.side == "LONG" else -1
            ratio = qty / p.qty
            entry_cost = p.entry_fee * ratio
            exit_cost = px * qty * self.cfg.fee_rate
            gross = sign * (px - p.entry) * qty
            stage_net = gross - entry_cost - exit_cost
            self.wallet += gross - exit_cost
            p.entry_fee -= entry_cost
            p.margin *= max(0, 1 - ratio)
            p.qty = max(0., p.qty - qty)
            p.accumulated_net += stage_net
            p.filled_stage_count += 1
            final = action.final or p.qty < max(1e-12, p.step * .5)
            if final and p.qty > p.step * .5:
                raise ValueError("Final exit must flatten the entire position")
            all_net = p.accumulated_net
            event = {
                "event_id": f"{symbol}:{p.opened_ts}:{p.filled_stage_count}",
                "symbol": symbol, "side": p.side, "opened_ts": p.opened_ts,
                "closed_ts": now_ms, "entry": p.entry, "exit": px,
                "quantity": qty, "net_pnl": round(all_net if final else stage_net, 8),
                "stage_net_pnl": round(stage_net, 8), "final": bool(final),
                "entry_ts": p.opened_ts, "exit_ts": now_ms,
                "features": dict(p.features), "entry_indicators": dict(p.features),
                "votes": list(p.votes), "approved_votes": list(p.votes),
                "initial_stop": p.initial_stop or p.entry - (1 if p.side == "LONG" else -1) * p.initial_risk,
                "initial_target": p.initial_target or p.target,
                "r_multiple": round(all_net / ((p.initial_qty or qty) * p.initial_risk), 6)
                              if p.initial_risk > 0 else None,
                "source": "paper",
                "reason": action.reason, "wallet": round(self.wallet, 8),
            }
            if final:
                event["y"] = int(all_net > 0)
                self.closed_count += 1
                self.gate.closed(all_net)
                del self.positions[symbol]
            self.pending_journal = event
            self.save()
            self._write_journal(event)
            self.pending_journal = None
            self.save()
            events.append(event)
        return events

    def reset_halt(self, acknowledge: bool) -> None:
        """Explicit local operator action; does NOT reset wallet or daily loss floor."""
        if not acknowledge or self.positions:
            raise ValueError("Risk reset needs operator acknowledgement and zero open positions")
        self.gate.blocked = False
        self.gate.consecutive_losses = 0
        self.save()
