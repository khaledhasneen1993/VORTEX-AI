"""Consolidated release contracts, not strategy performance evidence."""

import pytest
from dotenv import dotenv_values

from vortex.config import Settings
from vortex.configure import configure
from vortex.phase1_config import StrategyPolicy


def test_latest_defaults_and_no_alternative_master_profile(monkeypatch):
    from vortex.approved import APPROVED_ENV

    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    for key in APPROVED_ENV:
        monkeypatch.delenv(key, raising=False)
    cfg = Settings.from_env()
    assert cfg.starting_equity == 20
    assert (cfg.max_positions, cfg.max_daily_loss, cfg.max_leverage, cfg.max_margin_fraction) == (
        5,
        0.25,
        5,
        0.25,
    )
    assert cfg.operations.profile == "aggressive" and cfg.operations.short_loss_cooldown
    assert not cfg.phase1.strict_votes and cfg.phase1.allow_single_strong_vote
    assert cfg.min_strong_score == 6 and cfg.phase2.strong_max == 0.18
    assert (cfg.phase2.normal_min, cfg.phase2.normal_max) == (0.08, 0.10)
    assert cfg.phase1.flow_enabled and cfg.phase1.flow_mode == "voter"
    assert cfg.phase1.volume_spike_enabled and not cfg.phase1.regime_enabled
    assert cfg.experiment.enabled and cfg.experiment.capture_enabled and cfg.experiment.average_enabled
    assert (cfg.experiment.profit_margin, cfg.experiment.stop_price, cfg.experiment.account_loss) == (
        0.04,
        0.10,
        0.25,
    )
    assert cfg.runtime.recorder_enabled and cfg.runtime.live_resilience and cfg.runtime.paper_fast_scan
    assert (cfg.radar_limit, cfg.radar_fast_ranking, cfg.loop_seconds) == (30, True, 10)
    for key, value in (
        ("OPS_PROFILE", "conservative"),
        ("RUN_MODE", "testnet"),
        ("USE_AI_MODEL", "true"),
        ("USE_WEBSOCKET", "true"),
        ("PAPER_EXP_ENABLED", "false"),
        ("PHASE1_ENABLED", "false"),
    ):
        monkeypatch.setenv(key, value)
        with pytest.raises(ValueError):
            Settings.from_env()
        monkeypatch.delenv(key)


def test_environment_migration_preserves_secrets_and_old_session(tmp_path):
    path = tmp_path / ".env"
    old = tmp_path / "old-state"
    old.mkdir()
    (old / "position.json").write_text("unchanged")
    path.write_text(
        "VORTEX_TELEGRAM_TOKEN='do-not-print'\nSTARTING_EQUITY=150\nSTRICT_VOTES=false\nOPS_ENABLED=false\nPHASE1_ATR_PCT_MIN=0.02\nDATA_DIR=old-state\n"
    )
    folder = configure(path)
    values = dotenv_values(path)
    assert values["VORTEX_TELEGRAM_TOKEN"] == "do-not-print"
    assert values["STARTING_EQUITY"] == "20" and values["OPS_ENABLED"] == "true"
    assert values["STRICT_VOTES"] == "false" and folder != "old-state"
    assert "PHASE1_ATR_PCT_MIN" not in values
    assert (old / "position.json").read_text() == "unchanged"
    assert path.stat().st_mode & 0o777 == 0o600
    configure(path, 20)
    assert dotenv_values(path)["STARTING_EQUITY"] == "20"
    with pytest.raises(ValueError):
        configure(path, float("nan"))
    from dataclasses import replace
    import json
    from vortex.paper import PaperBroker

    old_cfg = Settings(data_dir=old)
    broker = PaperBroker(old_cfg)
    broker.save()
    saved = json.loads(broker.state_file.read_text())
    saved["operations_policy"]["profile"] = "aggressive"
    saved["operations_policy"].pop("short_loss_cooldown")
    saved["phase2_policy"]["policy"].pop("aggressive_strong_risk")
    saved.pop("opportunity_policy")
    broker.state_file.write_text(json.dumps(saved))
    assert PaperBroker(old_cfg).wallet == broker.wallet
    with pytest.raises(ValueError, match="Entry policy changed"):
        PaperBroker(replace(old_cfg, phase1=replace(old_cfg.phase1, strict_votes=False)))
    for flag in ("flow_enabled", "regime_enabled", "volume_spike_enabled", "liquidity_sweep_enabled"):
        with pytest.raises(ValueError, match="Entry policy changed"):
            PaperBroker(replace(old_cfg, phase1=replace(old_cfg.phase1, **{flag: True})))


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


def test_retired_cli_entry_command_is_not_selectable():
    from vortex.cli import main

    with pytest.raises(SystemExit):
        main(["testnet-once"])
