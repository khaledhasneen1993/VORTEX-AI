"""Opt-in strategy policy, isolated from frozen legacy research settings."""
from dataclasses import dataclass, fields
import os
from math import isfinite


@dataclass(frozen=True)
class StrategyPolicy:
    enabled: bool = False
    session_filter: bool = True
    sessions: str = 'asia,london,new_york'
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
    funding_extreme: float = 0.0015
    funding_oi_min_pct: float = 0.25
    funding_price_min_pct: float = 0.10
    funding_max_age_ms: int = 15000
    funding_interval_min_ms: int = 60000
    funding_interval_max_ms: int = 1800000
    max_signal_age_ms: int = 90000

    def __post_init__(self):
        allowed = {'asia', 'london', 'new_york'}
        if not set(self.sessions.split(',')) <= allowed or not self.sessions:
            raise ValueError('PHASE1_SESSIONS must name UTC sessions')
        for name in allowed:
            start, end = getattr(self, name+'_start'), getattr(self, name+'_end')
            if not 0 <= start < 24 or not 0 <= end <= 24 or start == end:
                raise ValueError('Invalid UTC session hours')
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not isfinite(value) or value < 0:
                    raise ValueError('Invalid PHASE1_' + f.name.upper())
        if not 20 <= self.atr_lookback <= 200 or not 2 <= self.cvd_window <= 100:
            raise ValueError('Invalid phase1 lookback')
        if not 2 <= self.breakout_lookback <= 100 or not 2 <= self.normal_votes <= 4:
            raise ValueError('Invalid phase1 vote/window bounds')
        if not 0 <= self.atr_percentile_min <= 100 or not 0 <= self.cvd_min <= 1:
            raise ValueError('Invalid phase1 percentile/CVD threshold')
        if not 0 < self.atr_pct_min < self.atr_pct_max < 1:
            raise ValueError('Invalid phase1 ATR limits')
        if not 0 < self.range_adx <= self.trend_adx <= self.strong_adx <= 100:
            raise ValueError('Invalid phase1 regime thresholds')
        if not 0 < self.funding_interval_min_ms <= self.funding_interval_max_ms:
            raise ValueError('Invalid funding interval')
        if min(self.trend_weight, self.breakout_weight, self.normal_weight,
               self.strong_weight, self.funding_extreme, self.max_signal_age_ms) <= 0:
            raise ValueError('Primary weights/thresholds must be positive')

    @classmethod
    def from_env(cls):
        values = {}
        defaults = cls()
        for f in fields(cls):
            raw = os.getenv('PHASE1_' + f.name.upper())
            if raw is None:
                continue
            default = getattr(defaults, f.name)
            if isinstance(default, bool):
                if raw.strip().lower() not in {'true', 'false'}:
                    raise ValueError('Invalid boolean PHASE1_' + f.name.upper())
                values[f.name] = raw.strip().lower() == 'true'
            else:
                values[f.name] = type(default)(raw.strip())
        return cls(**values)
