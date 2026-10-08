"""Targeted parity and adversarial regression tests; NO market simulation."""
import json
import pytest
from vortex.models import Candle, Signal, Position
from vortex.config import Settings
from vortex.risk import Filters
from vortex.paper import PaperBroker
from vortex.exits import decide_tick, levels_for_bar
from vortex.radar import rank
from vortex.strategies import Derivatives, vote
from vortex.derivatives import DerivativesTracker

F = Filters(.001, .001, 5., .01)


def test_websocket_uses_public_not_market_route():
    from vortex.stream import QuoteStream
    url = QuoteStream(("BTCUSDT",)).url
    assert url.startswith("wss://fstream.binance.com/public/stream?streams=")
    assert "@bookTicker" in url
    assert "/market/" not in url


def test_stage_exits_never_widen_stop():
    p = Position("BTCUSDT", "LONG", 1000, 100., 98., 106., 1., .05, 20.,
                 initial_qty=1., initial_risk=2., peak=100., step=.001)
    tp1 = decide_tick(p, 102.01)
    assert tp1.reason == "tp1" and tp1.qty == .25
    assert p.stop >= 100
    p.qty -= tp1.qty
    tp2 = decide_tick(p, 103.1)
    assert tp2.reason == "tp2" and tp2.qty == .25
    p.qty -= tp2.qty
    assert decide_tick(p, 105.1) is None
    assert p.stop >= 103.1
    stop = p.stop
    assert decide_tick(p, 102.9).reason == "stop"
    assert p.stop >= stop


def test_same_bar_stop_first_even_when_target_reached():
    p = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20,
                 initial_qty=1, initial_risk=2, peak=100, step=.001)
    orders = levels_for_bar(p, 97, 108, 99)
    assert len(orders) == 1 and orders[0].reason == "stop"
    assert orders[0].price == 98


def test_short_stop_first_and_gap_slippage():
    p = Position("BTCUSDT", "SHORT", 1, 100, 102, 94, 1, 0, 20,
                 initial_qty=1, initial_risk=2, peak=100, step=.001)
    orders = levels_for_bar(p, 90, 105, 103)
    assert len(orders) == 1 and orders[0].reason == "stop"
    assert orders[0].price == 103


def test_paper_partial_then_final_one_training_row(tmp_path):
    broker = PaperBroker(Settings(data_dir=tmp_path))
    features = {"volume_ratio": 1.9, "rsi7": 61, "adx14": 28,
                "atr_pct": .01, "return3": .02, "is_long": 1}
    signal = Signal("BTCUSDT", "LONG", 300000, 100, 98, 106, 8,
                    "2 confirmations", features)
    ok, why = broker.open(signal, 99.99, 100.01, F,
                          {"BTCUSDT": (99.99, 100.01)}, 5000000)
    assert ok, why
    first = broker.mark({"BTCUSDT": (102.2, 102.21)}, 5100000)
    assert len(first) == 1 and first[0]["reason"] == "tp1" and not first[0]["final"]
    second = broker.mark({"BTCUSDT": (103.2, 103.21)}, 5200000)
    assert len(second) == 1 and second[0]["reason"] == "tp2"
    broker.mark({"BTCUSDT": (105., 105.01)}, 5300000)  # trailing ratchet
    stop = broker.positions["BTCUSDT"].stop
    assert stop > broker.positions["BTCUSDT"].entry
    last = broker.mark({"BTCUSDT": (stop - .05, stop)}, 5400000)
    assert len(last) == 1 and last[0]["final"] and last[0]["reason"] == "stop"
    assert last[0]["features"] == features
    assert last[0]["y"] == int(last[0]["net_pnl"] > 0)
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    assert len((tmp_path / "partial_exits.jsonl").read_text().splitlines()) == 2
    assert PaperBroker(Settings(data_dir=tmp_path)).closed_count == 1


def test_radar_only_liquid_exchanged_contracts():
    data = [{"symbol": "BTCUSDT", "quoteVolume": "100000000", "priceChangePercent": "3"},
            {"symbol": "ETHUSDT", "quoteVolume": "80000000", "priceChangePercent": "-12"},
            {"symbol": "SCAMUSDT", "quoteVolume": "1e12", "priceChangePercent": "3000"}]
    ranked = rank({"BTCUSDT": {}, "ETHUSDT": {}}, data)
    assert [r.symbol for r in ranked] == ["ETHUSDT", "BTCUSDT"]


class PublicMarket:
    def __init__(self):
        self.oi = 1000
    def get(self, path, params):
        if path.endswith("premiumIndex"):
            return {"symbol": "BTCUSDT", "lastFundingRate": "-0.002"}
        return {"symbol": "BTCUSDT", "openInterest": str(self.oi)}


def test_derivatives_need_two_separated_observations():
    market = PublicMarket()
    tr = DerivativesTracker()
    assert tr.sample(market, "BTCUSDT", 1000000) is None
    market.oi = 1010
    assert tr.sample(market, "BTCUSDT", 1010000) is None
    market.oi = 1020
    d = tr.sample(market, "BTCUSDT", 1100000)
    assert d is not None and d.funding_rate == -.002 and d.oi_change_pct > 0
    assert d.valid(1100000) and not d.valid(1500000)


def test_two_independent_votes_enforced(monkeypatch):
    import vortex.strategies as st
    def series(n, step, offset, mult):
        out = []
        for i in range(n):
            close = 100 + i * mult
            vol = 400 if i == n-1 else 100
            ts = (i-offset) * step
            out.append(Candle(ts, close - .04, close+.04, close-.1, close, vol, ts+step-1))
        return out
    small = series(120, 300000, 0, .2)
    high = series(80, 900000, 40, .3)
    macro = series(60, 3600000, 50, .5)
    monkeypatch.setattr(st, "adx", lambda bars, period=14: 30.)
    monkeypatch.setattr(st, "_macd_hist", lambda closes: 1.)
    s = vote("BTCUSDT", small, high, macro=macro)
    assert s is not None and s.side == "LONG"
    assert "breakout" in s.reason and "trend" in s.reason
    # Drop volume breakout; trend alone must not trigger an entry.
    x = small[-1]
    small[-1] = Candle(x.ts,x.open,x.high,x.low,x.close,100,x.close_ts)
    assert vote("BTCUSDT", small, high, macro=macro) is None



def test_funding_fade_is_real_vote_and_stale_reading_abstains(monkeypatch):
    import vortex.strategies as st
    def series(n, step, offset, mult):
        xs = []
        for i in range(n):
            close = 100 + i * mult
            ts = (i - offset) * step
            xs.append(Candle(ts, close-.05, close+.05, close-.1, close, 100,
                             ts+step-1))
        return xs
    small = series(120, 300000, 0, .2)
    higher = series(80, 900000, 40, .3)
    macro = series(60, 3600000, 50, .5)
    monkeypatch.setattr(st, "adx", lambda x, period=14: 30.)
    monkeypatch.setattr(st, "_macd_hist", lambda x: 1.)
    close_time = small[-1].close_ts
    fresh = Derivatives(-.0016, 1.5, close_time)
    stale = Derivatives(-.0016, 1.5, close_time - 500_000)
    confirmed = vote("BTCUSDT", small, higher, macro, fresh,
                     decision_ms=close_time + 5000)
    assert confirmed is not None and confirmed.side == "LONG"
    assert "funding_fade" in confirmed.reason and "trend" in confirmed.reason
    assert vote("BTCUSDT", small, higher, macro, stale,
                decision_ms=close_time + 5000) is None


def test_partial_close_replay_stop_first_under_ambiguous_candle():
    p = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20.,
                 initial_qty=1, initial_risk=2, step=.001)
    # Both partial milestones and the initial stop touched: refuse to
    # manufacture same-bar "winning" partial fills.
    actions = levels_for_bar(p, low=97.5, high=104, opening=100)
    assert len(actions) == 1 and actions[0].reason == "stop" and actions[0].final
