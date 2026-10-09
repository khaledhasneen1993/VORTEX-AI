from vortex.operations import OperationsPolicy

"""Targeted parity and adversarial regression tests; NO market simulation."""
import json

import pytest

from vortex.config import Settings
from vortex.derivatives import DerivativesTracker
from vortex.exits import decide_tick, levels_for_bar
from vortex.models import Position, Signal
from vortex.paper import PaperBroker
from vortex.radar import rank
from vortex.risk import Filters

F = Filters(0.001, 0.001, 5.0, 0.01)


def test_websocket_uses_public_not_market_route():
    from vortex.stream import QuoteStream

    url = QuoteStream(("BTCUSDT",)).url
    assert url.startswith("wss://fstream.binance.com/public/stream?streams=")
    assert "@bookTicker" in url
    assert "/market/" not in url


def test_stage_exits_never_widen_stop():
    p = Position(
        "BTCUSDT",
        "LONG",
        1000,
        100.0,
        98.0,
        106.0,
        1.0,
        0.05,
        20.0,
        initial_qty=1.0,
        initial_risk=2.0,
        peak=100.0,
        step=0.001,
    )
    tp1 = decide_tick(p, 102.01)
    assert tp1.reason == "tp1" and tp1.qty == 0.30
    assert p.stop >= 100
    p.qty -= tp1.qty
    tp2 = decide_tick(p, 103.1)
    assert tp2.reason == "tp2" and tp2.qty == 0.30
    p.qty -= tp2.qty
    assert decide_tick(p, 105.1) is None
    assert p.stop >= 103.1
    stop = p.stop
    assert decide_tick(p, 102.9).reason == "stop"
    assert p.stop >= stop


def test_same_bar_stop_first_even_when_target_reached():
    p = Position(
        "BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20, initial_qty=1, initial_risk=2, peak=100, step=0.001
    )
    orders = levels_for_bar(p, 97, 108, 99)
    assert len(orders) == 1 and orders[0].reason == "stop"
    assert orders[0].price == 98


def test_short_stop_first_and_gap_slippage():
    p = Position(
        "BTCUSDT", "SHORT", 1, 100, 102, 94, 1, 0, 20, initial_qty=1, initial_risk=2, peak=100, step=0.001
    )
    orders = levels_for_bar(p, 90, 105, 103)
    assert len(orders) == 1 and orders[0].reason == "stop"
    assert orders[0].price == 103


def test_paper_partial_then_final_one_training_row(tmp_path):
    broker = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    features = {"volume_ratio": 1.9, "rsi7": 61, "adx14": 28, "atr_pct": 0.01, "return3": 0.02, "is_long": 1}
    signal = Signal("BTCUSDT", "LONG", 300000, 100, 98, 106, 8, "2 confirmations", features)
    ok, why = broker.open(signal, 99.99, 100.01, F, {"BTCUSDT": (99.99, 100.01)}, 5000000)
    assert ok, why
    first = broker.mark({"BTCUSDT": (102.2, 102.21)}, 5100000)
    assert len(first) == 1 and first[0]["reason"] == "tp1" and (not first[0]["final"])
    second = broker.mark({"BTCUSDT": (103.2, 103.21)}, 5200000)
    assert len(second) == 1 and second[0]["reason"] == "tp2"
    broker.mark({"BTCUSDT": (105.0, 105.01)}, 5300000)
    stop = broker.positions["BTCUSDT"].stop
    assert stop > broker.positions["BTCUSDT"].entry
    last = broker.mark({"BTCUSDT": (stop - 0.05, stop)}, 5400000)
    assert len(last) == 1 and last[0]["final"] and (last[0]["reason"] == "stop")
    assert all(last[0]["features"][k] == v for k, v in features.items())
    assert last[0]["features"]["selected_risk_fraction"] > 0
    assert last[0]["y"] == int(last[0]["net_pnl"] > 0)
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    assert len((tmp_path / "partial_exits.jsonl").read_text().splitlines()) == 2
    assert (
        PaperBroker(
            Settings(
                data_dir=tmp_path,
                operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
            )
        ).closed_count
        == 1
    )


def test_radar_only_liquid_exchanged_contracts():
    data = [
        {"symbol": "BTCUSDT", "quoteVolume": "100000000", "priceChangePercent": "3"},
        {"symbol": "ETHUSDT", "quoteVolume": "80000000", "priceChangePercent": "-12"},
        {"symbol": "SCAMUSDT", "quoteVolume": "1e12", "priceChangePercent": "3000"},
    ]
    ranked = rank({"BTCUSDT": {}, "ETHUSDT": {}}, data)
    assert [r.symbol for r in ranked] == ["ETHUSDT", "BTCUSDT"]


class PublicMarket:
    def server_ms(self):
        return self.now

    def __init__(self):
        self.oi = 1000
        self.now = 1000000

    def get(self, path, params):
        if path.endswith("premiumIndex"):
            return {"symbol": "BTCUSDT", "lastFundingRate": "-0.002", "time": self.now}
        return {"symbol": "BTCUSDT", "openInterest": str(self.oi), "time": self.now}


def test_derivatives_need_two_separated_observations():
    market = PublicMarket()
    tr = DerivativesTracker()
    assert tr.sample(market, "BTCUSDT", 1000000) is None
    market.oi = 1010
    market.now = 1010000
    assert tr.sample(market, "BTCUSDT", 1010000) is None
    market.oi = 1020
    market.now = 1100000
    d = tr.sample(market, "BTCUSDT", 1100000)
    assert d is not None and d.funding_rate == -0.002 and (d.oi_change_pct > 0)
    assert d.valid(1100000) and (not d.valid(1500000))


def test_partial_close_replay_stop_first_under_ambiguous_candle():
    p = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20.0, initial_qty=1, initial_risk=2, step=0.001)
    actions = levels_for_bar(p, low=97.5, high=104, opening=100)
    assert len(actions) == 1 and actions[0].reason == "stop" and actions[0].final


def test_ws_rejects_delayed_and_out_of_order_ticks():
    from vortex.stream import QuoteStream

    timestamp = [2000000000000]
    stream = QuoteStream(("BTCUSDT",), wall_ms=lambda: timestamp[0])

    def msg(event_ms, bid="100", ask="100.1"):
        return json.dumps({"data": {"s": "BTCUSDT", "b": bid, "a": ask, "E": event_ms}})

    stream.ingest(msg(timestamp[0] - 500))
    assert stream.snapshot()["BTCUSDT"] == (100.0, 100.1)
    stream.ingest(msg(timestamp[0] - 4000, "200", "200.1"))
    stream.ingest(msg(timestamp[0] - 900, "300", "300.1"))
    assert stream.snapshot()["BTCUSDT"] == (100.0, 100.1)
    timestamp[0] += 4001
    with pytest.raises(ValueError):
        stream.snapshot()


def test_staged_target_has_room_for_trailing():
    from vortex.exits import decide_tick

    p = Position(
        "BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20, initial_qty=1, initial_risk=2, peak=100, step=0.001
    )
    a = decide_tick(p, 102.1)
    assert a.reason == "tp1"
    p.qty -= a.qty
    b = decide_tick(p, 103.1)
    assert b.reason == "tp2"
    p.qty -= b.qty
    assert decide_tick(p, 104.1) is None
    assert p.stop > p.entry
    assert p.target > 104.1
