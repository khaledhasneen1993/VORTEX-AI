"""Domain objects; timestamp is Binance candle opening time in milliseconds."""
from __future__ import annotations
from dataclasses import dataclass, field


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
    features: dict[str, float] = field(default_factory=dict)


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
    features: dict[str, float] = field(default_factory=dict)
    initial_qty: float = 0.0
    initial_risk: float = 0.0
    peak: float = 0.0
    tp1_done: bool = False
    tp2_done: bool = False
    step: float = 0.0
    accumulated_net: float = 0.0
    filled_stage_count: int = 0
