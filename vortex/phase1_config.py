"""Current weighted-strategy configuration."""

import os
from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class StrategyPolicy:
    enabled: bool = True
    session_filter: bool = True
    sessions: str = "asia,london,new_york"
    asia_start: int = 0
    asia_end: int = 8
    london_start: int = 7
    london_end: int = 16
    new_york_start: int = 13
    new_york_end: int = 22
    volatility_filter: bool = True
    atr_lookback: int = 100
    atr_percentile_min: float = 40.0
    atr_pct_min: float = 0.0008
    atr_pct_max: float = 0.045
    cvd_filter: bool = True
    cvd_window: int = 10
    cvd_min: float = 0.05
    range_adx: float = 20.0
    trend_adx: float = 25.0
    breakout_adx: float = 18.0
    breakout_volume: float = 2.0
    breakout_lookback: int = 20
    trend_weight: float = 2.0
    breakout_weight: float = 2.0
    reversion_weight: float = 1.0
    funding_weight: float = 1.0
    trend_boost: float = 1.0
    normal_votes: int = 2
    normal_weight: float = 4.0
    strong_enabled: bool = True
    strong_adx: float = 30.0
    strong_volume: float = 3.0
    strong_body_atr: float = 0.6
    strong_weight: float = 3.0
    strict_votes: bool = True
    allow_single_strong_vote: bool = False
    min_strong_score: int = 7
    flow_enabled: bool = False
    flow_mode: str = "confirm"
    flow_window_ms: int = 15000
    flow_max_age_ms: int = 5000
    flow_min_trades: int = 20
    flow_limit: int = 1000
    flow_min_imbalance: float = 0.10
    flow_weight: float = 1.0
    regime_enabled: bool = False
    regime_window: int = 20
    regime_dead_percentile: float = 20.0
    regime_min_bb_width: float = 0.004
    regime_trend_efficiency: float = 0.35
    funding_extreme: float = 0.0015
    funding_oi_min_pct: float = 0.25
    funding_price_min_pct: float = 0.10
    funding_max_age_ms: int = 15000
    funding_interval_min_ms: int = 60000
    funding_interval_max_ms: int = 1800000
    max_signal_age_ms: int = 90000

    def __post_init__(self):
        allowed = {"asia", "london", "new_york"}
        if not set(self.sessions.split(",")) <= allowed or not self.sessions:
            raise ValueError("PHASE1_SESSIONS must name UTC sessions")
        for name in allowed:
            start, end = getattr(self, name + "_start"), getattr(self, name + "_end")
            if not 0 <= start < 24 or not 0 <= end <= 24 or start == end:
                raise ValueError("Invalid UTC session hours")
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not isfinite(value) or value < 0:
                    raise ValueError("Invalid PHASE1_" + f.name.upper())
        if not 20 <= self.atr_lookback <= 200 or not 2 <= self.cvd_window <= 100:
            raise ValueError("Invalid phase1 lookback")
        if not 2 <= self.breakout_lookback <= 100 or not 2 <= self.normal_votes <= 4:
            raise ValueError("Invalid phase1 vote/window bounds")
        if not 3 <= self.min_strong_score <= 10:
            raise ValueError("MIN_STRONG_SCORE must be 3..10")
        if not isinstance(self.strict_votes, bool) or not isinstance(self.allow_single_strong_vote, bool):
            raise ValueError("Vote flags must be boolean")
        if not isinstance(self.flow_enabled, bool) or self.flow_mode not in {"confirm", "voter"}:
            raise ValueError("Flow requires a boolean flag and confirm/voter mode")
        if not (
            1000 <= self.flow_window_ms <= 60000
            and 1 <= self.flow_max_age_ms <= min(15000, self.flow_window_ms)
            and 1 <= self.flow_min_trades < self.flow_limit <= 1000
            and 0 < self.flow_min_imbalance <= 1
            and 0 < self.flow_weight <= 2
        ):
            raise ValueError("Invalid bounded flow policy")
        if not isinstance(self.regime_enabled, bool) or not (
            10 <= self.regime_window <= 100
            and 0 <= self.regime_dead_percentile <= 100
            and 0 < self.regime_min_bb_width < 0.2
            and 0 < self.regime_trend_efficiency < 1
        ):
            raise ValueError("Invalid bounded regime policy")
        if not 0 <= self.atr_percentile_min <= 100 or not 0 <= self.cvd_min <= 1:
            raise ValueError("Invalid phase1 percentile/CVD threshold")
        if not 0 < self.atr_pct_min < self.atr_pct_max < 1:
            raise ValueError("Invalid phase1 ATR limits")
        if not 0 < self.range_adx <= self.trend_adx <= self.strong_adx <= 100:
            raise ValueError("Invalid phase1 regime thresholds")
        if not 0 < self.funding_interval_min_ms <= self.funding_interval_max_ms:
            raise ValueError("Invalid funding interval")
        if (
            min(
                self.trend_weight,
                self.breakout_weight,
                self.normal_weight,
                self.strong_weight,
                self.funding_extreme,
                self.max_signal_age_ms,
            )
            <= 0
        ):
            raise ValueError("Primary weights/thresholds must be positive")

    @classmethod
    def from_env(cls, defaults=None):
        values = {}
        defaults = defaults or cls()
        aliases = {
            "strict_votes": "STRICT_VOTES",
            "allow_single_strong_vote": "ALLOW_SINGLE_STRONG_VOTE",
            "min_strong_score": "MIN_STRONG_SCORE",
        }
        for f in fields(cls):
            name = "PHASE1_" + f.name.upper()
            raw = os.getenv(aliases.get(f.name, name), os.getenv(name))
            if raw is None:
                values[f.name] = getattr(defaults, f.name)
                continue
            default = getattr(defaults, f.name)
            if isinstance(default, bool):
                if raw.strip().lower() not in {"true", "false"}:
                    raise ValueError("Invalid boolean PHASE1_" + f.name.upper())
                values[f.name] = raw.strip().lower() == "true"
            else:
                values[f.name] = type(default)(raw.strip())
        return cls(**values)
