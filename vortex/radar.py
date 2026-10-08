"""Transparent broad-market ranking inspired by StrikeChart's scanner.

Scores use *observed* Binance 24h change/turnover only. This is a candidate
discovery stage, not a trading signal and not a claim of whale detection.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite, log10


@dataclass(frozen=True)
class Candidate:
    symbol: str
    score: float
    turnover_usdt: float
    change_24h_pct: float


def rank(exchange: dict, rows: list[dict], *, limit: int = 12,
         min_turnover_usdt: float = 20_000_000) -> list[Candidate]:
    if not 1 <= limit <= 30:
        raise ValueError("Radar limit outside audited quota")
    results: list[Candidate] = []
    for raw in rows:
        try:
            sym = raw["symbol"]
            if sym not in exchange:
                continue
            volume = float(raw["quoteVolume"])
            change = float(raw["priceChangePercent"])
            if not isfinite(volume) or not isfinite(change) or volume < min_turnover_usdt:
                continue
            # Avoid limitless score from one extreme mover, use log turnover.
            score = round(log10(max(volume, 1)) + min(abs(change), 35.0) * .2, 4)
            results.append(Candidate(sym, score, volume, change))
        except (KeyError, TypeError, ValueError):
            continue
    results.sort(key=lambda c: (-c.score, -c.turnover_usdt, c.symbol))
    return results[:limit]


def discover(market, *, limit: int = 12) -> list[Candidate]:
    rows = market.get("/fapi/v1/ticker/24hr")
    if not isinstance(rows, list):
        raise ValueError("Binance all-tickers response missing")
    ranked = rank(market.metadata(), rows, limit=limit)
    if not ranked:
        raise ValueError("No liquid market candidates: refuse blind entries")
    return ranked
