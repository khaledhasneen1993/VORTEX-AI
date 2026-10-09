"""Leakage-resistant registry and command builder for chronological research."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_index(month: str) -> int:
    if not MONTH.fullmatch(month):
        raise ValueError(f"Invalid calendar month: {month}")
    year, number = map(int, month.split("-"))
    return year * 12 + number - 1


def validate_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported walk-forward schema")
    periods = manifest.get("periods", {})
    required = ("development", "validation_locked", "secondary_locked",
                "previously_accessed_warmup_not_holdout", "exposed_development")
    if any(name not in periods for name in required):
        raise ValueError("Missing registered period class")
    primary_names = ("development", "validation_locked", "secondary_locked",
                     "exposed_development")
    primary = [(name, month) for name in primary_names for month in periods[name]]
    if any(not MONTH.fullmatch(month) for _, month in primary):
        raise ValueError("All registered periods must use YYYY-MM")
    months = [month for _, month in primary]
    if len(months) != len(set(months)):
        raise ValueError("Primary period classes must not overlap")
    for name in primary_names:
        values = [month_index(month) for month in periods[name]]
        if values != sorted(values):
            raise ValueError(f"{name} must be chronological")
    development = [month_index(x) for x in periods["development"]]
    validation = [month_index(x) for x in periods["validation_locked"]]
    secondary = [month_index(x) for x in periods["secondary_locked"]]
    exposed = [month_index(x) for x in periods["exposed_development"]]
    if not development or not validation or max(development) >= min(validation):
        raise ValueError("Development must end before locked validation")
    if secondary and max(validation) >= min(secondary):
        raise ValueError("Secondary periods must follow locked validation")
    if exposed and secondary and max(secondary) >= min(exposed):
        raise ValueError("Exposed periods must follow secondary periods")
    acceptance = manifest.get("acceptance", {})
    if len(validation) < acceptance.get("minimum_validation_months", 0):
        raise ValueError("Too few locked validation months")
    if manifest.get("validation_access") != "locked_until_candidate_frozen_after_development":
        raise ValueError("Validation access must start locked")
    execution = manifest.get("execution", {})
    if not execution.get("continuous_equity_across_months"):
        raise ValueError("Monthly equity resets cannot establish validation drawdown")
    if execution.get("ambiguous_intrabar_order") != "stop_first":
        raise ValueError("Intrabar ambiguity must remain conservative")


def source_hashes(root: Path) -> dict[str, str]:
    paths = sorted([*root.glob("vortex/*.py"), root / "research/replay.py"])
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in paths}


def replay_command(manifest: dict, phase: str, output: Path, root: Path) -> list[str]:
    validate_manifest(manifest)
    candidate = manifest.get("candidate")
    if not candidate:
        raise ValueError("No candidate is preregistered; returns must remain unread")
    if phase == "development":
        if candidate.get("status") not in {"preregistered", "frozen_after_development"}:
            raise ValueError("Development candidate is not preregistered")
        months = manifest["periods"]["development"]
        cost = 1.0
    elif phase in {"validation", "cost-stress"}:
        if candidate.get("status") != "frozen_after_development":
            raise ValueError("Validation is locked until candidate freeze")
        if not candidate.get("development_result_sha256"):
            raise ValueError("Frozen candidate lacks a development-result hash")
        if candidate.get("source_hashes") != source_hashes(root):
            raise ValueError("Research source changed after candidate freeze")
        months = manifest["periods"]["validation_locked"]
        cost = 2.0 if phase == "cost-stress" else 1.0
    else:
        raise ValueError("Unknown walk-forward phase")
    if output.exists():
        raise ValueError("Never overwrite a saved experiment")
    args = candidate.get("replay_args")
    if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
        raise ValueError("Candidate replay_args must be a list of strings")
    return ["python", "-m", "research.replay", "--month", ",".join(months),
            *args, "--cost-multiplier", str(cost), "--output", str(output)]


def registration_record(path: Path, manifest: dict, root: Path) -> dict:
    validate_manifest(manifest)
    raw = path.read_bytes()
    return {
        "registry_id": manifest["registry_id"],
        "status": "periods_registered_no_candidate_no_returns_read",
        "manifest_sha256": sha256(raw).hexdigest(),
        "periods": manifest["periods"],
        "strategy_trials_on_exposed_september":
            manifest["strategy_trials_on_exposed_september"],
        "source_hashes": source_hashes(root),
        "acceptance": manifest["acceptance"],
        "validation_access": manifest["validation_access"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("research/WALK_FORWARD.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=["register", "development", "validation", "cost-stress"],
                        default="register")
    args = parser.parse_args()
    root = Path.cwd()
    manifest = json.loads(args.manifest.read_text())
    if args.phase == "register":
        if args.output.exists():
            raise ValueError("Never overwrite a saved experiment")
        record = registration_record(args.manifest, manifest, root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record, indent=2))
        return
    print(" ".join(replay_command(manifest, args.phase, args.output, root)))


if __name__ == "__main__":
    main()
