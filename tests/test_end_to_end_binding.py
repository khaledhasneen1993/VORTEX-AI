from vortex.operations import OperationsPolicy

"Verify 10% risk configuration is actually used throughout entry/exit paths.\n\nNo external Binance calls; all trading adapters are deterministic fakes.\n"
from dataclasses import replace

import pytest

from vortex.binance import MarketError
from vortex.cli import refresh_open_position_atr
from vortex.config import Settings
from vortex.exits import decide_tick
from vortex.models import Candle, Position, Signal
from vortex.risk import Filters, size_trade
from vortex.testnet_guard import ProtectionError
from vortex.testnet_stages import maintain

FILTERS = Filters(0.001, 0.001, 5.0, 0.01)


def test_environment_values_are_real_settings_fields(monkeypatch):
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    for key, value in {
        "RUN_MODE": "paper",
        "RISK_PER_TRADE": "0.10",
        "MAX_LEVERAGE": "5",
        "STRICT_VOTES": "false",
        "MIN_STRONG_SCORE": "7",
        "TRAILING_ATR_MULT": "1.25",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env()
    assert settings.risk_per_trade == pytest.approx(0.1)
    assert settings.max_leverage == 5
    assert settings.min_strong_score == 7
    assert settings.trailing_atr_mult == pytest.approx(1.25)
    assert settings.max_positions == 4
    assert settings.max_daily_loss == pytest.approx(0.55)
    with pytest.raises(ValueError):
        replace(settings, risk_per_trade=0.16)
    with pytest.raises(ValueError):
        replace(settings, mode="live")


def test_short_stop_risk_includes_higher_exit_fee_and_slippage():
    cfg = Settings(
        risk_per_trade=0.1,
        max_leverage=5,
        operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
    )
    signal = Signal("BTCUSDT", "SHORT", 1, 100.0, 120.0, 60.0, 7, "short")
    quantity, margin = size_trade(signal, 1000.0, cfg, FILTERS)
    entry_cost = 100.0 * (cfg.fee_rate + cfg.slippage_bps / 10000)
    stop_exit_cost = 120.0 * (cfg.fee_rate + cfg.slippage_bps / 10000)
    assert quantity * (20.0 + entry_cost + stop_exit_cost) <= 100.0 + 1e-09
    assert quantity > 0 and margin <= 250.0
    assert quantity * 100 <= margin * 5 + 1e-08


def test_terminal_take_profit_closes_remainder_in_one_tick():
    pos = Position(
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
        peak=100.0,
        step=0.001,
        atr_value=1.33,
    )
    result = decide_tick(
        pos, 107.0, atr_value=1.0, trailing_atr_mult=2.0, policy=OperationsPolicy(terminal_target=True)
    )
    assert result is not None
    assert result.reason == "target" and result.final and (result.qty == 1.0)


class CandlesMarket:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def candles(self, symbol, interval, limit, now_ms):
        self.calls += 1
        if self.fail:
            raise MarketError("public API down")
        assert symbol == "BTCUSDT" and interval == "5m"
        return [Candle(i * 300000, 100.0, 101.0, 99.0, 100.0, 100.0, (i + 1) * 300000 - 1) for i in range(70)]


def test_open_paper_positions_refresh_completed_atr_before_trailing():
    market = CandlesMarket()
    latest = {"BTCUSDT": 0.5}
    refreshed = {}
    open_positions = {"BTCUSDT": object()}
    now = 100 * 300000
    refresh_open_position_atr(market, open_positions, "5m", now, latest, refreshed)
    assert latest["BTCUSDT"] == pytest.approx(2.0)
    assert market.calls == 1
    refresh_open_position_atr(market, open_positions, "5m", now + 3000, latest, refreshed)
    assert market.calls == 1
    market.fail = True
    refresh_open_position_atr(market, open_positions, "5m", now + 300000, latest, refreshed)
    assert latest["BTCUSDT"] == pytest.approx(2.0)
    assert market.calls == 2


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
        maintain(FakeGuard(), 100.0, 100.01, atr_value=1.0, trailing_atr_mult=1.0)


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
    signal = Signal("BTCUSDT", "LONG", 1, 100.0, 98.0, 106.0, 7, "mock")
    with pytest.raises(ValueError, match="entry parameters"):
        supervisor.enter(signal, 1.0, FILTERS, 6)
    assert supervisor.state["phase"] == "IDLE"
