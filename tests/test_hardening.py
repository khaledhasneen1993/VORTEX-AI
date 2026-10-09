from vortex.operations import OperationsPolicy

"""Offline hardening contract tests; no network, no API credentials or orders."""
import json

import pytest
import requests

from vortex.config import Settings
from vortex.exchange_testnet import ExchangeUncertain, TestnetGateway
from vortex.microstructure import analyze_microstructure
from vortex.models import Candle, Signal
from vortex.portfolio import run_portfolio
from vortex.risk import Filters
from vortex.stream import QuoteStream
from vortex.testnet_guard import ProtectionError, TestnetSupervisor

F = Filters(0.001, 0.001, 5, 0.1)
S = Signal("BTCUSDT", "LONG", 1000, 100, 98, 104, 7, "fixture")


class Response:
    status_code = 200
    headers = {}

    def json(self):
        return {"ok": True}


class Transport:
    def __init__(self, crash=False):
        self.sent = []
        self.crash = crash

    def request(self, method, url, **kwargs):
        self.sent.append((method, url, kwargs))
        if self.crash:
            raise requests.Timeout("unknown execution")
        return Response()


def test_testnet_url_pinned_and_write_needs_arm():
    http = Transport()
    api = TestnetGateway("TEST_KEY", "SECRET", http, clock=lambda: 100000)
    assert api.request("GET", "/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"}) == {"ok": True}
    assert http.sent[0][1].startswith("https://testnet.binancefuture.com/")
    assert "signature=" in http.sent[0][2]["params"]
    assert "TEST_KEY" == http.sent[0][2]["headers"]["X-MBX-APIKEY"]
    with pytest.raises(PermissionError):
        api.market_order("BTCUSDT", "BUY", 0.01, "vxinabc123")
    with pytest.raises(ValueError):
        api.request("GET", "/fapi/v1/userTrades")
    assert len(http.sent) == 1


def test_mutating_timeout_must_not_be_retried():
    http = Transport(crash=True)
    api = TestnetGateway("key", "secret", http, clock=lambda: 100000, armed=True)
    with pytest.raises(ExchangeUncertain):
        api.market_order("BTCUSDT", "BUY", 0.01, "vxentry123")
    assert len(http.sent) == 1


def test_close_all_uses_no_qty_and_no_reduce_only():
    http = Transport()
    api = TestnetGateway("key", "secret", http, clock=lambda: 100000, armed=True)
    api.protective("BTCUSDT", "SELL", "STOP_MARKET", 99.1, "vxstop123")
    payload = http.sent[0][2]["data"]
    assert "closePosition=true" in payload and "algoType=CONDITIONAL" in payload
    assert "triggerPrice=99.1" in payload and "workingType=MARK_PRICE" in payload
    assert "quantity=" not in payload and "reduceOnly=" not in payload


class FakeExchange:
    def __init__(self):
        self.amount = 0.0
        self.algos = []
        self.entry_count = 0
        self.flatten_count = 0
        self.lose_stop = False
        self.margin = "ISOLATED"
        self.hedge = False
        self.other_positions = False

    def one_way(self):
        return not self.hedge

    def positions(self):
        rows = [{"symbol": "BTCUSDT", "positionAmt": str(self.amount)}]
        if self.other_positions:
            rows.append({"symbol": "ETHUSDT", "positionAmt": "1"})
        return rows

    def request(self, method, path, params=None):
        assert method == "GET"
        if path == "/fapi/v1/openOrders":
            return []
        if path == "/fapi/v1/openAlgoOrders":
            return self.algos
        raise AssertionError(path)

    def symbol_config(self, symbol):
        return {"marginType": self.margin}

    def position(self, symbol):
        return self.amount

    def set_leverage(self, symbol, leverage):
        assert leverage <= 10

    def market_order(self, symbol, side, qty, client_id, reduce_only=False):
        if reduce_only:
            self.flatten_count += 1
            self.amount = 0
        else:
            self.entry_count += 1
            self.amount = qty if side == "BUY" else -qty
        return {"status": "FILLED", "avgPrice": "100"}

    def protective(self, symbol, side, kind, trigger, client_id):
        if self.lose_stop and kind == "STOP_MARKET":
            raise ExchangeUncertain("network uncertain")
        self.algos.append(
            {
                "symbol": symbol,
                "side": side,
                "orderType": kind,
                "clientAlgoId": client_id,
                "closePosition": True,
                "positionSide": "BOTH",
                "triggerPrice": str(trigger),
            }
        )
        return {"algoId": len(self.algos)}

    def open_algos(self, symbol):
        return list(self.algos)


def test_testnet_guards_are_persisted_and_verified(tmp_path):
    api = FakeExchange()
    guard = TestnetSupervisor(api, tmp_path / "intent.json")
    result = guard.enter(S, 0.1, F, 5)
    assert result["phase"] == "PROTECTED"
    assert api.entry_count == 1
    assert len(api.algos) == 2
    assert guard.audit()["ok"]
    resumed = TestnetSupervisor(api, tmp_path / "intent.json")
    assert resumed.audit()["phase"] == "PROTECTED"
    with pytest.raises(ProtectionError):
        resumed.enter(S, 0.1, F, 5)
    assert api.entry_count == 1


def test_missing_stop_triggers_emergency_close_and_halt(tmp_path):
    api = FakeExchange()
    guard = TestnetSupervisor(api, tmp_path / "intent.json")
    guard.enter(S, 0.1, F, 5)
    api.algos = api.algos[1:]
    with pytest.raises(ProtectionError):
        guard.audit(may_flatten=True)
    assert api.flatten_count == 1 and guard.state["phase"] == "HALTED"
    with pytest.raises(ProtectionError):
        TestnetSupervisor(api, tmp_path / "intent.json").audit()


def test_failed_stop_submit_closes_position_and_halts(tmp_path):
    api = FakeExchange()
    api.lose_stop = True
    guard = TestnetSupervisor(api, tmp_path / "intent.json")
    with pytest.raises(ProtectionError):
        guard.enter(S, 0.1, F, 5)
    assert api.flatten_count == 1
    assert guard.state["phase"] == "HALTED"


def test_one_way_isolated_and_clean_account_only(tmp_path):
    for field, value in [("hedge", True), ("other_positions", True), ("margin", "CROSSED")]:
        api = FakeExchange()
        setattr(api, field, value)
        guard = TestnetSupervisor(api, tmp_path / field / "intent.json")
        with pytest.raises(ProtectionError):
            guard.enter(S, 0.1, F, 5)
        assert api.entry_count == 0


def test_orderbook_uses_real_buyer_maker_flags():
    depth = {"bids": [["100", "500"]], "asks": [["100.01", "600"]]}
    trades = [{"p": "100", "q": "100", "m": False}, {"p": "100", "q": "20", "m": True}]
    r = analyze_microstructure("LONG", depth, trades)
    assert r.accepted and r.taker_buy_fraction > 0.8
    assert not analyze_microstructure("SHORT", depth, trades).accepted
    assert not analyze_microstructure("LONG", {"bids": [], "asks": []}, trades).accepted


def test_websocket_rejects_stale_or_invalid_quotes():
    t = [10.0]
    tape = QuoteStream(("BTCUSDT",), clock=lambda: t[0], wall_ms=lambda: 1000)
    with pytest.raises(ValueError):
        tape.snapshot()
    tape.ingest(
        json.dumps(
            {"stream": "btcusdt@bookTicker", "data": {"s": "BTCUSDT", "b": "100", "a": "100.1", "E": 999}}
        )
    )
    assert tape.snapshot()["BTCUSDT"] == (100.0, 100.1)
    t[0] = 14
    with pytest.raises(ValueError):
        tape.snapshot()
    assert "btcusdt@bookTicker" in tape.url


def fake_history(step=300000, n=90):
    return [Candle(i * step, 100, 102, 98, 100, 100, i * step + step - 1) for i in range(n)]


def test_portfolio_no_fake_trades_or_profit():
    bars = fake_history()
    symbols = {"BTCUSDT": bars, "ETHUSDT": bars}
    higher = {"BTCUSDT": fake_history(900000), "ETHUSDT": fake_history(900000)}
    f = {"BTCUSDT": F, "ETHUSDT": F}
    report = run_portfolio(
        symbols,
        higher,
        f,
        Settings(
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
        ),
    )
    assert report["closed_trades"] == 0
    assert report["win_rate"] is None
    assert report["profit_factor"] is None
    assert report["cash_wallet"] == 1000


def test_portfolio_rejects_missing_history():
    bars = fake_history()
    bars.pop(10)
    with pytest.raises(ValueError):
        run_portfolio(
            {"BTCUSDT": bars},
            {"BTCUSDT": fake_history(900000)},
            {"BTCUSDT": F},
            Settings(
                operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
            ),
        )


def test_paper_close_journal_crash_is_recoverable(monkeypatch, tmp_path):
    from vortex.paper import PaperBroker

    p = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    ok, _ = p.open(S, 99.99, 100.01, F, {"BTCUSDT": (99.99, 100.01)}, 1000000)
    assert ok
    original = p._write_journal

    def fail_before_append(event):
        raise OSError("simulated disk interruption")

    monkeypatch.setattr(p, "_write_journal", fail_before_append)
    with pytest.raises(OSError):
        p.mark({"BTCUSDT": (97, 97.01)}, 1050000)
    reloaded = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    assert reloaded.closed_count == 1
    assert not reloaded.positions
    assert reloaded.pending_journal is None
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    reloaded.save()
    after = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    assert after.closed_count == 1
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1


def test_emergency_close_must_confirm_exchange_is_flat(tmp_path):

    class PartialEmergency(FakeExchange):
        def market_order(self, symbol, side, qty, client_id, reduce_only=False):
            super().market_order(symbol, side, qty, client_id, reduce_only=reduce_only)
            if reduce_only:
                self.amount = 0.05
            return {"status": "PARTIALLY_FILLED"}

    api = PartialEmergency()
    api.amount = 0.1
    guardian = TestnetSupervisor(api, tmp_path / "partial.json")
    with pytest.raises(ProtectionError, match="partially filled"):
        guardian.emergency_flatten("BTCUSDT")
    assert guardian.state["phase"] == "HALTED"
    assert api.flatten_count == 1


def test_testnet_rejects_unknown_manual_conditional_orders_after_entry(tmp_path):
    api = FakeExchange()
    guard = TestnetSupervisor(api, tmp_path / "orphan.json")
    guard.enter(S, 0.1, F, 5)
    api.algos.append(
        {
            "clientAlgoId": "MANUAL-UNKNOWN",
            "orderType": "STOP_MARKET",
            "side": "SELL",
            "closePosition": True,
            "triggerPrice": "98",
            "positionSide": "BOTH",
        }
    )
    assert not guard.verify_protection("BTCUSDT", "LONG")
