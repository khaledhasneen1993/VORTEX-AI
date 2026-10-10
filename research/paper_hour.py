"""One bounded, independently hosted live-data PAPER session; no signed APIs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path

from vortex.binance import Market
from vortex.config import Settings
from vortex.radar import discover


def utc():
    return datetime.now(timezone.utc).isoformat()


def file_digest(path):
    """Bounded-memory hash; a week of observations need not fit in Android RAM."""
    checksum = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def summarize_log(path):
    """Stream persisted log once; do not materialize seven days into RAM."""
    data = {
        "successful_poll_cycles": 0, "cycle_errors": 0,
        "radar_cycles": 0, "paper_entries": 0,
        "last_observed_marked_equity": None,
        "signal_evaluations": 0, "entry_attempts": 0,
        "strategy_rejections": 0, "entry_skips": 0,
        "vote_records": 0, "pyramid_adds": 0,
    }
    matches = (
        ("cycle_errors", "Cycle failed closed:"),
        ("radar_cycles", "RADAR ranked liquid movers:"),
        ("signal_evaluations", " INFO ANALYZE "),
        ("entry_attempts", " INFO SIGNAL "),
        ("strategy_rejections", " DEBUG REJECT "),
        ("entry_skips", " INFO ENTRY_SKIP "),
        ("vote_records", " DEBUG VOTE "),
        ("pyramid_adds", " INFO PYRAMID: "),
    )
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            for key, marker in matches:
                data[key] += line.count(marker)
            if re.search(r"SIGNAL .*accepted=True:", line):
                data["paper_entries"] += 1
            for match in re.finditer(r"PAPER equity=([0-9.]+)", line):
                data["successful_poll_cycles"] += 1
                data["last_observed_marked_equity"] = float(match.group(1))
    return data


def session_args(argv=None):
    def positive_equity(value):
        number = float(value)
        if not isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("Starting equity must be finite and positive")
        return number

    parser = argparse.ArgumentParser(description="Bounded live-data PAPER radar session")
    parser.add_argument("--duration-seconds", type=int, choices=[1200, 3600, 10800, 604800], default=3600)
    parser.add_argument(
        "--starting-equity",
        type=positive_equity,
        default=None,
        help="Fresh PAPER bankroll; default uses existing configuration",
    )
    parser.add_argument("--output", type=Path, default=Path("runs/radar-one-hour"))
    parser.add_argument("--diagnostics", action="store_true", help="Record votes and rejection reasons")
    return parser.parse_args(argv)


def diagnostic_counts(text):
    return {
        "signal_evaluations": text.count(" INFO ANALYZE "),
        "entry_attempts": text.count(" INFO SIGNAL "),
        "strategy_rejections": text.count(" DEBUG REJECT "),
        "entry_skips": text.count(" INFO ENTRY_SKIP "),
        "vote_records": text.count(" DEBUG VOTE "),
        "pyramid_adds": text.count(" INFO PYRAMID: "),
    }


def main(argv=None):
    args = session_args(argv)
    duration = args.duration_seconds
    folder = args.output.resolve()
    if folder.exists():
        raise ValueError("Never restart or overwrite an existing session")
    folder.mkdir(parents=True)
    env = dict(os.environ)
    env.update(
        RUN_MODE="paper",
        USE_RADAR="true",
        USE_WEBSOCKET="false",
        USE_AI_MODEL="false",
        USE_CLAUDE="false",
        USE_MICROSTRUCTURE="false",
        VORTEX_TELEGRAM_TOKEN="",
        VORTEX_TELEGRAM_CHAT_ID="",
        DATA_DIR=str(folder / "state"),
        PYTHONUNBUFFERED="1",
    )
    if args.starting_equity is not None:
        env["STARTING_EQUITY"] = str(args.starting_equity)
    os.environ.update(env)
    if args.diagnostics:
        env["VORTEX_DIAGNOSTICS"] = "true"
    cfg = Settings.from_env()
    config = asdict(cfg)
    config["data_dir"] = str(config["data_dir"])
    report = {
        "requested_seconds": duration,
        "attempt_utc": utc(),
        "mode": "PAPER",
        "actual_exchange_orders": 0,
        "actual_exchange_fills": 0,
        "diagnostics_enabled": env.get("VORTEX_DIAGNOSTICS", "false").lower() == "true",
        "counter_schema_version": 3,
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "commit": os.getenv("GITHUB_SHA")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "config": config,
        "source_sha256": {
            str(p): file_digest(p)
            for p in sorted([*Path("vortex").glob("*.py"), Path(__file__)])
        },
        "limitations": [
            "Displayed REST quotes are conditional simulated fills, not actual executions",
            "Quotes/stops sampled at polling cycles, not continuous tick execution",
            "PAPER broker does not account for funding payments or liquidation",
            "Open positions remain open at the end; no invented closing price",
            "Elapsed duration is not proof of seven-day continuous market coverage or profitability",
        ],
    }
    process = None
    began = None
    try:
        market = Market()
        now = market.server_ms()
        candidates = discover(market, limit=24)
        quotes = market.quotes(now_ms=now)
        if not any(c.symbol in quotes for c in candidates):
            raise ValueError("No fresh quote for any radar candidate")
        report["preflight"] = {
            "server_ms": now,
            "candidates": [asdict(c) for c in candidates],
            "fresh_quote_count": len(quotes),
        }
        report["started_utc"] = utc()
        began = time.monotonic()
        process = subprocess.Popen(
            [sys.executable, "-m", "vortex.cli", "paper"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def collect():
            with (folder / "session.log").open("x") as target:
                for line in process.stdout:
                    target.write(line)
                    target.flush()
                    print(line, end="", flush=True)

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        print(
            "SESSION_STARTED " + json.dumps({"utc": report["started_utc"], "seconds": duration}), flush=True
        )
        progress_every = 30 if duration == 604800 else 1
        next_progress_at = 0.0
        while process.poll() is None and time.monotonic() - began < duration:
            elapsed_so_far = time.monotonic() - began
            if elapsed_so_far >= next_progress_at:
                (folder / "progress.json").write_text(
                    json.dumps(
                        {
                            "utc": utc(),
                            "elapsed_seconds": elapsed_so_far,
                            "pid": process.pid,
                            "running": True,
                        },
                        indent=2,
                    )
                )
                next_progress_at += progress_every
            time.sleep(1)
        elapsed = time.monotonic() - began
        timed_out = elapsed >= duration and process.poll() is None
        if timed_out:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        thread.join(timeout=10)
        report.update(
            elapsed_seconds=elapsed,
            ended_utc=utc(),
            child_returncode=process.returncode,
            duration_completed=timed_out,
        )
        report.update(summarize_log(folder / "session.log"))
        report["status"] = (
            "completed_duration_with_observed_cycles"
            if timed_out and report["successful_poll_cycles"] > 0
            else "failed_no_successful_cycles"
            if timed_out
            else "failed_early"
        )
        state = folder / "state" / "paper_state.json"
        if state.exists():
            report["final_saved_state"] = json.loads(state.read_text())
    except Exception:
        report.update(
            status="failed_preflight" if began is None else "failed_runtime",
            duration_completed=False,
            ended_utc=utc(),
            elapsed_seconds=0 if began is None else time.monotonic() - began,
            error=traceback.format_exc(),
        )
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
    finally:
        report["artifact_sha256"] = {
            str(p.relative_to(folder)): file_digest(p)
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }
        (folder / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "completed_duration_with_observed_cycles" else 1


if __name__ == "__main__":
    sys.exit(main())
