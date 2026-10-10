from dataclasses import replace

import pytest

from vortex.models import Candle
from vortex.phase1_config import StrategyPolicy
from vortex.regime import classify

P = StrategyPolicy(regime_enabled=True)


def bars(closes):
    return [
        Candle(i * 300000, x, x + 0.01, x - 0.01, x, 10, (i + 1) * 300000 - 1) for i, x in enumerate(closes)
    ]


def test_dead_range_chop_and_clear_trend_are_distinct():
    flat = bars([100] * 20)
    assert classify(flat, 10, 19, 19, P).name == "dead"
    zigzag = bars([100 + (i % 2) for i in range(20)])
    assert classify(zigzag, 50, 19, 19, P).name == "range"
    assert classify(zigzag, 50, 26, 30, P).name == "chop"
    trend = bars([100 + i for i in range(20)])
    label = classify(trend, 25, 30, 30, P)
    assert label.name == "trend" and label.efficiency == 1 and label.bb_width > 0.004
    assert classify(trend, 50, 19, 19, P).name == "chop"
    assert classify(trend, 25, 30, 30, replace(P, regime_enabled=False)).name == "disabled"
    assert classify(trend, None, 30, 30, P).name == "unknown"
    assert classify(bars([float("nan")] * 20), 50, 30, 30, P).name == "unknown"
    for kwargs in (
        {"regime_window": 1001},
        {"regime_dead_percentile": 101},
        {"regime_min_bb_width": 0},
        {"regime_trend_efficiency": 1},
    ):
        with pytest.raises(ValueError):
            replace(P, **kwargs)
