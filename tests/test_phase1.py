from dataclasses import fields, replace

import pytest

from vortex.config import Settings
from vortex.market_features import Derivatives
from vortex.models import Candle
from vortex.operations import OperationsPolicy
from vortex.phase1_config import StrategyPolicy
from vortex.phase1_strategy import (
    atr_percentile,
    cvd_ratio,
    funding_direction,
    phase1_vote,
    session_allowed,
    weighted_selection,
)
from vortex.strategy import analyze


def history(n, step, end, sign=1):
    result = []
    for i in range(n):
        price = 100 + sign * (i * 0.08 + i * i * 0.0003)
        result.append(
            Candle(
                end - n * step + i * step,
                price - 0.02 * sign,
                price + 0.1,
                price - 0.1,
                price,
                100,
                end - n * step + (i + 1) * step - 1,
                80 if sign == 1 else 20,
            )
        )
    return result


def setup(sign=1):
    end = 1791547200000
    small, higher, macro = (
        history(220, 300000, end, sign),
        history(120, 900000, end, sign),
        history(260, 3600000, end, sign),
    )
    small[-1] = replace(
        small[-1],
        volume=400,
        taker_buy_volume=320 if sign == 1 else 80,
        open=small[-1].close - sign * 0.2,
        low=min(small[-1].low, small[-1].close - sign * 0.2),
        high=max(small[-1].high, small[-1].close - sign * 0.2),
    )
    return (small, higher, macro, end)


def test_actual_cvd_and_missing_data():
    bars = history(20, 300000, 1791547200000)
    assert cvd_ratio(bars, 10) == pytest.approx(0.6)
    assert cvd_ratio([replace(b, taker_buy_volume=None) for b in bars], 10) is None
    assert cvd_ratio([replace(b, taker_buy_volume=101) for b in bars], 10) is None
    raw = [1, "1", "2", ".5", "1.5", "100", 299999, 0, 0, "70", 0, 0]
    assert Candle.from_binance(raw).taker_buy_volume == 70
    assert Candle.from_binance(raw[:7]).taker_buy_volume is None


def test_atr_rank_no_future():
    bars = history(130, 300000, 1791547200000)
    rank = atr_percentile(bars, 100)
    assert 0 <= rank <= 100
    assert atr_percentile(bars[:20], 100) is None
    expanded = bars + [replace(bars[-1], high=10000)]
    assert atr_percentile(expanded[:-1], 100) == rank


def test_session_overlap_and_closed_hours():
    p = StrategyPolicy(sessions="london")
    day = 1791504000000 // 86400000 * 86400000
    assert session_allowed(p, day + 8 * 3600000)
    assert not session_allowed(p, day + 23 * 3600000)
    assert session_allowed(replace(p, session_filter=False), day + 23 * 3600000)
    night = replace(p, london_start=22, london_end=6)
    assert session_allowed(night, day + 23 * 3600000)
    assert not session_allowed(night, day + 12 * 3600000)


@pytest.mark.parametrize("sign", [1, -1])
def test_funding_needs_price_oi_and_freshness(sign):
    p = StrategyPolicy()
    now = 1000000
    d = Derivatives(-sign * 0.002, 1, now - 100, sign * 0.5, 300000)
    assert funding_direction(d, now, p) == sign
    for weak in (
        replace(d, price_change_pct=-sign * 0.5),
        replace(d, oi_change_pct=0.01),
        replace(d, price_change_pct=None),
        replace(d, interval_ms=1),
        replace(d, observed_ms=now - 16000),
        replace(d, observed_ms=now + 1),
    ):
        assert funding_direction(weak, now, p) == 0


def test_weighted_normal_strong_primary_and_tie():
    p = StrategyPolicy()
    w = dict(trend=3, breakout=3, reversion=1, funding_fade=1)
    assert weighted_selection({"trend": 1, "breakout": 1}, w, 1, False, p)[0] == 1
    assert weighted_selection({"trend": 1}, w, 1, False, p)[0] == 0
    assert weighted_selection({"trend": 1}, w, 1, True, p)[0] == 1
    assert weighted_selection({"trend": 1, "breakout": -1}, w, 1, True, p)[0] == 0
    assert weighted_selection({"funding_fade": 1, "reversion": 1}, w, 1, True, p)[0] == 0
    assert weighted_selection({"trend": 1}, w, 1, True, replace(p, strong_enabled=False))[0] == 0
    weak_weights = dict(w, trend=2)
    mixed = {"trend": 1, "funding_fade": 1}
    assert weighted_selection(mixed, weak_weights, 1, False, p)[0] == 0
    assert weighted_selection(mixed, weak_weights, 1, False, replace(p, strict_votes=False))[0] == 1
    opt = replace(p, allow_single_strong_vote=True)
    assert weighted_selection({"trend": 1}, weak_weights, 1, False, opt)[0] == 0
    assert weighted_selection({"trend": 1}, weak_weights, 1, False, opt, clear_single=True)[0] == 1
    assert weighted_selection({"trend": 1}, weak_weights, 1, False, p, clear_single=True)[0] == 0
    assert (
        weighted_selection({"trend": 1, "funding_fade": -1}, weak_weights, 1, False, opt, clear_single=True)[
            0
        ]
        == 0
    )
    assert weighted_selection({"funding_fade": 1}, w, 1, False, opt, clear_single=True)[0] == 0
    assert weighted_selection({"trend": 1}, weak_weights, -1, False, opt, clear_single=True)[0] == 0


@pytest.mark.parametrize("sign", [1, -1])
def test_full_signal_symmetry_and_fail_closed(sign):
    small, higher, macro, now = setup(sign)
    p = StrategyPolicy(enabled=True, session_filter=False, volatility_filter=False)

    def run(s=small, h=higher, m=macro, t=now):
        return phase1_vote(
            "BTCUSDT", s, h, macro=m, deriv=None, decision_ms=t, minute=None, min_score=5, policy=p
        )

    sig = run()
    assert sig and sig.side == ("LONG" if sign == 1 else "SHORT")
    assert "trend" in sig.votes and sig.features["strong_signal"] == 1
    assert abs(sig.target - sig.entry) / abs(sig.entry - sig.stop) == pytest.approx(3)
    assert run(m=history(260, 3600000, now, -sign)) is None
    assert run(s=[replace(b, taker_buy_volume=None) for b in small]) is None
    assert run(t=now + 100000) is None
    assert run(s=small[:-2] + small[-1:]) is None
    assert run(m=None) is None
    assert run(s=small + [replace(small[-1], ts=now, close_ts=now + 300000)]) is None
    assert analyze("BTCUSDT", small, higher, macro=macro, decision_ms=now, policy=p) == sig
    spike = analyze(
        "BTCUSDT",
        small,
        higher,
        macro=macro,
        decision_ms=now,
        policy=replace(p, volume_spike_enabled=True, volume_spike_close_fraction=0.5),
    )
    assert spike and "volume_spike" in spike.votes and "breakout" not in spike.votes
    assert len(spike.votes) == len(sig.votes)
    swept = list(small)
    if sign == 1:
        swept[-1] = replace(swept[-1], low=min(b.low for b in swept[-21:-1]) - 2)
    else:
        swept[-1] = replace(swept[-1], high=max(b.high for b in swept[-21:-1]) + 2)
    sweep = analyze(
        "BTCUSDT",
        swept,
        higher,
        macro=macro,
        decision_ms=now,
        policy=replace(p, liquidity_sweep_enabled=True, sweep_min_atr=0.5),
    )
    assert sweep and "liquidity_sweep" in sweep.votes
    from vortex.orderflow import FlowObservation

    flow_policy = replace(p, flow_enabled=True, flow_min_trades=2)
    fresh = FlowObservation("BTCUSDT", now, now, 2, sign * 2, sign * 0.5, sign * 0.5, "FLOW_VALID")

    def with_flow(observation, policy=flow_policy):
        return analyze(
            "BTCUSDT", small, higher, macro=macro, decision_ms=now, policy=policy, flow=observation
        )

    confirmed = with_flow(fresh)
    assert confirmed and "FLOW_ALIGNED" in confirmed.reason
    assert confirmed.features["flow_cvd_base"] == sign * 2
    assert (
        with_flow(replace(fresh, cvd_base=-sign * 2, base_imbalance=-sign * 0.5, aggression=-sign * 0.5))
        is None
    )
    assert with_flow(replace(fresh, cvd_base=0, base_imbalance=0, aggression=0)) is None
    missing_flow = with_flow(None)
    assert missing_flow and missing_flow.features["flow_available"] == 0
    stale = with_flow(replace(fresh, end_ms=now - 16000, latest_ms=now - 16000))
    assert stale and "FLOW_ABSTAIN_STALE_OR_FUTURE" in stale.reason and "flow_cvd_base" not in stale.features
    voter = with_flow(fresh, replace(flow_policy, flow_mode="voter"))
    assert voter and "order_flow" in voter.votes
    funding_policy = replace(flow_policy, funding_flow_confirm=True)
    derivative = Derivatives(-sign * 0.002, 1, now - 100, sign * 0.5, 300000)
    funded = analyze(
        "BTCUSDT",
        small,
        higher,
        macro=macro,
        decision_ms=now,
        derivatives=derivative,
        policy=funding_policy,
        flow=fresh,
    )
    assert funded and "funding_fade" in funded.votes and "FUNDING_FLOW_ALIGNED" in funded.reason
    unfunded = analyze(
        "BTCUSDT", small, higher, macro=macro, decision_ms=now, derivatives=derivative, policy=funding_policy
    )
    assert (
        unfunded
        and "funding_fade" not in unfunded.votes
        and "FUNDING_ABSTAIN_FLOW_UNCONFIRMED" in unfunded.reason
    )
    with pytest.raises(ValueError):
        replace(p, funding_flow_confirm=True)


def test_configuration_env_and_no_risk_change(monkeypatch):
    monkeypatch.setenv("PHASE1_ENABLED", "true")
    monkeypatch.setenv("PHASE1_CVD_MIN", ".12")
    p = StrategyPolicy.from_env()
    assert p.enabled and p.cvd_min == 0.12
    assert (
        Settings(
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
        ).risk_per_trade
        == 0.12
        and Settings(
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
        ).max_positions
        == 4
    )
    for kwargs in (
        {"cvd_min": 2},
        {"atr_percentile_min": 101},
        {"sessions": "mars"},
        {"normal_votes": 1},
        {"range_adx": 30},
        {"trend_weight": float("nan")},
    ):
        with pytest.raises(ValueError):
            StrategyPolicy(**kwargs)
    monkeypatch.setenv("PHASE1_ENABLED", "maybe")
    with pytest.raises(ValueError):
        StrategyPolicy.from_env()
    env = open(".env.example").read()
    assert all(("PHASE1_" + f.name.upper() + "=" in env for f in fields(StrategyPolicy)))


def test_filters_toggle_and_thresholds(monkeypatch):
    import vortex.phase1_strategy as mod

    monkeypatch.setattr(mod, "atr_percentile", lambda *args: 30)
    small, higher, macro, now = setup()
    base = StrategyPolicy(enabled=True, session_filter=False, volatility_filter=False)

    def run(policy, bars=small):
        return phase1_vote(
            "BTCUSDT",
            bars,
            higher,
            macro=macro,
            deriv=None,
            decision_ms=now,
            minute=None,
            min_score=5,
            policy=policy,
        )

    assert run(base)
    assert run(replace(base, volatility_filter=True, atr_percentile_min=100)) is None
    improved = replace(base, regime_enabled=True, volatility_filter=True, atr_percentile_min=100)
    trend = run(improved)
    assert trend and trend.features["regime_id"] == 1 and "REGIME_TREND_DIRECTIONAL" in trend.reason
    assert run(replace(improved, regime_dead_percentile=100, regime_min_bb_width=0.19)) is None
    missing = [replace(b, taker_buy_volume=None) for b in small]
    assert run(replace(base, cvd_filter=False), missing)
    assert run(replace(base, session_filter=True, sessions="asia")) is None
    assert run(replace(base, strong_enabled=False, normal_weight=10)) is None
    assert run(replace(base, trend_weight=1, breakout_weight=1, trend_boost=0, strong_weight=3)) is None
    with pytest.raises(ValueError):
        Settings(
            phase1=base,
            timeframe="15m",
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    # Actual pipeline: only trend votes; the new volume/body path needs opt-in.
    monkeypatch.setattr(mod, "adx", lambda bars: 25)
    monkeypatch.setattr(mod, "atr", lambda bars: 0.2)
    single = replace(base, breakout_adx=100, min_strong_score=6)
    assert run(single) is None
    opt = replace(single, allow_single_strong_vote=True)
    sig = run(opt)
    assert sig and sig.score == 6 and sig.votes == ("trend",)
    assert sig.features["strong_signal"] == 1
    assert run(replace(opt, min_strong_score=7)) is None
    assert run(opt, small[:-1] + [replace(small[-1], volume=390)]) is None
    assert run(opt, small[:-1] + [replace(small[-1], open=small[-1].close - 0.15)]) is None
    assert run(opt, missing) is None
    monkeypatch.setattr(mod, "adx", lambda bars: 24)
    assert run(opt) is None


def test_range_reversion_gate(monkeypatch):
    import vortex.phase1_strategy as mod

    small, higher, macro, now = setup()
    calls = []
    monkeypatch.setattr(mod, "reversion_direction", lambda *args: calls.append(1) or 1)
    p = StrategyPolicy(enabled=True, session_filter=False, volatility_filter=False)
    monkeypatch.setattr(mod, "adx", lambda bars: 19)
    mod.phase1_vote(
        "BTCUSDT", small, higher, macro=macro, deriv=None, decision_ms=now, minute=None, min_score=5, policy=p
    )
    assert len(calls) == 1
    monkeypatch.setattr(mod, "adx", lambda bars: 20)
    mod.phase1_vote(
        "BTCUSDT", small, higher, macro=macro, deriv=None, decision_ms=now, minute=None, min_score=5, policy=p
    )
    assert len(calls) == 1


def test_paired_price_tracker():
    from vortex.derivatives import DerivativesTracker

    class Market:
        now = 1000000
        mark = 100
        oi = 100

        def server_ms(self):
            return self.now

        def get(self, path, params):
            if path.endswith("premiumIndex"):
                return dict(symbol="BTCUSDT", lastFundingRate="-.002", time=self.now, markPrice=self.mark)
            return dict(symbol="BTCUSDT", openInterest=self.oi, time=self.now)

    m = Market()
    t = DerivativesTracker()
    assert t.sample(m, "BTCUSDT", m.now) is None
    m.now += 300000
    m.mark = 101
    m.oi = 102
    d = t.sample(m, "BTCUSDT", m.now)
    assert d.price_change_pct == pytest.approx(1)
    assert d.interval_ms == 300000
    assert funding_direction(d, m.now, StrategyPolicy()) == 1


def test_paper_capture_requires_observed_primary_and_keeps_freshness(monkeypatch):
    from vortex import phase1_strategy as module

    small, higher, macro, end = setup()
    policy = StrategyPolicy(strong_enabled=False, normal_votes=4, normal_weight=20)
    monkeypatch.setattr(module, "atr_percentile", lambda *args: 30)
    args = dict(macro=macro, decision_ms=end, minute=None, policy=policy)
    assert analyze("BTCUSDT", small, higher, **args) is None
    signal = analyze("BTCUSDT", small, higher, capture=True, **args)
    assert signal and signal.side == "LONG" and "CAPTURE_RELAXED" in signal.reason
    mixed = history(260, 3600000, end, -1)
    assert analyze("BTCUSDT", small, higher, capture=True, **dict(args, macro=mixed))
    assert analyze("BTCUSDT", small, higher, capture=True, **dict(args, decision_ms=end + 90001)) is None
    monkeypatch.setattr(module, "adx", lambda *args: 0)
    flat_volume = [replace(b, volume=100) for b in small]
    assert analyze("BTCUSDT", flat_volume, higher, capture=True, **args) is None
