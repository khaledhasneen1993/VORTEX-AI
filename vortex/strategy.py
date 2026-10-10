"""Single canonical strategy entrypoint; no legacy voting fallback."""

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
    flow=None,
    capture=False,
):
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
        flow=flow,
        capture=capture,
    )
