import json
from pathlib import Path

import pytest

from research.replay import parse_months
from research.walk_forward import replay_command, validate_manifest


ROOT = Path(__file__).parents[1]


def manifest():
    return json.loads((ROOT / "research/WALK_FORWARD.json").read_text())


def test_registered_calendar_is_chronological_and_locked():
    validate_manifest(manifest())


def test_continuous_replay_month_parser_refuses_gaps_and_reordering():
    assert parse_months("2026-01,2026-02,2026-03") == ["2026-01", "2026-02", "2026-03"]
    with pytest.raises(ValueError, match="consecutive"):
        parse_months("2026-01,2026-03")
    with pytest.raises(ValueError, match="consecutive"):
        parse_months("2026-02,2026-01")


def test_validation_cannot_be_opened_without_frozen_candidate(tmp_path):
    with pytest.raises(ValueError, match="No candidate|locked until candidate freeze"):
        replay_command(manifest(), "validation", tmp_path / "result.json", ROOT)


def test_source_change_after_freeze_blocks_validation(tmp_path):
    registered = manifest()
    registered["candidate"] = {
        "status": "frozen_after_development",
        "development_result_sha256": "a" * 64,
        "source_hashes": {},
        "replay_args": ["--execution", "1m"],
    }
    with pytest.raises(ValueError, match="source changed"):
        replay_command(registered, "validation", tmp_path / "result.json", ROOT)


def test_development_command_is_one_continuous_calendar_replay(tmp_path):
    registered = manifest()
    registered["candidate"] = {
        "status": "preregistered",
        "replay_args": ["--decision-interval", "15m", "--execution", "1m"],
    }
    command = replay_command(registered, "development", tmp_path / "result.json", ROOT)
    assert command[command.index("--month") + 1] == "2026-01,2026-02,2026-03"
    assert command[command.index("--cost-multiplier") + 1] == "1.0"
