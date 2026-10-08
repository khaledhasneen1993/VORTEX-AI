"""TESTNET staging mock tests: no network, no real positions, no API keys."""
import pytest
from vortex.models import Signal
from vortex.risk import Filters
from vortex.testnet_guard import TestnetSupervisor, ProtectionError
from vortex.testnet_stages import maintain, tighten_stop
from vortex.exchange_testnet import ExchangeUncertain

F = Filters(.001, .001, 5., .01)
S = Signal("BTCUSDT", "LONG", 10, 100, 98, 106, 7, "trend + breakout")


class Exchange:
    def __init__(self, *, uncertain_cancel=False):
        self.qty = 0.
        self.algos = []
        self.requests = []
        self.uncertain_cancel = uncertain_cancel

    def one_way(self):
        return True

    def positions(self):
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.qty)}]

    def request(self, method, endpoint, params=None):
        if endpoint in {"/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders"}:
            return self.algos if endpoint.endswith("AlgoOrders") else []
        raise AssertionError(endpoint)

    def symbol_config(self, symbol):
        return {"marginType": "ISOLATED"}

    def position(self, symbol):
        return self.qty

    def open_algos(self, symbol):
        return list(self.algos)

    def set_leverage(self, symbol, lev):
        assert lev == 5

    def market_order(self, symbol, side, qty, client_id, reduce_only=False):
        self.requests.append((side, qty, client_id, reduce_only))
        if reduce_only:
            self.qty += qty if side == "BUY" else -qty
        else:
            self.qty += qty if side == "BUY" else -qty
        return {"status": "FILLED", "avgPrice": "100"}

    def protective(self, symbol, side, kind, trigger, client_id):
        self.algos.append({"clientAlgoId": client_id, "orderType": kind,
                           "side": side, "closePosition": True,
                           "positionSide": "BOTH", "triggerPrice": str(trigger)})
        return {"algoId": len(self.algos)}

    def cancel_algo(self, client_id):
        if self.uncertain_cancel:
            raise ExchangeUncertain("unconfirmed DELETE")
        self.algos = [o for o in self.algos if o["clientAlgoId"] != client_id]
        return {"code": 200}


def test_partial_exit_then_tighten_never_cancels_only_stop(tmp_path):
    exchange = Exchange()
    supervisor = TestnetSupervisor(exchange, tmp_path / "journal.json")
    assert supervisor.enter(S, .100, F, 5)["phase"] == "PROTECTED"
    assert len(exchange.algos) == 2
    old_stop = supervisor.state["stop_id"]
    result = maintain(supervisor, 102.1, 102.11)
    assert result["status"] == "tp1"
    assert exchange.qty == pytest.approx(.075)
    assert supervisor.state["stop"] >= 100
    assert exchange.requests[-1][-1]  # reduceOnly
    assert old_stop not in {o["clientAlgoId"] for o in exchange.algos}
    assert supervisor.verify_protection("BTCUSDT", "LONG")
    result2 = maintain(supervisor, 103.1, 103.11)
    assert result2["status"] == "tp2"
    assert exchange.qty == pytest.approx(.05)
    assert maintain(supervisor, 105.1, 105.11)["status"] == "stop tightened"
    assert supervisor.state["stop"] >= 103.0
    assert supervisor.verify_protection("BTCUSDT", "LONG")
    assert TestnetSupervisor(exchange, tmp_path / "journal.json").audit()["ok"]


def test_unknown_cancel_latches_account_and_keeps_both_guards(tmp_path):
    exchange = Exchange(uncertain_cancel=True)
    supervisor = TestnetSupervisor(exchange, tmp_path / "journal.json")
    supervisor.enter(S, .100, F, 5)
    with pytest.raises(ProtectionError):
        maintain(supervisor, 102.1, 102.11)
    assert exchange.qty == pytest.approx(.075)
    assert supervisor.state["phase"] == "HALTED"
    assert len(exchange.algos) == 3
    with pytest.raises(ProtectionError):
        TestnetSupervisor(exchange, tmp_path / "journal.json").audit()


def test_unarmed_or_unconfirmed_state_cannot_send_partial(tmp_path):
    exchange = Exchange()
    supervisor = TestnetSupervisor(exchange, tmp_path / "journal.json")
    with pytest.raises(ProtectionError):
        maintain(supervisor, 105, 105.01)
    assert not exchange.requests
    supervisor.enter(S, .100, F, 5)
    supervisor.persist(stage_intent={"id": "vxpending", "qty": 0.025})
    with pytest.raises(ProtectionError):
        maintain(supervisor, 102.1, 102.11)
    assert len(exchange.requests) == 1  # initial order only


def test_flat_exchange_cleanup_does_not_cancel_unrelated_orders(tmp_path):
    exchange = Exchange()
    supervisor = TestnetSupervisor(exchange, tmp_path / "journal.json")
    supervisor.enter(S, .100, F, 5)
    exchange.qty = 0
    with pytest.raises(ProtectionError):
        supervisor.audit(may_flatten=False)
    # Inspection mode halted intentionally; simulate operator creating a new
    # clean journal for a separate fixture.
    exchange = Exchange()
    supervisor = TestnetSupervisor(exchange, tmp_path / "other.json")
    supervisor.enter(S, .100, F, 5)
    exchange.qty = 0
    exchange.algos.append({"clientAlgoId": "manual_other", "orderType": "STOP_MARKET"})
    assert supervisor.audit(may_flatten=True)["phase"] == "IDLE"
    assert {x["clientAlgoId"] for x in exchange.algos} == {"manual_other"}
