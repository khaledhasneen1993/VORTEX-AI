"""Testnet order supervisor with write-ahead state and protective order verification.

This code NEVER accepts production credentials/hostname. Startup refuses unmanaged
positions. Any uncertain order response latches a halt for manual inspection.
Always use exchange position truth, not a local simulated quantity.
"""
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from .exchange_testnet import ExchangeRejected, ExchangeUncertain, decimal_text
from .models import Signal
from .risk import Filters, floor_step


class ProtectionError(RuntimeError):
    pass


class TestnetSupervisor:
    def __init__(self, api, state_path: Path):
        self.api = api
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {"phase": "IDLE", "entry_id": None, "symbol": None}
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        if self.state.get("phase") not in {"IDLE", "INTENT", "PROTECTING", "PROTECTED", "HALTED"}:
            raise ProtectionError("Unrecognized testnet state")

    def persist(self, **values):
        self.state.update(values)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(self.state, fp, sort_keys=True)
            fp.flush()
            os.fsync(fp.fileno())
        tmp.replace(self.path)

    def halt(self, reason):
        self.persist(phase="HALTED", reason=reason)
        raise ProtectionError(reason)

    def start_check(self):
        if self.state["phase"] != "IDLE":
            self.halt("Existing journal needs exchange reconciliation / human review")
        if not self.api.one_way():
            self.halt("Hedge mode unsupported: bot requires ONE-WAY mode")
        active = [p for p in self.api.positions() if abs(float(p.get("positionAmt", 0))) > 1e-12]
        if active:
            self.halt("Unmanaged exchange positions present: refusing new entry")
        # Exchange conditional orders can exist without positions. Reject rather than overwrite.
        algos = self.api.request("GET", "/fapi/v1/openAlgoOrders")
        if algos:
            self.halt("Unmanaged algo orders present: refusing new entry")
        return True

    @staticmethod
    def client_id(prefix: str) -> str:
        return "vx" + prefix + uuid.uuid4().hex[:22]

    def verify_protection(self, symbol: str, expected_side: str) -> bool:
        amount = self.api.position(symbol)
        if abs(amount) <= 1e-12:
            return False
        if (amount > 0) != (expected_side == "LONG"):
            self.halt("Exchange side mismatches journal")
        orders = self.api.open_algos(symbol)
        protective_side = "SELL" if amount > 0 else "BUY"
        # Find only OUR named orders, reject accidentally counting manual protective orders.
        own = [o for o in orders if o.get("clientAlgoId") in
               {self.state.get("stop_id"), self.state.get("take_id")}]
        types = {o.get("orderType", o.get("type")) for o in own
                 if o.get("side") == protective_side and
                 str(o.get("closePosition")).lower() == "true" and
                 o.get("positionSide", "BOTH") == "BOTH"}
        return {"STOP_MARKET", "TAKE_PROFIT_MARKET"} <= types

    def emergency_flatten(self, symbol: str) -> None:
        """Close a known position once; if uncertain, STOP, never repeat blindly."""
        amount = self.api.position(symbol)
        if abs(amount) < 1e-12:
            return
        close_id = self.state.get("close_id") or self.client_id("exit")
        self.persist(close_id=close_id, phase="HALTED", reason="Emergency close attempted")
        try:
            self.api.market_order(symbol, "SELL" if amount > 0 else "BUY",
                                  abs(amount), close_id, reduce_only=True)
        except (ExchangeUncertain, ExchangeRejected) as exc:
            self.halt(f"EMERGENCY CLOSE UNCERTAIN: {type(exc).__name__}; operator must reconcile")

    def enter(self, signal: Signal, qty: float, filt: Filters, leverage: int) -> dict:
        if self.state["phase"] != "IDLE":
            raise ProtectionError("Bot not IDLE; no new orders permitted")
        self.start_check()
        if signal.side not in {"LONG", "SHORT"} or qty <= 0 or leverage not in range(1, 11):
            raise ValueError("Invalid entry parameters")
        if qty < filt.min_qty or qty * signal.entry < filt.min_notional:
            raise ValueError("Exchange minimum violated")
        q = floor_step(qty, filt.step)
        if q != qty:
            raise ValueError("Quantity must be pre-rounded by risk engine")
        if signal.stop <= 0 or signal.target <= 0:
            raise ValueError("Invalid protective prices")
        if not (signal.stop < signal.entry < signal.target if signal.side == "LONG"
                else signal.target < signal.entry < signal.stop):
            raise ValueError("Stop/target wrong side of entry")
        # Bias stop rounding away from price to avoid immediate trigger; reject if risk widens.
        stop = floor_step(signal.stop, filt.tick) if signal.side == "LONG" else (
            -floor_step(-signal.stop, filt.tick) if signal.stop % filt.tick == 0 else
            floor_step(signal.stop, filt.tick) + filt.tick)
        take = floor_step(signal.target, filt.tick)
        if signal.side == "SHORT":
            take = floor_step(signal.target, filt.tick)
        if stop <= 0 or take <= 0:
            raise ValueError("Invalid rounded protective level")
        entry_id = self.client_id("in")
        stop_id = self.client_id("sl")
        take_id = self.client_id("tp")
        self.persist(phase="INTENT", symbol=signal.symbol, side=signal.side,
                     entry_id=entry_id, stop_id=stop_id, take_id=take_id,
                     qty=q, stop=stop, target=take, reason="Entry intent logged")
        try:
            self.api.set_leverage(signal.symbol, leverage)
            side = "BUY" if signal.side == "LONG" else "SELL"
            self.api.market_order(signal.symbol, side, q, entry_id)
            # Do NOT trust a fill acknowledgement without exchange position confirmation.
            actual = self.api.position(signal.symbol)
            if actual == 0 or (actual > 0) != (signal.side == "LONG"):
                self.halt("Entry not confirmed / wrong side; investigate exchange")
            self.persist(phase="PROTECTING", filled_qty=abs(actual))
            closing_side = "SELL" if actual > 0 else "BUY"
            self.api.protective(signal.symbol, closing_side, "STOP_MARKET", stop, stop_id)
            self.api.protective(signal.symbol, closing_side, "TAKE_PROFIT_MARKET", take, take_id)
            if not self.verify_protection(signal.symbol, signal.side):
                self.emergency_flatten(signal.symbol)
                self.halt("Protection could not be verified; emergency reduce-only close sent")
            self.persist(phase="PROTECTED", reason="Two exchange-side close-all guards verified")
            return dict(self.state)
        except (ExchangeRejected, ExchangeUncertain) as exc:
            # A timeout may have OPENED a position. Query truth before acting.
            try:
                actual = self.api.position(signal.symbol)
            except Exception:
                self.halt("Exchange unavailable after ambiguous order; MANUAL RECONCILIATION REQUIRED")
            if abs(actual) > 0:
                self.emergency_flatten(signal.symbol)
            self.halt(f"Order sequence failed: {type(exc).__name__}; account reconciliation required")

    def audit(self) -> dict:
        """Audit existing testnet position. Nothing is retried, repaired or assumed."""
        if self.state["phase"] == "IDLE":
            self.start_check()
            return {"ok": True, "phase": "IDLE"}
        if self.state["phase"] == "HALTED":
            raise ProtectionError(self.state.get("reason", "HALTED"))
        sym, side = self.state["symbol"], self.state["side"]
        amount = self.api.position(sym)
        if not amount:
            # If exchange closed position, orphan conditional orders may remain.
            algos = self.api.open_algos(sym)
            own = [o for o in algos if o.get("clientAlgoId") in
                   {self.state.get("stop_id"), self.state.get("take_id")}]
            if own:
                self.halt("Flat but orphan TP/SL exists; manual cleanup required")
            self.persist(phase="IDLE", entry_id=None, symbol=None, side=None,
                         stop_id=None, take_id=None, close_id=None, reason="Exchange flat")
            return {"ok": True, "phase": "IDLE"}
        if not self.verify_protection(sym, side):
            self.emergency_flatten(sym)
            self.halt("Protective algo missing; emergency reduce-only close sent")
        self.persist(phase="PROTECTED")
        return {"ok": True, "phase": "PROTECTED", "symbol": sym}
