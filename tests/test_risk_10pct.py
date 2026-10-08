"""Regression tests for 10% risk-budget configuration (PAPER / Backtest / Testnet only)."""
from dataclasses import replace

import pytest

from vortex.config import Settings
from vortex.exits import decide_tick
from vortex.models import Position, Signal
from vortex.risk import Filters, RiskGate, size_trade, trailing_stop


F = Filters(step=0.001, min_qty=0.001, min_notional=5, tick=0.01)


def test_environment_defaults_and_all_controls(monkeypatch):
    for key in ("RISK_PER_TRADE", "MAX_LEVERAGE", "STRICT_VOTES",
                "MIN_STRONG_SCORE", "TRAILING_ATR_MULT"):
        monkeypatch.delenv(key, raising=False)
    defaults = Settings.from_env()
    assert defaults.risk_per_trade == pytest.approx(0.10)
    assert defaults.max_leverage == 5
    assert defaults.strict_votes is True
    assert defaults.min_strong_score == 7
    assert defaults.trailing_atr_mult == 1.0
    assert defaults.max_positions == 3
    assert defaults.max_margin_fraction == pytest.approx(0.25)
    assert defaults.max_daily_loss == pytest.approx(0.50)
    assert defaults.max_consecutive_losses == 5

    monkeypatch.setenv("RISK_PER_TRADE", "0.10")
    monkeypatch.setenv("MAX_LEVERAGE", "5")
    monkeypatch.setenv("STRICT_VOTES", "false")
    monkeypatch.setenv("MIN_STRONG_SCORE", "3")
    monkeypatch.setenv("TRAILING_ATR_MULT", "2.5")
    cfg = Settings.from_env()
    assert (cfg.risk_per_trade, cfg.max_leverage, cfg.strict_votes,
            cfg.min_strong_score, cfg.trailing_atr_mult) == (0.10, 5, False, 3, 2.5)


@pytest.mark.parametrize("risk,good", [
    (0.00001, True), (0.10, True), (0.1000001, False),
    (0, False), (-0.02, False), (float("nan"), False),
])
def test_risk_bounds(risk, good):
    if good:
        assert Settings(risk_per_trade=risk).risk_per_trade == risk
    else:
        with pytest.raises(ValueError):
            Settings(risk_per_trade=risk)


@pytest.mark.parametrize("score,good", [(3, True), (7, True), (10, True), (2, False), (11, False)])
def test_strong_score_bounds(score, good):
    if good:
        Settings(min_strong_score=score)
    else:
        with pytest.raises(ValueError):
            Settings(min_strong_score=score)


@pytest.mark.parametrize("mult,good", [
    (0.5, True), (1.0, True), (3.0, True), (0.49, False),
    (3.01, False), (float("inf"), False),
])
def test_trailing_multiplier_bounds(mult, good):
    if good:
        Settings(trailing_atr_mult=mult)
    else:
        with pytest.raises(ValueError):
            Settings(trailing_atr_mult=mult)


def test_no_live_and_bounded_leverage():
    with pytest.raises(ValueError):
        Settings(mode="live")
    with pytest.raises(ValueError):
        Settings(mode="testnet")  # signed TESTNET uses a separately armed gateway
    Settings(max_leverage=1)
    Settings(max_leverage=10)
    with pytest.raises(ValueError):
        Settings(max_leverage=11)


def test_true_ten_percent_risk_budget_including_round_trip_costs():
    cfg = Settings(risk_per_trade=.10, max_leverage=5)
    sig = Signal("BTCUSDT", "LONG", 123, 100, 80, 140, 7, "test")
    qty, margin = size_trade(sig, 1000, cfg, F)
    worst_loss = qty * ((sig.entry - sig.stop)
                        + sig.entry * (2 * cfg.fee_rate + 2 * cfg.slippage_bps / 10000))
    assert qty > 0 and 95 <= worst_loss <= 100 + 1e-6
    assert margin <= 250 + 1e-6
    assert qty * sig.entry <= margin * 5 + 1e-6


def test_margin_cap_dominates_without_forcing_full_ten_percent_loss():
    cfg = Settings(risk_per_trade=.10, max_leverage=5, max_margin_fraction=.25)
    sig = Signal("BTCUSDT", "LONG", 123, 100, 98, 140, 7, "test")
    qty, margin = size_trade(sig, 1000, cfg, F)
    assert qty == pytest.approx(12.5)
    assert margin == pytest.approx(250)
    assert qty * 2.16 < 100  # 10% is a ceiling; don't increase to "use" it
    second = size_trade(sig, 1000, cfg, F, committed_margin=200)
    assert second is not None
    assert second[1] <= 50 + 1e-8


def test_daily_stop_and_consecutive_losses_preserved():
    cfg = Settings()
    gate = RiskGate(cfg, 1000)
    assert gate.can_open(501, 0)[0]
    assert not gate.can_open(500, 0)[0]
    assert gate.blocked
    second = RiskGate(cfg, 1000)
    for _ in range(5):
        second.closed(-1)
    assert not second.can_open(1000, 0)[0]


def test_two_r_atr_trailing_never_widens():
    p = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1, 0, 20,
                 initial_qty=1, initial_risk=2, tp1_done=True, tp2_done=True,
                 step=.001, atr_value=1)
    assert decide_tick(p, 104, atr_value=1.5, trailing_atr_mult=2.5) is None
    assert p.stop >= 102 + .02 * 1.5
    old = p.stop
    decide_tick(p, 104.1, atr_value=3, trailing_atr_mult=3)
    assert p.stop >= old
    assert trailing_stop(100, 104, 2, 1, 1, "LONG") >= 102



def test_risk_gates_cannot_be_relaxed_through_environment(monkeypatch):
    with pytest.raises(ValueError):
        Settings(max_positions=4)
    with pytest.raises(ValueError):
        Settings(max_margin_fraction=.251)
    with pytest.raises(ValueError):
        Settings(max_daily_loss=.501)
    with pytest.raises(ValueError):
        Settings(max_consecutive_losses=6)


def test_max_leverage_setting_ten_never_increases_trade_above_five_x():
    sig = Signal("BTCUSDT", "LONG", 123, 100, 98, 140, 7, "test")
    cfg = Settings(risk_per_trade=.10, max_leverage=10)
    order = size_trade(sig, 1000, cfg, F)
    assert order is not None
    qty, margin = order
    assert qty == pytest.approx(12.5)
    assert margin == pytest.approx(250)
    assert qty * sig.entry <= 5 * margin + 1e-8


def test_no_martingale_and_margin_reduces_additional_trade_size():
    sig = Signal("BTCUSDT", "LONG", 123, 100, 98, 140, 7, "test")
    cfg = Settings()
    first = size_trade(sig, 1000, cfg, F, committed_margin=0)
    constrained = size_trade(sig, 1000, cfg, F, committed_margin=230)
    assert first is not None and constrained is not None
    assert constrained[0] < first[0]
    assert constrained[1] <= 20 + 1e-8
    assert size_trade(sig, 1000, cfg, F, committed_margin=250) is None



def test_daily_loss_fifty_percent_env_threshold_and_latch(monkeypatch):
    from vortex.config import Settings
    from vortex.risk import RiskGate
    monkeypatch.setenv("MAX_DAILY_LOSS", "0.50")
    cfg = Settings.from_env()
    assert cfg.max_daily_loss == pytest.approx(.50)
    gate = RiskGate(cfg, 1000.)
    assert gate.can_open(501., 0) == (True, "ok")
    assert gate.can_open(500., 0) == (False, "daily loss circuit breaker")
    assert not gate.can_open(1000., 0)[0]  # halt stays latched
    with pytest.raises(ValueError, match="Daily loss"):
        Settings(max_daily_loss=.501)
    with pytest.raises(ValueError, match="Daily loss"):
        Settings(max_daily_loss=0)
