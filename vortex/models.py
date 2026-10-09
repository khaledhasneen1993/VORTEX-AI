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
    taker_buy_volume: float | None = None

    @classmethod
    def from_binance(cls, values: list) -> "Candle":
        c = cls(int(values[0]), *map(float, values[1:6]), close_ts=int(values[6]),
                taker_buy_volume=float(values[9]) if len(values) > 9 else None)
        if min(c.open, c.high, c.low, c.close) <= 0 or c.low > c.high:
            raise ValueError("Malformed exchange candle")
        return c


@dataclass(frozen=True)
class FundingEvent:
    """Exchange-published funding rate paired with the contemporaneous mark."""
    ts: int
    rate: float
    mark_price: float


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
    votes: tuple[str, ...] = ()
    atr_value: float = 0.0


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
    votes: list[str] = field(default_factory=list)
    initial_stop: float = 0.0
    initial_target: float = 0.0
    atr_value: float = 0.0
    accumulated_funding: float = 0.0

    # Original strategy R anchor is immutable after weighted-cost pyramiding.
    anchor_entry: float = 0.0
    risk_fraction: float = 0.0
    trade_risk_cap: float = 0.0
    total_entry_qty: float = 0.0
    pyramid_count: int = 0
    last_pyramid_ms: int = 0
