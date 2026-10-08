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
        self.wallet = cfg.starting_equity
        self.positions: dict[str, Position] = {}
        self.last_trade_ts: dict[str, int] = {}
        self.last_signal: dict[str, int] = {}
        self.gate = RiskGate(cfg, self.wallet)
        self.closed_count = 0
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
        risk = raw["risk"]
        self.gate.date = risk["date"]
        self.gate.day_start_equity = float(risk["day_start_equity"])
        self.gate.consecutive_losses = int(risk["consecutive_losses"])
        self.gate.blocked = bool(risk["blocked"])

    def save(self) -> None:
        obj = {"version": 1, "mode": "paper", "wallet": self.wallet,
               "positions": {k: asdict(v) for k, v in self.positions.items()},
               "last_trade_ts": self.last_trade_ts, "last_signal": self.last_signal,
               "closed_count": self.closed_count,
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
        if now_ms - self.last_trade_ts.get(signal.symbol, 0) < self.cfg.cooldown_minutes * 60000:
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
        adjusted = Signal(signal.symbol, signal.side, signal.ts, entry,
                          entry - sign * stop_gap, entry + sign * target_gap,
                          signal.score, signal.reason)
        margin_in_use = sum(p.margin for p in self.positions.values())
        sized = size_trade(adjusted, equity, self.cfg, filters, margin_in_use)
        if sized is None:
            return False, "min notional / risk cap prevents entry"
        qty, margin = sized
        fee = qty * entry * self.cfg.fee_rate
        self.wallet -= fee
        self.positions[signal.symbol] = Position(signal.symbol, signal.side, now_ms,
                                                 entry, adjusted.stop, adjusted.target,
                                                 qty, fee, margin)
        self.last_trade_ts[signal.symbol] = now_ms
        self.last_signal[signal.symbol] = signal.ts
        self.save()
        return True, f"{signal.side} quantity={qty:g} entry={entry:.6g} SL={adjusted.stop:.6g} TP={adjusted.target:.6g}"

    def mark(self, quotes: dict[str, tuple[float, float]], now_ms: int) -> list[dict]:
        exits: list[dict] = []
        for symbol, p in list(self.positions.items()):
            if symbol not in quotes:
                continue
            bid, ask = quotes[symbol]
            raw = bid if p.side == "LONG" else ask
            hit_stop = raw <= p.stop if p.side == "LONG" else raw >= p.stop
            hit_target = raw >= p.target if p.side == "LONG" else raw <= p.target
            if not (hit_stop or hit_target):
                continue
            slip = self.cfg.slippage_bps / 10000
            px = raw * (1 - slip if p.side == "LONG" else 1 + slip)
            sign = 1 if p.side == "LONG" else -1
            exit_fee = px * p.qty * self.cfg.fee_rate
            net = sign * (px - p.entry) * p.qty - p.entry_fee - exit_fee
            self.wallet += sign * (px - p.entry) * p.qty - exit_fee
            item = {"symbol": symbol, "side": p.side, "opened_ts": p.opened_ts,
                    "closed_ts": now_ms, "entry": p.entry, "exit": px,
                    "quantity": p.qty, "net_pnl": round(net, 8),
                    "reason": "stop" if hit_stop else "target", "wallet": round(self.wallet, 8)}
            with self.trades_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item) + "\n")
            exits.append(item)
            del self.positions[symbol]
            self.closed_count += 1
            self.gate.closed(net)
            self.save()
        return exits
