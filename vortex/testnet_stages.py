"""Explicitly armed TESTNET-only staged exits and safe stop tightening.

Every write uses a persisted unique ID, never replays ambiguous writes.
An existing exchange-held close-all STOP stays active until a tighter STOP
is independently visible. At no point is the current protective stop
cancelled before replacement. A crash in any in-flight transition latches
a state requiring human reconciliation; NEVER fabricate a filled exit.

The broker is for one manually commissioned TESTNET position. No production URL.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from .models import Position
from .exits import decide_tick
from .testnet_guard import ProtectionError
from .exchange_testnet import ExchangeUncertain, ExchangeRejected


def quantize(value: float, tick: float, side: str) -> float:
    d = Decimal(str(tick))
    if d <= 0:
        raise ProtectionError("Unusable tick size")
    rule = ROUND_CEILING if side == "LONG" else ROUND_FLOOR
    return float((Decimal(str(value)) / d).to_integral_value(rounding=rule) * d)


def model(guard, amount: float) -> Position:
    st = guard.state
    need = ["actual_entry", "initial_qty", "initial_risk", "stop", "target", "step", "tick"]
    if any(float(st.get(k) or 0) <= 0 for k in need):
        raise ProtectionError("No audited fill/filters in testnet journal")
    if (amount > 0) != (st["side"] == "LONG"):
        raise ProtectionError("Testnet position side does not match journal")
    return Position(st["symbol"], st["side"], 0, float(st["actual_entry"]),
                    float(st["stop"]), float(st["target"]), abs(amount),
                    0., 0., initial_qty=float(st["initial_qty"]),
                    initial_risk=float(st["initial_risk"]),
                    peak=float(st.get("peak") or st["actual_entry"]),
                    tp1_done=bool(st.get("tp1_done", False)),
                    tp2_done=bool(st.get("tp2_done", False)),
                    step=float(st["step"]),
                    atr_value=float(st.get("atr_value") or float(st["initial_risk"]) / 1.5))


def tighten_stop(guard, wanted: float) -> bool:
    st = guard.state
    if st.get("phase") != "PROTECTED" or st.get("stop_replace_intent") or st.get("old_stop_cancel"):
        raise ProtectionError("Stop replacement already pending / halted")
    symbol, side = st["symbol"], st["side"]
    original = float(st["stop"])
    new = quantize(wanted, float(st["tick"]), side)
    if (new <= original if side == "LONG" else new >= original):
        return False
    amount = guard.api.position(symbol)
    if not amount or not guard.verify_protection(symbol, side):
        guard.halt("Cannot tighten stop: unprotected or absent position")
    old_id = st["stop_id"]
    new_id = guard.client_id("trail")
    closing = "SELL" if side == "LONG" else "BUY"
    guard.persist(stop_replace_intent={"new_id": new_id, "new_price": new, "old_id": old_id})
    try:
        guard.api.protective(symbol, closing, "STOP_MARKET", new, new_id)
    except (ExchangeRejected, ExchangeUncertain) as exc:
        guard.halt(f"New stop response uncertain: {type(exc).__name__}; inspect testnet")
    # New stop MUST be exchange-visible before old one is deleted.
    observed = [o for o in guard.api.open_algos(symbol) if o.get("clientAlgoId") == new_id]
    matches = [o for o in observed
               if o.get("orderType", o.get("type")) == "STOP_MARKET"
               and o.get("side") == closing
               and str(o.get("closePosition")).lower() == "true"
               and Decimal(str(o.get("triggerPrice", "0"))) == Decimal(str(new))]
    if len(matches) != 1:
        guard.halt("Replacement stop not verified; original stop remains on exchange")
    # The transition journal describes BOTH stops if a crash interrupts cleanup.
    guard.persist(stop=new, stop_id=new_id, old_stop_cancel=old_id, stop_replace_intent=None)
    try:
        guard.api.cancel_algo(old_id)
    except (ExchangeRejected, ExchangeUncertain) as exc:
        guard.halt(f"Old stop cancel uncertain: {type(exc).__name__}; both guards may be active")
    if any(o.get("clientAlgoId") == old_id for o in guard.api.open_algos(symbol)):
        guard.halt("Old STOP remained after cancel response; inspect exchange")
    if not guard.verify_protection(symbol, side):
        guard.halt("Protective orders disappeared after replacement")
    guard.persist(old_stop_cancel=None)
    return True


def maintain(guard, bid: float, ask: float, *,
             atr_value: float | None = None, trailing_atr_mult: float = 1.0) -> dict:
    """Operator-armed one-pass TESTNET maintenance using an independent quote."""
    st = guard.state
    if st.get("phase") != "PROTECTED":
        raise ProtectionError("Testnet position not in protected state")
    if st.get("stage_intent") or st.get("stop_replace_intent") or st.get("old_stop_cancel"):
        guard.halt("An incomplete signed order transition requires manual reconciliation")
    if not (0 < bid <= ask):
        raise ValueError("Invalid Testnet bid/ask")
    symbol = st["symbol"]
    amount = guard.api.position(symbol)
    if not amount:
        guard.halt("Position appears flat between audit and update; human reconciliation required")
    if not guard.verify_protection(symbol, st["side"]):
        guard.emergency_flatten(symbol)
        guard.halt("Missing protective order before staged update")
    position = model(guard, amount)
    # Execution side: longs sell at bid, shorts buy at ask, never at mid/last.
    price = bid if st["side"] == "LONG" else ask
    step = decide_tick(position, price, atr_value=atr_value,
                       trailing_atr_mult=trailing_atr_mult)
    if step and step.final:
        # Exchange-side close-all TP or SL must manage final exit; never
        # race the exchange with a second market order at the threshold.
        return {"status": "awaiting exchange-held close-all order"}
    if step and step.reason in {"tp1", "tp2"}:
        if step.qty >= abs(amount) or step.qty <= 0:
            guard.halt("Invalid TESTNET partial quantity")
        cid = guard.client_id(step.reason)
        guard.persist(stage_intent={"id": cid, "qty": step.qty,
                                    "kind": step.reason, "old_qty": abs(amount)})
        closing = "SELL" if st["side"] == "LONG" else "BUY"
        try:
            guard.api.market_order(symbol, closing, step.qty, cid, reduce_only=True)
        except (ExchangeRejected, ExchangeUncertain) as exc:
            guard.halt(f"Partial close uncertain: {type(exc).__name__}; NEVER resend automatically")
        after = abs(guard.api.position(symbol))
        if abs(after - (abs(amount) - step.qty)) > max(.00000001, float(st["step"]) * .1):
            guard.halt("Partial exit not fully confirmed; review Binance position and fills")
        guard.persist(stage_intent=None, tp1_done=position.tp1_done,
                      tp2_done=position.tp2_done, peak=position.peak,
                      atr_value=position.atr_value)
        # The original exchange STOP is still active throughout the partial exit.
        if position.stop != float(st["stop"]):
            tighten_stop(guard, position.stop)
        return {"status": step.reason, "qty": step.qty, "remaining": after}
    # If 2R reached after TP2, ratchet the protected stop without widening it.
    guard.persist(peak=position.peak, tp1_done=position.tp1_done,
                  tp2_done=position.tp2_done, atr_value=position.atr_value)
    if position.stop != float(st["stop"]):
        tightened = tighten_stop(guard, position.stop)
        return {"status": "stop tightened" if tightened else "unchanged",
                "stop": guard.state["stop"]}
    return {"status": "protected and unchanged"}
