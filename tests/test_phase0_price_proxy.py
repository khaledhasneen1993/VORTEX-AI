"""Price-only research proxy requires explicit assumptions; no runtime-guard mutation."""
from dataclasses import replace
from pathlib import Path

import pytest

from research import phase0_price_proxy as proxy
from vortex.config import Settings


def test_proxy_config_preserves_canonical_runtime_and_scales_costs():
    original = Settings()
    assert original.operations.funding_guard is True
    assert original.operations.liquidity_guard is True
    base = proxy.proxy_configuration(original)
    stress = proxy.proxy_configuration(original, doubled_costs=True)
    assert original.operations.funding_guard is True
    assert original.operations.liquidity_guard is True
    assert base.operations.funding_guard is False
    assert base.operations.liquidity_guard is False
    assert base.phase1 is original.phase1
    assert base.phase2 is original.phase2
    assert base.risk_per_trade == original.risk_per_trade
    assert base.max_daily_loss == original.max_daily_loss
    assert stress.fee_rate == pytest.approx(2 * original.fee_rate)
    assert stress.operations.cost_multiplier == 2
    assert base.operations.cost_multiplier == original.operations.cost_multiplier
    assert base.operations != original.operations
    with pytest.raises(ValueError, match="preserve"):
        proxy.proxy_configuration(replace(original, operations=replace(original.operations, funding_guard=False)))


def test_measurement_output_is_explicitly_non_executable(tmp_path, monkeypatch):
    (tmp_path / "exchange_info.json").write_text('{"symbols": []}')
    class DummyMarket:
        root = tmp_path
        sources = {}
        def server_ms(self):
            return 1000
        def history(self, symbol, interval, days, now):
            assert symbol == "BTCUSDT" and days == 30 and now == 1000
            return [interval]
        def symbol_filters(self, symbol):
            return {"test": "filters"}
    seen = []
    def standin(symbol, small, higher, filt, cfg, *, macro, minute, execution_observations):
        assert execution_observations is None
        assert cfg.operations.funding_guard is False
        assert cfg.operations.liquidity_guard is False
        seen.append((cfg.fee_rate, cfg.operations.cost_multiplier))
        return {
            "metrics": {"closed_trades": 0, "win_rate_pct": 0.0, "profit_factor": None, "average_r": None},
            "max_drawdown_pct": 0.0, "start_equity": 1000.0, "wallet": 1000.0,
            "equity_with_unrealized": 1000.0,
            "open_position": False, "halted": False, "trades": [],
        }
    monkeypatch.setattr(proxy, "run_single_backtest", standin)
    report = proxy.measure_symbol(DummyMarket(), "BTCUSDT", 30, 1000, Settings())
    assert len(seen) == 2
    assert report["economic_phase0_accepted"] is False
    assert report["valid_real_market_fills"] is None
    assert report["live_guard_configuration_unchanged"] is True
    assert report["scenarios"]["ordinary_modeled_costs"]["closed_trades"] == 0
    assert report["scenarios"]["doubled_modeled_costs"]["profit_factor_model"] is None
    assert "funding" in report["warning"].lower()
    with pytest.raises(ValueError, match="supported"):
        proxy.measure_symbol(DummyMarket(), "BTCUSDT", 27, 1000, Settings())
