from dataclasses import replace

import pytest

from vortex.extra_voters import liquidity_sweep, volume_spike
from vortex.models import Candle
from vortex.phase1_config import StrategyPolicy

P = StrategyPolicy(volume_spike_enabled=True, liquidity_sweep_enabled=True)
PRIOR = [Candle(i * 300000, 100, 101, 99, 100, 100, (i + 1) * 300000 - 1) for i in range(20)]


@pytest.mark.parametrize("sign", [1, -1])
def test_spike_closes_past_swing_with_directional_body(sign):
    current = Candle(
        6000000,
        100,
        103 if sign == 1 else 100.2,
        99.8 if sign == 1 else 97,
        102.9 if sign == 1 else 97.1,
        400,
        6299999,
    )
    rows = PRIOR + [current]
    assert volume_spike(rows, 1, 4, 30, 30, P)[0] == sign
    assert volume_spike(rows, 1, 4, 30, 30, replace(P, volume_spike_enabled=False))[0] == 0
    assert volume_spike(rows, 1, 2, 30, 30, P)[0] == 0
    assert volume_spike(rows, 1, 4, 19, 19, P)[0] == 0
    assert volume_spike(PRIOR, 1, 4, 30, 30, P)[0] == 0
    assert volume_spike(PRIOR + [replace(current, close=100)], 1, 4, 30, 30, P)[0] == 0


@pytest.mark.parametrize("sign", [1, -1])
def test_sweep_reclaims_swing_with_large_wick_and_no_two_sided_sweep(sign):
    current = Candle(
        6000000,
        99.5 if sign == 1 else 100.5,
        100.1 if sign == 1 else 103,
        97 if sign == 1 else 99.9,
        100,
        200,
        6299999,
    )
    rows = PRIOR + [current]
    assert liquidity_sweep(rows, 1, 2, P)[0] == sign
    assert liquidity_sweep(rows, 1, 2, replace(P, liquidity_sweep_enabled=False))[0] == 0
    assert liquidity_sweep(rows, 1, 1, P)[0] == 0
    assert liquidity_sweep(PRIOR, 1, 2, P)[0] == 0
    assert (
        liquidity_sweep(PRIOR + [replace(current, high=103, low=97)], 1, 2, P)[1]
        == "SWEEP_ABSTAIN_BOTH_SIDES"
    )
    assert liquidity_sweep(PRIOR + [replace(current, close=98 if sign == 1 else 102)], 1, 2, P)[0] == 0
