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


def test_interrupted_summary_preserves_observed_evidence_and_marks_stopped(tmp_path):
    import json
    from research.paper_hour import summarize_session

    (tmp_path / "session.log").write_text(
        "INFO ANALYZE BTCUSDT\nPAPER equity=20.00\nCycle failed closed: unavailable\n"
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "paper_state.json").write_text(
        json.dumps({"wallet": 20, "positions": {}, "closed_count": 0})
    )
    report = {}
    summarize_session(report, tmp_path, None, 123, interrupted=True)
    assert report["status"] == "interrupted"
    assert report["duration_completed"] is False
    assert report["elapsed_seconds"] == 123
    assert report["successful_poll_cycles"] == 1
    assert report["cycle_errors"] == 1
    assert report["paper_entries"] == 0
    assert report["final_saved_state"]["wallet"] == 20
    assert json.loads((tmp_path / "progress.json").read_text())["running"] is False


def test_child_gets_graceful_interrupt_before_forced_kill():
    import signal
    import subprocess
    from research.paper_hour import stop_child

    class Child:
        returncode = None
        signals = []
        killed = False

        def poll(self):
            return self.returncode

        def send_signal(self, sig):
            self.signals.append(sig)

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("paper", timeout)
            self.returncode = -9

        def kill(self):
            self.killed = True

    child = Child()
    assert stop_child(child) is True
    assert child.signals == [signal.SIGINT]
    assert child.killed


def test_six_hour_session_has_separate_output():
    args = session_args(["--duration-seconds", "21600", "--starting-equity", "20",
                         "--output", "runs/capture-six-hours"])
    assert args.duration_seconds == 6 * 60 * 60
    assert args.starting_equity == 20
    assert args.output == Path("runs/capture-six-hours")
