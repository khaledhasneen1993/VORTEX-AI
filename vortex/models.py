"""Domain objects; timestamp is Binance candle opening time in milliseconds."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_ts: int = 0

    @classmethod
    def from_binance(cls, values: list) -> "Candle":
        c = cls(int(values[0]), *map(float, values[1:6]), close_ts=int(values[6]))
        if min(c.open, c.high, c.low, c.close) <= 0 or c.low > c.high:
            raise ValueError("Malformed exchange candle")
        return c


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str
    ts: int
    entry: float
    stop: float
    target: float
    score: int
    reason: str


@dataclass
class Position:
    symbol: str
    side: str
    opened_ts: int
    entry: float
    stop: float
    target: float
    qty: float
    entry_fee: float
    margin: float
