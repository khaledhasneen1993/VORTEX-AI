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
            decision_ms: int | None = None) -> Signal | None:
    return vote(symbol, candles, higher, macro=macro, deriv=derivatives,
                min_score=min_score)
