"""Optional measurement utilities. No exchange writes or entry authority."""

import json
import os

from .locks import ProcessLock
from .reports import summary

VOTERS = ("trend", "breakout", "reversion", "funding_fade")


def append_decision(folder, row):
    """Dedicated flock protects complete JSONL records; write errors propagate."""
    with ProcessLock(folder / "signal-audit.lock"):
        with (folder / "signals.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())


def voter_attribution(trades):
    """Overlapping trade cohorts are descriptive, never a causal ablation result."""
    result = {}
    for voter in VOTERS:
        cohort = [row for row in trades if voter in row.get("votes", ())]
        stats = summary(cohort, [])
        result[voter] = {
            "closed_trades": len(cohort),
            "win_rate_pct": stats["win_rate_pct"] if cohort else None,
            "profit_factor": stats["profit_factor"],
            "average_r": stats["average_r"],
            "marginal_contribution": None,
            "marginal_status": "requires_paired_leave_one_voter_out_replay",
            "low_sample_warning": len(cohort) < 100,
            "cohorts_overlap": True,
        }
    return result
