"""Consolidated release contracts, not strategy performance evidence."""

import os
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
    assert cfg.operations.profile == "default" and cfg.phase1.strict_votes
    assert not cfg.phase1.allow_single_strong_vote and cfg.min_strong_score == 7
    assert not cfg.phase2.aggressive_strong_risk and cfg.phase2.strong_max == 0.15
    assert not cfg.operations.short_loss_cooldown
    assert (cfg.radar_limit, cfg.radar_fast_ranking, cfg.loop_seconds) == (24, False, 20)
    for flag in ("PHASE1_ENABLED", "PHASE2_ENABLED", "OPS_ENABLED"):
        monkeypatch.setenv(flag, "false")
        with pytest.raises(ValueError, match="Only the current"):
            Settings.from_env()
        monkeypatch.delenv(flag)
    monkeypatch.setenv("OPS_PROFILE", "aggressive")
    aggressive = Settings.from_env()
    assert not aggressive.phase1.strict_votes and aggressive.phase1.allow_single_strong_vote
    assert aggressive.min_strong_score == aggressive.phase1.min_strong_score == 6
    assert aggressive.phase2.aggressive_strong_risk and aggressive.phase2.strong_max == 0.18
    assert (aggressive.phase2.normal_min, aggressive.phase2.normal_max) == (0.08, 0.10)
    assert aggressive.operations.short_loss_cooldown
    assert (aggressive.radar_limit, aggressive.radar_fast_ranking, aggressive.loop_seconds) == (30, True, 10)
    assert (aggressive.max_leverage, aggressive.max_margin_fraction) == (5, 0.25)
    monkeypatch.setenv("STRICT_VOTES", "true")
    monkeypatch.setenv("ALLOW_SINGLE_STRONG_VOTE", "false")
    monkeypatch.setenv("MIN_STRONG_SCORE", "8")
    monkeypatch.setenv("PHASE2_AGGRESSIVE_STRONG_RISK", "false")
    monkeypatch.setenv("OPS_SHORT_LOSS_COOLDOWN", "false")
    monkeypatch.setenv("RADAR_LIMIT", "24")
    monkeypatch.setenv("RADAR_FAST_RANKING", "false")
    overridden = Settings.from_env()
    assert overridden.phase1.strict_votes and not overridden.phase1.allow_single_strong_vote
    assert overridden.min_strong_score == 8 and overridden.phase2.strong_max == 0.15
    assert not overridden.operations.short_loss_cooldown and not overridden.radar_fast_ranking
    for name in (
        "STRICT_VOTES",
        "ALLOW_SINGLE_STRONG_VOTE",
        "PHASE2_AGGRESSIVE_STRONG_RISK",
        "OPS_SHORT_LOSS_COOLDOWN",
        "RADAR_FAST_RANKING",
    ):
        previous = os.environ[name]
        monkeypatch.setenv(name, "maybe")
        with pytest.raises(ValueError):
            Settings.from_env()
        monkeypatch.setenv(name, previous)
    monkeypatch.setenv("OPS_PROFILE", "conservative")
    safer = Settings.from_env()
    assert safer.risk_per_trade == 0.08 and safer.max_positions == 2 and safer.max_daily_loss == 0.20


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
    assert values["STRICT_VOTES"] == "false" and folder != "old-state"
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
