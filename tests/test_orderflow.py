"""Synthetic public observations verify semantics, not trading performance."""

from dataclasses import replace

import pytest

from vortex.orderflow import collect_flow, flow_direction, summarize_trades
from vortex.phase1_config import StrategyPolicy

NOW = 1_000_000
P = StrategyPolicy(flow_enabled=True, flow_min_trades=2)


def prints(maker=False):
    return [dict(a=10, T=NOW - 100, p="100", q="3", m=maker), dict(a=11, T=NOW, p="100", q="1", m=not maker)]


@pytest.mark.parametrize("sign", [1, -1])
def test_cvd_aggression_direction_and_freshness(sign):
    observation = summarize_trades("BTCUSDT", prints(sign == -1), NOW, P)
    assert observation.cvd_base == 2 * sign
    assert observation.base_imbalance == observation.aggression == 0.5 * sign
    assert flow_direction(observation, "BTCUSDT", NOW, P)[0] == sign
    assert flow_direction(observation, "BTCUSDT", NOW, replace(P, flow_enabled=False)) == (0, "FLOW_DISABLED")
    for when in (NOW - 1, NOW + P.flow_max_age_ms + 1):
        assert flow_direction(observation, "BTCUSDT", when, P)[1] == "FLOW_ABSTAIN_STALE_OR_FUTURE"
    assert flow_direction(observation, "ETHUSDT", NOW, P)[1] == "FLOW_ABSTAIN_SYMBOL_MISMATCH"
    assert flow_direction(None, "BTCUSDT", NOW, P)[1] == "FLOW_ABSTAIN_MISSING"
    assert flow_direction(replace(observation, aggression=float("nan")), "BTCUSDT", NOW, P)[0] == 0


def test_uncertain_coverage_neutral_and_malformed_abstain():
    assert summarize_trades("BTCUSDT", prints() * 500, NOW, P).reason == "FLOW_ABSTAIN_TRUNCATED"
    for rows in (
        [],
        prints()[:1],
        prints()[::-1],
        [prints()[0], prints()[0]],
        [dict(prints()[0], m="false")],
        [dict(prints()[0], q="nan")],
        [dict(prints()[0], T=NOW + 1)],
        [dict(prints()[0], T=NOW - 60000)],
    ):
        observation = summarize_trades("BTCUSDT", rows, NOW, P)
        assert observation.cvd_base is None and observation.reason.startswith("FLOW_ABSTAIN_")
    neutral = summarize_trades("BTCUSDT", [dict(t, q="1") for t in prints()], NOW, P)
    assert flow_direction(neutral, "BTCUSDT", NOW, P) == (0, "FLOW_NEUTRAL")


def test_collector_is_bounded_opt_in_and_soft_on_failure():
    from vortex.binance import MarketError

    class Market:
        calls = []

        def get(self, path, params):
            self.calls.append((path, params))
            return prints()

    market = Market()
    assert collect_flow(market, "BTCUSDT", NOW, replace(P, flow_enabled=False)) is None
    assert market.calls == []
    assert collect_flow(market, "BTCUSDT", NOW, P).reason == "FLOW_VALID"
    assert market.calls[0] == (
        "/fapi/v1/aggTrades",
        {
            "symbol": "BTCUSDT",
            "startTime": NOW - 15000,
            "endTime": NOW,
            "limit": 1000,
        },
    )
    market.get = lambda *args: (_ for _ in ()).throw(MarketError("unavailable"))
    assert collect_flow(market, "BTCUSDT", NOW, P).reason == "FLOW_ABSTAIN_FETCH_FAILED"
    for kwargs in (
        {"flow_mode": "fake"},
        {"flow_max_age_ms": 15001},
        {"flow_limit": 1001},
        {"flow_min_imbalance": 0},
        {"flow_weight": 3},
    ):
        with pytest.raises(ValueError):
            replace(P, **kwargs)
