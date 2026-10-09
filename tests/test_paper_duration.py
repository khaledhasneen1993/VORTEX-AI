from pathlib import Path

import pytest

from research.paper_hour import session_args


def test_twenty_minute_session_has_separate_output():
    args = session_args(["--duration-seconds", "1200", "--output", "runs/radar-20m"])
    assert args.duration_seconds == 20 * 60
    assert args.output == Path("runs/radar-20m")


def test_hour_workflow_keeps_original_duration_and_artifact_path():
    args = session_args([])
    assert args.duration_seconds == 3600
    assert args.output == Path("runs/radar-one-hour")
    assert args.starting_equity is None


def test_three_hour_session_with_150_dollar_bankroll():
    args = session_args(
        ["--duration-seconds", "10800", "--starting-equity", "150", "--output", "runs/radar-3h-150-01"]
    )
    assert args.duration_seconds == 3 * 60 * 60
    assert args.starting_equity == 150
    assert args.output == Path("runs/radar-3h-150-01")


@pytest.mark.parametrize("equity", ["0", "-150", "nan", "inf"])
def test_invalid_bankroll_rejected(equity):
    with pytest.raises(SystemExit):
        session_args(["--starting-equity", equity])


@pytest.mark.parametrize("seconds", ["0", "-1", "3601"])
def test_unsupported_duration_rejected(seconds):
    with pytest.raises(SystemExit):
        session_args(["--duration-seconds", seconds])
