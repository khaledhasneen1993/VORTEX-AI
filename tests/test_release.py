"""Consolidated release contracts, not strategy performance evidence."""

import pytest
from dotenv import dotenv_values

from vortex.config import Settings
from vortex.configure import configure
from vortex.phase1_config import StrategyPolicy


def test_latest_defaults_and_no_alternative_master_profile(monkeypatch):
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    cfg = Settings.from_env()
    assert cfg.phase1.enabled and cfg.phase2.enabled and cfg.operations.enabled
    assert (cfg.risk_per_trade, cfg.max_positions, cfg.max_daily_loss, cfg.trailing_atr_mult) == (
        0.12,
        4,
        0.55,
        0.8,
    )
    assert cfg.operations.tp1_fraction == cfg.operations.tp2_fraction == 0.3
    assert not cfg.operations.terminal_target and not cfg.operations.telegram_alerts
    for flag in ("PHASE1_ENABLED", "PHASE2_ENABLED", "OPS_ENABLED"):
        monkeypatch.setenv(flag, "false")
        with pytest.raises(ValueError, match="Only the current"):
            Settings.from_env()
        monkeypatch.delenv(flag)


def test_environment_migration_preserves_secrets_and_old_session(tmp_path):
    path = tmp_path / ".env"
    old = tmp_path / "old-state"
    old.mkdir()
    (old / "position.json").write_text("unchanged")
    path.write_text(
        "VORTEX_TELEGRAM_TOKEN='do-not-print'\nSTARTING_EQUITY=150\nSTRICT_VOTES=false\nOPS_ENABLED=false\nDATA_DIR=old-state\n"
    )
    folder = configure(path)
    values = dotenv_values(path)
    assert values["VORTEX_TELEGRAM_TOKEN"] == "do-not-print"
    assert values["STARTING_EQUITY"] == "150" and values["OPS_ENABLED"] == "true"
    assert "STRICT_VOTES" not in values and folder != "old-state"
    assert (old / "position.json").read_text() == "unchanged"
    assert path.stat().st_mode & 0o777 == 0o600
    configure(path, 20)
    assert dotenv_values(path)["STARTING_EQUITY"] == "20"
    with pytest.raises(ValueError):
        configure(path, float("nan"))


def test_no_retired_strategy_or_research_policy_imports():
    import importlib.util

    assert importlib.util.find_spec("vortex.strategies") is None
    assert importlib.util.find_spec("vortex.research_policy") is None


def test_analyze_always_routes_to_current_strategy(monkeypatch):
    from vortex import strategy

    called = {}

    def vote(*args, **kwargs):
        called.update(kwargs)
        return "current"

    monkeypatch.setattr(strategy, "phase1_vote", vote)
    assert strategy.analyze("BTCUSDT", [], []) == "current"
    assert isinstance(called["policy"], StrategyPolicy)
