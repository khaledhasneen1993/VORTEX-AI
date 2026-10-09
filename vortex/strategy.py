"""Canonical VORTEX strategy entrypoint: 4 strategies, at least 2 agree.

The optional hourly macro history and funding/OI must be truly observed and
fully completed at the decision time. Unknown derivatives abstain, never guess.
"""
from __future__ import annotations
from .models import Candle, Signal
from .strategies import Derivatives, vote


def analyze(symbol: str, candles: list[Candle], higher: list[Candle],
            min_score: int = 5, *,
            macro: list[Candle] | None = None,
            derivatives: Derivatives | None = None,
            decision_ms: int | None = None,
            minute: list[Candle] | None = None,
            strict_votes: bool = True, min_strong_score: int = 7, policy=None) -> Signal | None:
    if policy is not None and policy.enabled:
        from .phase1_strategy import phase1_vote
        return phase1_vote(symbol, candles, higher, macro=macro, deriv=derivatives,
                           decision_ms=decision_ms, minute=minute, min_score=min_score,
                           policy=policy)
    return vote(symbol, candles, higher, macro=macro, deriv=derivatives,
                min_score=min_score, decision_ms=decision_ms, minute=minute,
                strict_votes=strict_votes, min_strong_score=min_strong_score)
