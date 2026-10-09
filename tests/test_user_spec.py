from vortex.operations import OperationsPolicy

"""User-requested VORTEX 7-point spec: no public network or signed exchange writes."""
import json

import pytest

from vortex.config import Settings
from vortex.exchange_testnet import TestnetGateway
from vortex.exits import decide_tick, levels_for_bar
from vortex.models import Candle, Position, Signal
from vortex.paper import PaperBroker
from vortex.reports import save_report, summary
from vortex.risk import Filters, trailing_stop
from vortex.testnet_guard import ProtectionError


def _bars(n, step, offset, slope, volume=100):
    out = []
    for i in range(n):
        p = 100.0 + i * slope
        t = (i - offset) * step
        out.append(Candle(t, p - 0.04, p + 0.04, p - 0.1, p, volume, t + step - 1))
    return out


def test_trailing_atr_at_two_r_locks_one_r_plus_buffer():
    p = Position(
        "BTCUSDT",
        "LONG",
        1,
        100,
        98,
        106,
        1.0,
        0.0,
        20.0,
        initial_qty=1.0,
        initial_risk=2.0,
        step=0.001,
        tp1_done=True,
        tp2_done=True,
        atr_value=1.0,
    )
    assert decide_tick(p, 104.0, atr_value=3.0, trailing_atr_mult=1.0) is None
    assert p.stop >= 102.06
    before = p.stop
    assert decide_tick(p, 103.8, atr_value=0.8, trailing_atr_mult=1.0) is None
    assert p.stop >= before
    assert trailing_stop(100, 104, 2, 1, 1, "LONG") >= 102


def test_short_atr_trail_and_ohlc_stop_first():
    p = Position(
        "BTCUSDT",
        "SHORT",
        1,
        100,
        102,
        94,
        1.0,
        0.0,
        20.0,
        initial_qty=1.0,
        initial_risk=2.0,
        step=0.001,
        tp1_done=True,
        tp2_done=True,
        atr_value=1.0,
    )
    decide_tick(p, 95.8, atr_value=1.0, trailing_atr_mult=1.0)
    assert p.stop <= 97.98
    levels = levels_for_bar(p, 91.0, 105.0, 99.0, atr_value=1.0, trailing_atr_mult=1.0)
    assert len(levels) == 1 and levels[0].reason == "stop"


def test_closed_paper_persists_full_training_record_once(tmp_path):
    signal = Signal(
        "BTCUSDT",
        "LONG",
        300000,
        100,
        98,
        106,
        7,
        "strong trend",
        features={
            "volume_ratio": 2.0,
            "rsi7": 62,
            "adx14": 31,
            "atr_pct": 0.012,
            "return3": 0.02,
            "is_long": 1.0,
        },
        votes=("trend",),
        atr_value=1.33,
    )
    filt = Filters(0.001, 0.001, 5.0, 0.01)
    b = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    ok, msg = b.open(signal, 99.99, 100.01, filt, {"BTCUSDT": (99.99, 100.01)}, 400000)
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
    history = [{"ts": i * 300000, "equity": float(e)} for i, e in enumerate([1000.0, 1010.0, 990.0, 1030.0])]
    trades = [{"net_pnl": 10.0, "r_multiple": 1.0}, {"net_pnl": -5.0, "r_multiple": -0.5}]
    stats = summary(trades, history)
    assert stats["closed_trades"] == 2
    assert stats["win_rate_pct"] == 50
    assert stats["profit_factor"] == 2.0
    assert stats["average_r"] == 0.25
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
            self.orders.append(
                {
                    "clientAlgoId": cid,
                    "type": kind,
                    "side": side,
                    "triggerPrice": str(trigger),
                    "closePosition": True,
                }
            )
            return {"algoId": len(self.orders)}

        def open_algos(self, symbol):
            return self.orders

    api = PartialTestnet()
    guard = TestnetSupervisor(api, tmp_path / "intent.json")
    sig = Signal("BTCUSDT", "LONG", 0, 100, 98, 106, 7, "entry")
    with pytest.raises(ProtectionError, match="partially filled"):
        guard.enter(sig, 0.1, Filters(0.001, 0.001, 5, 0.01), 5)
    assert api.entry_count == 1
    assert guard.state["phase"] == "HALTED"
    assert len(api.orders) == 2
    assert guard.state["entry_id"] and guard.state["stop_id"] and guard.state["take_id"]


def test_env_voting_and_atr_settings_are_validated(monkeypatch):
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    monkeypatch.setenv("STRICT_VOTES", "false")
    monkeypatch.setenv("TRAILING_ATR_MULT", "1.25")
    monkeypatch.setenv("MIN_STRONG_SCORE", "8")
    cfg = Settings.from_env()
    assert cfg.trailing_atr_mult == 1.25
    assert cfg.min_strong_score == 8
    assert cfg.risk_per_trade == 0.12 and cfg.max_positions == 4
    assert cfg.max_leverage == 5 and cfg.max_daily_loss == 0.55
    monkeypatch.setenv("OPS_PROFILE", "unknown")
    with pytest.raises(ValueError):
        Settings.from_env()
