"""Assess recorded Phase 0 process evidence, never infer trading profitability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED = ("single-30", "portfolio-30", "single-90", "portfolio-90")


def assess(folder: Path) -> dict:
    issues = []
    try:
        coverage = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        coverage = {}
        issues.append(f"missing/unreadable coverage.json: {type(exc).__name__}")
    expected = coverage.get("expected_files")
    verified = coverage.get("verified_files")
    complete = (
        coverage.get("complete") is True
        and isinstance(expected, int)
        and not isinstance(expected, bool)
        and expected > 0
        and verified == expected
        and coverage.get("missing_count") == 0
        and isinstance(coverage.get("source_sha256"), list)
        and len(coverage["source_sha256"]) == expected
    )
    if not complete:
        issues.append("OHLCV coverage not confirmed from manifest")

    legacy_codes = {}
    legacy_file = folder / "replay-returncodes.txt"
    if legacy_file.is_file():
        for line in legacy_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in {"single", "portfolio"} and value.strip().isdecimal():
                legacy_codes[key.strip()] = int(value.strip())

    attempts = {}
    for name in EXPECTED:
        log = folder / f"{name}.log"
        code_file = folder / f"{name}.exitcode"
        old_key = name.split("-")[0]
        legacy = name.endswith("-90") and old_key in legacy_codes
        if not log.is_file() and legacy:
            log = folder / f"{old_key}.log"
        if not log.is_file() or (not code_file.is_file() and not legacy):
            attempts[name] = {"status": "not_recorded", "exit_code": None}
            issues.append(f"missing recorded attempt: {name}")
            continue
        try:
            raw = code_file.read_text(encoding="ascii").strip() if code_file.is_file() else str(legacy_codes[old_key])
            if not raw.isdecimal():
                raise ValueError("invalid exit code")
            code = int(raw)
            if not 0 <= code <= 255:
                raise ValueError("exit code out of range")
        except (OSError, ValueError):
            attempts[name] = {"status": "invalid_record", "exit_code": None}
            issues.append(f"invalid exit code: {name}")
            continue
        attempts[name] = {"status": "process_exited_zero" if code == 0 else "process_failed", "exit_code": code}
        if code:
            issues.append(f"full-guard replay did not complete: {name} (exit {code})")

    # This process audit cannot certify PnL even if a producer sets a success flag.
    issues.append("economic acceptance requires a separately audited PnL and execution report")
    limitations = coverage.get("unavailable", [])
    if limitations:
        issues.append("missing historical as-of inputs: " + "; ".join(str(x) for x in limitations))
    if coverage.get("filter_snapshot_current_only") is True:
        issues.append("exchange filters not proven historically as-of")

    processes_ok = complete and all(attempts.get(name, {}).get("exit_code") == 0 for name in EXPECTED)
    return {
        "kind": "phase0_process_evidence_not_pnl",
        "source_coverage_complete": complete,
        "expected_files": expected,
        "verified_files": verified,
        "attempts": attempts,
        "process_checks_passed": processes_ok,
        "economic_baseline_accepted": False,
        "issues": issues,
        "pnl": None,
        "profit_factor": None,
        "win_rate": None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true", help="Exit 1 if source or replay-process check failed")
    args = parser.parse_args(argv)
    report = assess(args.root)
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / "phase0_status.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "issues"}, indent=2))
    for issue in report["issues"]:
        print("BLOCKER:", issue)
    return int(args.enforce and not report["process_checks_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
