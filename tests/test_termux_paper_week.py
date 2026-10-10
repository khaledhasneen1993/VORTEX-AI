"""PAPER-only Termux week runner contracts; all fixtures are synthetic."""
import hashlib

import pytest

from research.paper_hour import file_digest, session_args, summarize_log


def test_week_duration_is_explicit_opt_in_and_default_unchanged():
    default = session_args([])
    assert default.duration_seconds == 3600
    week = session_args(["--duration-seconds", "604800", "--starting-equity", "20"])
    assert week.duration_seconds == 604800
    assert week.starting_equity == 20
    with pytest.raises(SystemExit):
        session_args(["--duration-seconds", "604801"])
    with pytest.raises(SystemExit):
        session_args(["--starting-equity", "-1"])


def test_week_streamed_log_report_never_invents_trades(tmp_path):
    logfile = tmp_path / "session.log"
    logfile.write_text(
        "2026-10-10 00:00:00 INFO PAPER equity=20.00\n"
        "2026-10-10 00:00:01 INFO RADAR ranked liquid movers:\n"
        "2026-10-10 00:00:02 DEBUG REJECT BTCUSDT reason=too_few_votes\n"
        "2026-10-10 00:00:03 INFO SIGNAL BTCUSDT accepted=True: LONG\n"
        "2026-10-10 00:00:04 INFO ENTRY_SKIP ETHUSDT insufficient_depth\n"
        "2026-10-10 00:00:05 WARNING Cycle failed closed: HTTP 451\n"
        "2026-10-10 00:00:06 INFO PAPER equity=20.25\n"
    )
    report = summarize_log(logfile)
    assert report["successful_poll_cycles"] == 2
    assert report["last_observed_marked_equity"] == 20.25
    assert report["cycle_errors"] == 1
    assert report["radar_cycles"] == 1
    assert report["paper_entries"] == 1
    assert report["strategy_rejections"] == 1
    assert report["entry_skips"] == 1
    assert "net_pnl" not in report and "profit_factor" not in report
    assert file_digest(logfile) == hashlib.sha256(logfile.read_bytes()).hexdigest()
