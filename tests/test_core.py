"""Deterministic unit regression tests: no API credentials and no internet."""
import json
import math
from dataclasses import replace
import pytest
from vortex.config import Settings
from vortex.models import Candle, Signal
from vortex.risk import Filters, RiskGate, floor_step, size_trade
from vortex.paper import PaperBroker
from vortex.indicators import ema, rsi, atr, adx
from vortex.strategy import analyze
from vortex.backtest import run
from vortex.binance import Market, MarketError


FILTER = Filters(step=0.001, min_qty=0.001, min_notional=5, tick=0.01)
SIG = Signal("BTCUSDT", "LONG", 300000, 100, 98, 103, 6, "test")


def test_live_and_excessive_risk_rejected():
    for mode in ("live", "testnet", "real"):
        with pytest.raises(ValueError):
            Settings(mode=mode)
    with pytest.raises(ValueError):
        Settings(risk_per_trade=0.25)
    with pytest.raises(ValueError):
        Settings(max_leverage=100)


def test_floor_precision_and_size():
    assert floor_step(1.999, 0.01) == 1.99
    assert floor_step(0.0059, 0.001) == 0.005
    cfg = Settings()
    qty, margin = size_trade(SIG, 1000, cfg, FILTER)
    assert qty > 0
    assert margin <= 1000 * cfg.max_margin_fraction
    estimated_loss = qty * (2 + 100 * (2 * cfg.fee_rate + 2 * cfg.slippage_bps / 10000))
    assert estimated_loss <= cfg.risk_per_trade * 1000 + 0.000001


def test_small_account_does_not_increase_order_above_risk():
    assert size_trade(SIG, 1, Settings(starting_equity=1), FILTER) is None


def test_bad_stop_and_margin_rejected():
    bad = replace(SIG, stop=SIG.entry)
    assert size_trade(bad, 100, Settings(), FILTER) is None
    assert size_trade(SIG, 100, Settings(), FILTER, committed_margin=100) is None


def test_consecutive_losses_never_halt_entries():
    gate = RiskGate(Settings(), 100)
    for count in range(1, 11):
        gate.closed(-1)
        assert gate.consecutive_losses == count
        assert gate.can_open(100, 0) == (True, "ok")
    gate.closed(1)
    assert gate.consecutive_losses == 0
    assert gate.can_open(100, 0)[0]


def test_gate_daily_drawdown_halts():
    gate = RiskGate(Settings(max_daily_loss=0.50), 1000)
    assert gate.can_open(501, 0)[0]
    assert gate.can_open(500, 0) == (False, "daily loss circuit breaker")
    gate.new_day("2099-01-01", 1100)
    assert not gate.can_open(1100, 0)[0]  # halt stays latched


def test_no_duplicate_signals_or_reset_balance(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    p = PaperBroker(cfg)
    ok, _ = p.open(SIG, 99.99, 100.01, FILTER, {"BTCUSDT": (99.99, 100.01)}, 500000)
    assert ok
    assert len(p.positions) == 1
    assert p.wallet < 1000
    p2 = PaperBroker(cfg)
    assert p2.wallet == p.wallet
    assert "BTCUSDT" in p2.positions
    ok, _ = p2.open(SIG, 99.99, 100.01, FILTER, {"BTCUSDT": (99.99, 100.01)}, 500001)
    assert not ok
    exits = p2.mark({"BTCUSDT": (97.8, 97.81)}, 600000)
    assert len(exits) == 1 and exits[0]["net_pnl"] < 0
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    p3 = PaperBroker(cfg)
    assert not p3.positions
    assert p3.closed_count == 1
    assert p3.gate.consecutive_losses == 1


def test_wide_spread_does_not_trade(tmp_path):
    broker = PaperBroker(Settings(data_dir=tmp_path))
    ok, reason = broker.open(SIG, 99, 100, FILTER, {"BTCUSDT": (99, 100)}, 500000)
    assert not ok and "spread" in reason


def test_missing_open_position_quote_fail_closed(tmp_path):
    broker = PaperBroker(Settings(data_dir=tmp_path))
    broker.open(SIG, 99.99, 100.01, FILTER, {"BTCUSDT": (99.99, 100.01)}, 500000)
    with pytest.raises(ValueError):
        broker.equity({})


def test_market_is_public_only():
    m = Market()
    with pytest.raises(MarketError):
        m.get("/fapi/v1/order")


def test_exchange_filters_market_lot_fallback():
    info = {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.01"},
                        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0", "minQty": "0"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"}]}
    f = Filters.from_exchange(info)
    assert f.step == 0.001
    assert f.min_qty == 0.01


def fake_candles(n=80, step=300000):
    return [Candle(i * step, 100, 102, 98, 100, 100, i * step + step - 1) for i in range(n)]


def test_indicators_flat_market():
    candles = fake_candles(75)
    assert math.isclose(ema([100.] * 50, 21), 100)
    assert rsi([100.] * 30) == 50
    assert math.isclose(atr(candles, 14), 4)
    assert adx(candles, 14) == 0


def test_reject_future_higher_timeframe():
    bars = fake_candles(80)
    htf = fake_candles(36, 900000)  # last 15m candle is in the future
    assert analyze("BTCUSDT", bars, htf) is None


def test_backtest_next_open_and_stop_wins_tie(monkeypatch):
    bars = fake_candles(72)
    # Every bar's high > target and low < stop: stop must have priority.
    import vortex.backtest as backtest_module
    monkeypatch.setattr(backtest_module, "analyze",
                        lambda sym, history, upper, min_score: (
                            Signal(sym, "LONG", history[-1].ts, 100, 99, 101, 7, "test")
                            if len(history) == 66 else None))
    report = run("BTCUSDT", bars, [], FILTER, Settings())
    assert report["closed_trades"] == 1
    trade = report["trades"][0]
    assert trade["open_ts"] == bars[66].ts
    assert trade["close_ts"] == bars[66].ts
    assert trade["reason"] == "stop"
    assert trade["net_pnl"] < 0


def test_no_profits_invented_for_empty_sample():
    report = run("BTCUSDT", fake_candles(10), [], FILTER, Settings())
    assert report["closed_trades"] == 0
    assert report["wallet"] == 1000
    assert report["win_rate_pct"] == 0


def test_corrupted_state_fails_instead_of_resetting(tmp_path):
    (tmp_path / "paper_state.json").write_text('{"broken":true}', encoding="utf-8")
    with pytest.raises(ValueError):
        PaperBroker(Settings(data_dir=tmp_path))


def test_explicit_risk_reset_keeps_daily_loss_floor(tmp_path):
    broker = PaperBroker(Settings(data_dir=tmp_path))
    broker.gate.blocked = True
    broker.gate.consecutive_losses = 4
    broker.gate.day_start_equity = 1000
    broker.wallet = 490
    broker.save()
    with pytest.raises(ValueError):
        broker.reset_halt(False)
    broker.reset_halt(True)
    reloaded = PaperBroker(Settings(data_dir=tmp_path))
    assert reloaded.wallet == 490
    assert not reloaded.gate.can_open(490, 0)[0]


def test_dashboard_requires_local_port():
    from vortex.dashboard import serve
    with pytest.raises(ValueError):
        serve(Settings(), port=80)


def test_history_rejects_invalid_span():
    m = Market()
    m._exchange = {"BTCUSDT": {}}
    with pytest.raises(MarketError):
        m.history("BTCUSDT", "5m", 99, 9999999)
