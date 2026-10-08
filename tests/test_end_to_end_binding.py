"""Verify 10% risk configuration is actually used throughout entry/exit paths.

No external Binance calls; all trading adapters are deterministic fakes.
"""
from dataclasses import replace

import pytest
from vortex.binance import MarketError
from vortex.cli import refresh_open_position_atr
from vortex.config import Settings
from vortex.exits import decide_tick
from vortex.models import Candle, Position, Signal
from vortex.risk import Filters, size_trade
from vortex.testnet_stages import maintain
from vortex.testnet_guard import ProtectionError

FILTERS = Filters(.001, .001, 5., .01)


def test_environment_values_are_real_settings_fields(monkeypatch):
    for key, value in {
        "RUN_MODE": "paper", "RISK_PER_TRADE": "0.10",
        "MAX_LEVERAGE": "5", "STRICT_VOTES": "false",
        "MIN_STRONG_SCORE": "7", "TRAILING_ATR_MULT": "1.25",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env()
    assert settings.risk_per_trade == pytest.approx(.10)
    assert settings.max_leverage == 5
    assert settings.strict_votes is False
    assert settings.min_strong_score == 7
    assert settings.trailing_atr_mult == pytest.approx(1.25)
    assert settings.max_positions == 3
    assert settings.max_daily_loss == pytest.approx(.50)
    with pytest.raises(ValueError):
        replace(settings, risk_per_trade=.15)
    with pytest.raises(ValueError):
        replace(settings, mode="live")


def test_short_stop_risk_includes_higher_exit_fee_and_slippage():
    cfg = Settings(risk_per_trade=.10, max_leverage=5)
    signal = Signal("BTCUSDT", "SHORT", 1, 100., 120., 60., 7, "short")
    quantity, margin = size_trade(signal, 1000., cfg, FILTERS)
    entry_cost = 100. * (cfg.fee_rate + cfg.slippage_bps / 10_000)
    stop_exit_cost = 120. * (cfg.fee_rate + cfg.slippage_bps / 10_000)
    assert quantity * (20. + entry_cost + stop_exit_cost) <= 100. + 1e-9
    assert quantity > 0 and margin <= 250.
    assert quantity * 100 <= margin * 5 + 1e-8


def test_terminal_take_profit_closes_remainder_in_one_tick():
    pos = Position("BTCUSDT", "LONG", 1, 100, 98, 106, 1., 0., 20.,
                   initial_qty=1., initial_risk=2., peak=100., step=.001,
                   atr_value=1.33)
    result = decide_tick(pos, 107., atr_value=1., trailing_atr_mult=2.)
    assert result is not None
    assert result.reason == "target" and result.final and result.qty == 1.


class CandlesMarket:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def candles(self, symbol, interval, limit, now_ms):
        self.calls += 1
        if self.fail:
            raise MarketError("public API down")
        assert symbol == "BTCUSDT" and interval == "5m"
        return [
            Candle(i * 300000, 100., 101., 99., 100., 100.,
                   (i+1) * 300000 - 1) for i in range(70)
        ]


def test_open_paper_positions_refresh_completed_atr_before_trailing():
    market = CandlesMarket()
    latest = {"BTCUSDT": .5}
    refreshed = {}
    open_positions = {"BTCUSDT": object()}
    now = 100 * 300000
    refresh_open_position_atr(market, open_positions, "5m", now, latest, refreshed)
    assert latest["BTCUSDT"] == pytest.approx(2.)
    assert market.calls == 1
    refresh_open_position_atr(market, open_positions, "5m", now + 3000, latest, refreshed)
    assert market.calls == 1
    market.fail = True
    refresh_open_position_atr(market, open_positions, "5m", now + 300000, latest, refreshed)
    assert latest["BTCUSDT"] == pytest.approx(2.)
    assert market.calls == 2


def test_guarded_testnet_signal_preserves_atr_and_votes(monkeypatch):
    from vortex import testnet_runner

    now = 20000000
    signal = Signal("BTCUSDT", "LONG", now - 300000, 100., 90., 130.,
                    8, "consensus", features={"adx14": 30.},
                    votes=("trend", "breakout"), atr_value=2.75)

    class FakeAPI:
        def usdt_balance(self):
            return 1000.

    class FakeGuard:
        def __init__(self):
            self.state = {"phase": "IDLE"}
            self.placed = None

        def start_check(self):
            return True

        def persist(self, **values):
            self.state.update(values)

        def enter(self, sig, qty, filt, leverage):
            self.placed = (sig, qty, leverage)
            return {"entry": True}

    class FakeMarket:
        def __init__(self, *, base):
            assert "testnet" in base

        def server_ms(self):
            return now

        def candles(self, symbol, interval, limit, server):
            return [Candle(now - 300000, 100., 101., 99., 100., 100.,
                           now - 1000)]

        def quotes(self, *, now_ms):
            return {"BTCUSDT": (99.99, 100.01)}

        def symbol_filters(self, symbol):
            return FILTERS

    guard = FakeGuard()
    monkeypatch.setenv("VORTEX_TESTNET_ARM", "TESTNET_ONLY")
    monkeypatch.setenv("USE_CLAUDE", "false")
    monkeypatch.setattr(testnet_runner, "prepare", lambda cfg, armed: (FakeAPI(), guard))
    monkeypatch.setattr(testnet_runner, "Market", FakeMarket)
    monkeypatch.setattr(testnet_runner, "analyze", lambda *args, **kwargs: signal)
    out = testnet_runner._once_locked(Settings(), "BTCUSDT", acknowledge=True)
    assert out == {"entry": True}
    delivered, quantity, leverage = guard.placed
    assert delivered.votes == ("trend", "breakout")
    assert delivered.features == {"adx14": 30.}
    assert delivered.atr_value == pytest.approx(2.75)
    assert delivered.entry == pytest.approx(100.01)
    assert quantity > 0 and leverage == 5


def test_testnet_flat_during_stages_latches_halt_instead_of_silent_skip():
    class FakeAPI:
        def position(self, symbol):
            return 0

    class FakeGuard:
        state = {"phase": "PROTECTED", "symbol": "BTCUSDT", "side": "LONG"}
        api = FakeAPI()
        def halt(self, reason):
            raise ProtectionError(reason)

    with pytest.raises(ProtectionError, match="reconciliation"):
        maintain(FakeGuard(), 100., 100.01, atr_value=1., trailing_atr_mult=1.)



def test_testnet_supervisor_rejects_leverage_over_five_before_signed_write(tmp_path):
    from vortex.testnet_guard import TestnetSupervisor

    class NoWrites:
        def symbol_config(self, symbol):
            return {"marginType": "ISOLATED"}
        def market_order(self, *args, **kwargs):
            raise AssertionError("No signed order allowed")

    api = NoWrites()
    supervisor = TestnetSupervisor(api, tmp_path / "intent.json")
    supervisor.start_check = lambda: True
    signal = Signal("BTCUSDT", "LONG", 1, 100., 98., 106., 7, "mock")
    with pytest.raises(ValueError, match="entry parameters"):
        supervisor.enter(signal, 1., FILTERS, 6)
    assert supervisor.state["phase"] == "IDLE"
