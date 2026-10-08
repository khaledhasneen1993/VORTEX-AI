"""User-requested VORTEX 7-point spec: no public network or signed exchange writes."""
import json
import logging
from dataclasses import replace

import pytest

from vortex.config import Settings
from vortex.exits import decide_tick, levels_for_bar
from vortex.models import Candle, Position, Signal
from vortex.paper import PaperBroker
from vortex.risk import Filters, trailing_stop
from vortex.reports import save_report, summary
from vortex.strategies import vote
from vortex.testnet_guard import ProtectionError, TestnetSupervisor
from vortex.exchange_testnet import TestnetGateway


def _bars(n, step, offset, slope, volume=100):
    out = []
    for i in range(n):
        p = 100. + i * slope
        t = (i - offset) * step
        out.append(Candle(t, p-0.04, p+0.04, p-0.1, p, volume, t+step-1))
    return out


def test_default_two_votes_rejected_but_one_strong_accepted(monkeypatch, caplog):
    import vortex.strategies as st
    small = _bars(120, 300000, 0, .20)
    small[-1] = replace(small[-1], volume=220)
    higher = _bars(80, 900000, 40, .30)
    macro = _bars(240, 3600000, 231, .50)
    monkeypatch.setattr(st, "adx", lambda bars, period=14: 12. if bars is small else 30.)
    monkeypatch.setattr(st, "_macd_hist", lambda bars: 1.)
    with caplog.at_level(logging.DEBUG, logger="vortex.votes"):
        assert vote("BTCUSDT", small, higher, macro=macro) is None
        accepted = vote("BTCUSDT", small, higher, macro=macro,
                        strict_votes=False, min_strong_score=7)
    assert accepted is not None and accepted.side == "LONG"
    assert accepted.votes == ("trend",) and accepted.score >= 7
    assert "STRONG_SINGLE" in accepted.reason
    assert any("trend=LONG" in m for m in caplog.messages)
    assert any("breakout=ABSTAIN" in m for m in caplog.messages)
    assert any("REJECT" in m for m in caplog.messages)


def test_single_vote_does_not_override_opposing_hourly_trend(monkeypatch):
    import vortex.strategies as st
    small = _bars(120, 300000, 0, .2)
    small[-1] = replace(small[-1], volume=240)
    higher = _bars(80, 900000, 40, .3)
    macro_down = _bars(240, 3600000, 231, -.1)
    monkeypatch.setattr(st, "adx", lambda bars, period=14: 30.)
    monkeypatch.setattr(st, "_macd_hist", lambda prices: 1.)
    assert vote("BTCUSDT", small, higher, macro=macro_down,
                strict_votes=False, min_strong_score=7) is None


def test_trailing_atr_at_two_r_locks_one_r_plus_buffer():
    p = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1., 0., 20.,
                 initial_qty=1., initial_risk=2., step=.001,
                 tp1_done=True, tp2_done=True, atr_value=1.)
    assert decide_tick(p, 104.0, atr_value=3., trailing_atr_mult=1.) is None
    assert p.stop >= 102.06
    before = p.stop
    assert decide_tick(p, 103.8, atr_value=.8, trailing_atr_mult=1.) is None
    assert p.stop >= before
    assert trailing_stop(100, 104, 2, 1, 1, "LONG") >= 102


def test_short_atr_trail_and_ohlc_stop_first():
    p = Position("BTCUSDT", "SHORT", 1, 100, 102, 94, 1., 0., 20.,
                 initial_qty=1., initial_risk=2., step=.001,
                 tp1_done=True, tp2_done=True, atr_value=1.)
    decide_tick(p, 95.8, atr_value=1., trailing_atr_mult=1.)
    assert p.stop <= 97.98
    levels = levels_for_bar(p, 91., 105., 99., atr_value=1., trailing_atr_mult=1.)
    assert len(levels) == 1 and levels[0].reason == "stop"


def test_closed_paper_persists_full_training_record_once(tmp_path):
    signal = Signal("BTCUSDT", "LONG", 300000, 100, 98, 106, 7, "strong trend",
                    features={"volume_ratio": 2., "rsi7": 62, "adx14": 31,
                              "atr_pct": .012, "return3": .02, "is_long": 1.},
                    votes=("trend",), atr_value=1.33)
    filt = Filters(.001, .001, 5., .01)
    b = PaperBroker(Settings(data_dir=tmp_path))
    ok, msg = b.open(signal, 99.99, 100.01, filt,
                     {"BTCUSDT": (99.99, 100.01)}, 400000)
    assert ok, msg
    b.mark({"BTCUSDT": (97.8, 97.81)}, 500000, {"BTCUSDT": 1.1})
    rows = [json.loads(x) for x in (tmp_path / "closed_trades.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["approved_votes"] == ["trend"]
    assert row["votes"] == ["trend"] and row["entry_indicators"]["adx14"] == 31
    assert row["initial_stop"] > 0 and row["initial_target"] > 0
    assert row["entry_ts"] == 400000 and row["exit_ts"] == 500000
    assert row["r_multiple"] is not None and row["net_pnl"] < 0
    assert row["y"] == 0
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1


def test_report_metrics_and_json_persist(tmp_path):
    history = [{"ts": i * 300000, "equity": float(e)} for i, e in
               enumerate([1000., 1010., 990., 1030.])]
    trades = [
        {"net_pnl": 10., "r_multiple": 1.},
        {"net_pnl": -5., "r_multiple": -.5},
    ]
    stats = summary(trades, history)
    assert stats["closed_trades"] == 2
    assert stats["win_rate_pct"] == 50
    assert stats["profit_factor"] == 2.
    assert stats["average_r"] == .25
    assert stats["max_drawdown_pct"] > 0
    saved = save_report(tmp_path, "backtest", {"metrics": stats}, symbol="BTCUSDT")
    assert saved.parent.name == "backtests"
    assert json.loads(saved.read_text())["metrics"] == stats


def test_mainnet_aliases_rejected_before_any_testnet_exchange(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "MAINNET-UNKNOWN")
    monkeypatch.setenv("VORTEX_TESTNET_KEY", "TEST")
    monkeypatch.setenv("VORTEX_TESTNET_SECRET", "TEST")
    with pytest.raises(PermissionError):
        TestnetGateway.from_env(armed=True)
    monkeypatch.delenv("BINANCE_API_KEY")
    assert TestnetGateway.from_env().armed is False


def test_testnet_partial_entry_latches_halt_and_preserves_guards(tmp_path):
    from vortex.models import Signal
    from vortex.risk import Filters
    from vortex.testnet_guard import TestnetSupervisor
    class PartialTestnet:
        def __init__(self):
            self.qty = 0
            self.orders = []
            self.entry_count = 0
        def one_way(self):
            return True
        def positions(self):
            return [{"symbol": "BTCUSDT", "positionAmt": str(self.qty)}]
        def request(self, method, path, params=None):
            if path in ("/fapi/v1/openAlgoOrders", "/fapi/v1/openOrders"):
                return self.orders if path.endswith("AlgoOrders") else []
            raise AssertionError(path)
        def symbol_config(self, symbol):
            return {"marginType": "ISOLATED"}
        def set_leverage(self, symbol, x):
            pass
        def market_order(self, symbol, side, qty, cid, reduce_only=False):
            self.entry_count += 1
            self.qty = qty / 2
            return {"status": "PARTIALLY_FILLED", "avgPrice": "100"}
        def position(self, symbol):
            return self.qty
        def protective(self, symbol, side, kind, trigger, cid):
            self.orders.append({"clientAlgoId": cid, "type": kind, "side": side,
                                "triggerPrice": str(trigger), "closePosition": True})
            return {"algoId": len(self.orders)}
        def open_algos(self, symbol):
            return self.orders
    api = PartialTestnet()
    guard = TestnetSupervisor(api, tmp_path / "intent.json")
    sig = Signal("BTCUSDT", "LONG", 0, 100, 98, 106, 7, "entry")
    with pytest.raises(ProtectionError, match="partially filled"):
        guard.enter(sig, .1, Filters(.001, .001, 5, .01), 5)
    assert api.entry_count == 1
    assert guard.state["phase"] == "HALTED"
    assert len(api.orders) == 2
    assert guard.state["entry_id"] and guard.state["stop_id"] and guard.state["take_id"]



def test_two_vote_majority_survives_one_dissent(monkeypatch):
    from vortex.strategies import Derivatives
    import vortex.strategies as st
    small = _bars(120, 300000, 0, .20)
    small[-1] = replace(small[-1], volume=220)
    higher = _bars(80, 900000, 40, .30)
    macro = _bars(240, 3600000, 231, .50)
    monkeypatch.setattr(st, "adx", lambda bars, period=14: 30.)
    monkeypatch.setattr(st, "_macd_hist", lambda prices: 1.)
    current = small[-1].close_ts
    deriv = Derivatives(.002, 2., current)
    accepted = vote("BTCUSDT", small, higher, macro=macro, deriv=deriv)
    assert accepted is not None
    assert accepted.side == "LONG"
    assert set(accepted.votes) == {"trend", "breakout"}


def test_env_voting_and_atr_settings_are_validated(monkeypatch):
    monkeypatch.setenv("STRICT_VOTES", "false")
    monkeypatch.setenv("TRAILING_ATR_MULT", "1.25")
    monkeypatch.setenv("MIN_STRONG_SCORE", "8")
    cfg = Settings.from_env()
    assert cfg.strict_votes is False
    assert cfg.trailing_atr_mult == 1.25
    assert cfg.min_strong_score == 8
    assert cfg.risk_per_trade == .10 and cfg.max_positions == 3
    assert cfg.max_leverage == 5 and cfg.max_daily_loss == .05
    monkeypatch.setenv("STRICT_VOTES", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()
