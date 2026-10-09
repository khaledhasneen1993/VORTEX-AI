"""Single canonical strategy entrypoint; no legacy voting fallback."""

import os

from .phase1_config import StrategyPolicy
from .phase1_strategy import phase1_vote


def analyze(
    symbol,
    candles,
    higher,
    min_score=5,
    *,
    macro=None,
    derivatives=None,
    decision_ms=None,
    minute=None,
    policy=None,
    audit=None,
):
    if audit is None and os.getenv("VORTEX_SIGNAL_AUDIT", "false").lower() == "true":
        from pathlib import Path
        from .measurement import append_decision

        folder = Path(os.getenv("DATA_DIR", "data"))
        audit = lambda row: append_decision(folder, row)
    return phase1_vote(
        symbol,
        candles,
        higher,
        macro=macro,
        deriv=derivatives,
        decision_ms=decision_ms,
        minute=minute,
        min_score=min_score,
        policy=policy or StrategyPolicy(),
        audit=audit,
    )
