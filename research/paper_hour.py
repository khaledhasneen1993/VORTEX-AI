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


def session_args(argv=None):
    def positive_equity(value):
        number = float(value)
        if not isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("Starting equity must be finite and positive")
        return number

    parser = argparse.ArgumentParser(description="Bounded live-data PAPER radar session")
    parser.add_argument("--duration-seconds", type=int, choices=[1200, 3600, 10800], default=3600)
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
        "counter_schema_version": 2,
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "commit": os.getenv("GITHUB_SHA")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "config": config,
        "source_sha256": {
            str(p): sha256(p.read_bytes()).hexdigest()
            for p in sorted([*Path("vortex").glob("*.py"), Path(__file__)])
        },
        "limitations": [
            "Displayed REST quotes are conditional simulated fills, not actual executions",
            "Quotes/stops sampled at polling cycles, not continuous tick execution",
            "PAPER broker does not account for funding payments or liquidation",
            "Open positions remain open at the end; no invented closing price",
            "This short session cannot establish profitability or fulfill the seven-day forward gate",
        ],
    }
    process = None
    began = None
    try:
        market = Market()
        now = market.server_ms()
        candidates = discover(market, limit=cfg.radar_limit, fast_ranking=cfg.radar_fast_ranking)
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
        while process.poll() is None and time.monotonic() - began < duration:
            (folder / "progress.json").write_text(
                json.dumps(
                    {
                        "utc": utc(),
                        "elapsed_seconds": time.monotonic() - began,
                        "pid": process.pid,
                        "running": True,
                    },
                    indent=2,
                )
            )
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
        text = (folder / "session.log").read_text()
        equities = [float(x) for x in re.findall(r"PAPER equity=([0-9.]+)", text)]
        report.update(
            successful_poll_cycles=len(equities),
            cycle_errors=text.count("Cycle failed closed:"),
            radar_cycles=text.count("RADAR ranked liquid movers:"),
            paper_entries=len(re.findall(r"SIGNAL .*accepted=True:", text)),
            last_observed_marked_equity=equities[-1] if equities else None,
        )
        report.update(diagnostic_counts(text))
        report["status"] = (
            "completed_duration"
            if timed_out and equities
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
            str(p.relative_to(folder)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }
        (folder / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "completed_duration" else 1


if __name__ == "__main__":
    sys.exit(main())
