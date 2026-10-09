"""Record the four requested historical commands, including failures, without strategy changes.

This is an attempt recorder, NOT a complete baseline/shadow/ablation pipeline.
Missing historical funding/depth inputs must not be disabled implicitly.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from vortex.locks import ProcessLock


def collect(output, reference_commit, timeout_seconds=120, *, executor=subprocess.run):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    sources = sorted(root.glob("vortex/*.py")) + [Path(__file__).resolve()]
    report = {
        "reference_commit": reference_commit,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "attempts_only",
        "economic_validation": False,
        "source_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        "cost_requirements": {
            "taker_fee_rate": 0.0005,
            "maker_fee_rate": 0.0002,
            "maker_execution_used": False,
            "note": "Market fills require taker fees. Current slippage lacks volume scaling; full-profile replay requires as-of depth/funding and derivative observations.",
        },
        "attempts": [],
        "remaining": [
            "Real continuous market sources and hashes for both spans",
            "Identical frozen cutoff and correct warmup exclusion in both engines",
            "As-of funding/OI/mark/depth observations (never future settlements as signal inputs)",
            "Funding settlement in the single-symbol engine and volume-scaled costs",
            "Independent forward shadow outcomes for accepted and rejected candidates",
            "Paired leave-one-voter-out replay for marginal contribution",
            "Historical Radar membership: fixed six-symbol CLI portfolio is not the 24-symbol Radar",
        ],
    }
    with ProcessLock(output / "measurement.lock"):
        for days in (30, 90):
            for command in ("backtest", "portfolio-backtest"):
                label = f"{command}-{days}d"
                argv = [sys.executable, "-m", "vortex.cli", command, "--days", str(days)]
                env = dict(os.environ)
                env.update(
                    RUN_MODE="backtest",
                    FEE_RATE="0.0005",
                    VORTEX_EXTENDED_HISTORY="true",
                    VORTEX_SIGNAL_AUDIT="true",
                    USE_AI_MODEL="false",
                    USE_CLAUDE="false",
                    OPS_TELEGRAM_ALERTS="false",
                    DATA_DIR=str(output.resolve() / label / "state"),
                )
                row = {
                    "command": ["vortex", command, "--days", str(days)],
                    "actual_argv": argv,
                    "requested_days": days,
                    "started_utc": datetime.now(timezone.utc).isoformat(),
                    "metrics": None,
                    "attribution": None,
                    "loaded_market_period": None,
                }
                try:
                    result = executor(
                        argv,
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                        check=False,
                    )
                    text = result.stdout + result.stderr
                    row.update(
                        returncode=result.returncode,
                        status="command_returned_success_requires_audit"
                        if result.returncode == 0
                        else "failed",
                    )
                except subprocess.TimeoutExpired:
                    text = "Command exceeded bounded timeout; child terminated. No performance report accepted.\n"
                    row.update(returncode=None, status="timeout")
                log_path = output / (label + ".log")
                log_path.write_text(text, encoding="utf-8")
                row.update(
                    ended_utc=datetime.now(timezone.utc).isoformat(),
                    log=log_path.name,
                    log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
                )
                report["attempts"].append(row)
                (output / "attempts.json").write_text(json.dumps(report, indent=2, allow_nan=False))
                print(label, row["status"], "returncode=" + str(row["returncode"]), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-commit", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 600:
        parser.error("timeout must be 1..600 seconds per command")
    collect(args.output, args.reference_commit, args.timeout_seconds)


if __name__ == "__main__":
    main()
