from vortex.operations import OperationsPolicy

"""Account-level Phase2 tests use synthetic observations, not market performance."""
from dataclasses import fields, replace
from math import sin

import pytest

from vortex.config import Settings
from vortex.exits import decide_tick
from vortex.models import Candle, Position, Signal
from vortex.paper import PaperBroker
from vortex.phase2 import (
    ProfitReserve,
    RiskPolicy,
    apply_pyramid,
    correlation_gate,
    pyramid_plan,
    risk_fraction,
)
from vortex.risk import Filters, RiskGate, size_trade

F = Filters(0.001, 0.001, 5, 0.01)
NOW = 1791547200000


def config(**kw):
    return Settings(
        phase2=RiskPolicy(enabled=True),
        risk_per_trade=0.12,
        max_positions=4,
        max_daily_loss=0.55,
        trailing_atr_mult=0.8,
        **kw,
        operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
    )


def signal(symbol="BTCUSDT", side="LONG", score=8, strong=True):
    return Signal(
        symbol,
        side,
        NOW - 300000,
        100,
        90 if side == "LONG" else 110,
        130 if side == "LONG" else 70,
        score,
        "test",
        {"strong_signal": float(strong)},
    )


def bars(sign=1):
    price = 100
    out = []
    for i in range(80):
        price *= 1 + sign * (0.001 * sin(i * 0.3) + 0.0001 * i / 80)
        ts = NOW - (80 - i) * 300000
        out.append(Candle(ts, price, price + 0.1, price - 0.1, price, 100, ts + 299999, 70))
    return out


def position(side="LONG"):
    p = Position(
        "BTCUSDT",
        side,
        NOW - 1200000,
        100,
        110 if side == "LONG" else 90,
        130 if side == "LONG" else 70,
        5,
        0.25,
        100,
        initial_qty=10,
        initial_risk=10,
        peak=120 if side == "LONG" else 80,
        tp1_done=True,
        tp2_done=True,
        step=0.001,
        accumulated_net=62.0,
        anchor_entry=100,
        risk_fraction=0.12,
        trade_risk_cap=120,
        total_entry_qty=10,
    )
    return p


def test_dynamic_risk_and_cap():
    c = config()
    assert risk_fraction(signal(score=5, strong=False), c) == 0.08
    assert risk_fraction(signal(score=10, strong=False), c) == 0.1
    assert risk_fraction(signal(score=7), c) == 0.12
    assert risk_fraction(signal(score=10), c) == 0.15
    assert risk_fraction(signal(score=10), replace(c, risk_per_trade=0.15)) == 0.15
    aggressive = replace(c, phase2=replace(c.phase2, aggressive_strong_risk=True, strong_max=0.18))
    assert risk_fraction(signal(score=10), aggressive) == 0.18
    assert risk_fraction(signal(score=10, strong=False), aggressive) == 0.10
    assert risk_fraction(signal(score=7), aggressive) == 0.12
    sized = size_trade(signal(score=10), 1000, aggressive, F)
    assert sized and sized[1] <= 1000 * aggressive.phase2.entry_margin_fraction
    assert sized[0] * 100 / sized[1] <= 5
    assert size_trade(signal(score=10), 1000, aggressive, F, committed_margin=250) is None
    assert risk_fraction(signal(score=4), c) == 0
    assert risk_fraction(signal(score=10, strong=False), replace(c, risk_per_trade=0.09)) == 0.09
    assert size_trade(signal(score=4), 1000, c, F) is None
    assert (
        risk_fraction(
            signal(score=10),
            Settings(
                operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
            ),
        )
        == 0.15
    )


def test_default_env_and_validation(monkeypatch):
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    monkeypatch.setenv("PHASE2_ENABLED", "true")
    for key in ("RISK_PER_TRADE", "MAX_POSITIONS", "MAX_DAILY_LOSS", "TRAILING_ATR_MULT"):
        monkeypatch.delenv(key, raising=False)
    c = Settings.from_env()
    assert (c.risk_per_trade, c.max_positions, c.max_daily_loss, c.trailing_atr_mult) == (0.12, 4, 0.55, 0.8)
    for kwargs in ({"risk_per_trade": 0.151}, {"max_positions": 5}, {"max_daily_loss": 0.551}):
        with pytest.raises(ValueError):
            replace(c, **kwargs)
    for kw in (
        {"normal_min": 0.07},
        {"strong_max": 0.16},
        {"compounding_fraction": 1.1},
        {"pyramid_max_adds": 4},
        {"pyramid_trigger_r": 1},
        {"correlation_max": 1},
        {"entry_margin_fraction": 0.26},
        {"pyramid_risk_fraction": float("nan")},
    ):
        with pytest.raises(ValueError):
            RiskPolicy(**kw)
    monkeypatch.setenv("PHASE2_ENABLED", "bad")
    with pytest.raises(ValueError):
        RiskPolicy.from_env()


def test_capital_reserve_ignores_marks_and_never_releases_on_losses():
    r = ProfitReserve(config())
    assert r.capital(1000, 1200) == 1000
    r.record(100)
    assert r.reserved == 50 and r.capital(1100, 1200) == 1050
    r.record(-100)
    assert r.reserved == 50 and r.capital(1000, 900) == 850
    assert r.capital(20, 10) == 0


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_pyramid_winner_limit_and_immutable_r(side):
    c = config()
    p = position(side)
    px = 120 if side == "LONG" else 80
    plan = pyramid_plan(p, px, NOW, c, F, 1000, 100, 1, px)
    plan = pyramid_plan(p, px, NOW, c, F, 4000, 100, 1, px)
    assert plan
    old_stop, old_target = (p.stop, p.target)
    q, m, f = plan
    assert q <= p.initial_qty * c.phase2.pyramid_size_fraction
    apply_pyramid(p, px, q, m, f, NOW)
    assert (
        p.pyramid_count == 1 and p.stop == old_stop and (p.target == old_target) and (p.anchor_entry == 100)
    )
    assert p.entry != 100 and p.initial_qty == 10
    assert pyramid_plan(p, px, NOW + 600000, c, F, 4000, p.margin, 1, px) is None
    decide_tick(p, px, atr_value=2, trailing_atr_mult=0.8)
    assert (p.stop - old_stop) * (1 if side == "LONG" else -1) >= 0


@pytest.mark.parametrize(
    "change",
    [
        {"tp2_done": False},
        {"pyramid_count": 1},
        {"trade_risk_cap": 0},
        {"opened_ts": NOW - 1000},
        {"stop": 70, "accumulated_net": 0},
    ],
)
def test_pyramid_never_loser_or_unprotected(change):
    p = replace(position(), **change)
    assert pyramid_plan(p, 120, NOW, config(), F, 4000, 100, 1, 120) is None


def test_pyramid_prior_observation_no_lookahead():
    p = position()
    assert pyramid_plan(p, 120, NOW, config(), F, 4000, 100, 1, 110) is None
    assert pyramid_plan(p, 95, NOW, config(), F, 4000, 100, 1, 120) is None
    assert pyramid_plan(p, 135, NOW, config(), F, 4000, 100, 1, 135) is None
    assert pyramid_plan(p, 120, NOW, config(), F, 4000, 100, 1200, 120) is None


def test_direction_adjusted_correlation_and_missing():
    histories = {"BTCUSDT": bars(), "ETHUSDT": bars()}
    positions = {"BTCUSDT": position()}
    pol = RiskPolicy(enabled=True)
    assert not correlation_gate(signal("ETHUSDT"), positions, histories, NOW, pol)[0]
    assert correlation_gate(signal("ETHUSDT", side="SHORT"), positions, histories, NOW, pol)[0]
    assert not correlation_gate(signal("ETHUSDT"), positions, {}, NOW, pol)[0]
    assert not correlation_gate(signal("ETHUSDT"), positions, histories, NOW + 400000, pol)[0]
    assert correlation_gate(signal("ETHUSDT"), positions, {}, NOW, replace(pol, correlation_filter=False))[0]
    opposite = {"BTCUSDT": bars(), "ETHUSDT": bars(-1)}
    assert not correlation_gate(signal("ETHUSDT", side="SHORT"), positions, opposite, NOW, pol)[0]


def test_four_positions_and_global_risk_margin(tmp_path):
    c = config(data_dir=tmp_path, fee_rate=0, slippage_bps=0)
    c = replace(c, phase2=replace(c.phase2, correlation_filter=False))
    broker = PaperBroker(c)
    quotes = {s: (100, 100) for s in ("AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT")}
    for s in list(quotes)[:4]:
        assert broker.open(signal(s), 100, 100, F, quotes, NOW)[0]
    assert len(broker.positions) == 4
    assert sum((p.margin for p in broker.positions.values())) <= 250
    assert not broker.open(signal("EUSDT"), 100, 100, F, quotes, NOW)[0]
    gate = RiskGate(c, 1000)
    assert gate.can_open(451, 0)[0] and (not gate.can_open(450, 0)[0])
    assert not gate.can_open(1000, 0)[0]
    assert size_trade(signal(), 1000, c, F, committed_risk=301) is None


def test_paper_reserve_restart_and_configuration_latch(tmp_path):
    c = config(data_dir=tmp_path, fee_rate=0, slippage_bps=0)
    b = PaperBroker(c)
    ok, _ = b.open(signal(), 100, 100, F, {"BTCUSDT": (100, 100)}, NOW)
    assert ok
    before = b.wallet
    event = b.mark({"BTCUSDT": (131, 131)}, NOW + 300000)[0]
    assert event["final"]
    assert b.reserve.reserved == pytest.approx(event["net_pnl"] * 0.5)
    assert b.wallet > before
    recovered = PaperBroker(c)
    assert recovered.wallet == b.wallet and recovered.reserve.reserved == b.reserve.reserved
    with pytest.raises(ValueError, match="policy changed"):
        PaperBroker(replace(c, phase2=replace(c.phase2, compounding_fraction=0.7)))


def test_pyramid_accounting_and_crash_journal(tmp_path):
    c = config(data_dir=tmp_path, starting_equity=4000, fee_rate=0.0005, slippage_bps=0)
    c = replace(c, phase2=replace(c.phase2, correlation_filter=False))
    b = PaperBroker(c)
    b.positions["BTCUSDT"] = position()
    original = b.wallet
    h = bars()
    h[-1] = replace(h[-1], close=120, high=120.1, low=119.9, open=120)
    event = b.pyramid("BTCUSDT", 120, 120, F, {"BTCUSDT": (120, 120)}, NOW, {"BTCUSDT": h})
    assert event and b.wallet == pytest.approx(original - event["fee"])
    b.pending_journal = event
    b.save()
    recovered = PaperBroker(c)
    assert recovered.positions["BTCUSDT"].pyramid_count == 1
    assert len((tmp_path / "pyramids.jsonl").read_text().splitlines()) == 1
    p = recovered.positions["BTCUSDT"]
    expected = original - event["fee"] + (131 - p.entry) * p.qty - 131 * p.qty * c.fee_rate
    final = recovered.mark({"BTCUSDT": (131, 131)}, NOW + 300000)[0]
    assert recovered.wallet == pytest.approx(expected)
    assert final["pyramid_count"] == 1 and final["total_entry_qty"] > 10
    assert not recovered.positions


def test_testnet_phase2_rejected_before_credentials(monkeypatch):
    import vortex.testnet_runner as runner

    monkeypatch.setattr(runner, "prepare", lambda *a, **k: pytest.fail("must not access exchange"))
    result = runner._once_locked(config(), "BTCUSDT", acknowledge=True)
    assert not result["ok"] and "PAPER/BACKTEST" in result["reason"]


def test_all_phase2_env_fields_present():
    from pathlib import Path

    env = Path(".env.example").read_text()
    assert all(("PHASE2_" + f.name.upper() + "=" in env for f in fields(RiskPolicy)))


def rising_bars():
    out = []
    for i in range(80):
        px = 100 if i < 71 else {71: 112, 72: 116, 73: 121}.get(i, 122)
        if i >= 77:
            px = 131
        ts = NOW + (i - 80) * 300000
        out.append(Candle(ts, px, px + 0.1, px - 0.1, px, 100, ts + 299999, 70))
    return out


def test_historical_pyramid_and_compounding_in_both_engines(monkeypatch):
    import vortex.backtest as bt
    import vortex.portfolio as pf

    def candidate(symbol, subset, *args, **kwargs):
        if len(subset) == 70:
            return replace(signal(symbol, score=9), ts=subset[-1].ts)
        return None

    monkeypatch.setattr(bt, "analyze", candidate)
    monkeypatch.setattr(pf, "analyze", candidate)
    c = config(starting_equity=4000, fee_rate=0.0005, slippage_bps=0)
    hist = rising_bars()
    one = bt.run("BTCUSDT", hist, [], F, c)
    portfolio = pf.run_portfolio({"BTCUSDT": hist}, {"BTCUSDT": []}, {"BTCUSDT": F}, c, diagnostics=True)
    for report in (one, portfolio):
        assert len(report["pyramid_events"]) == 1
        assert report["reserved_profit"] > 0 and report["closed_trades"] == 1
        assert report["trades"][0]["pyramid_count"] == 1
        assert report["trades"][0]["net_pnl"] > 0
    assert one["wallet"] == pytest.approx(portfolio["cash_wallet"], abs=0.001)
    assert one["reserved_profit"] == pytest.approx(portfolio["reserved_profit"])
    event = portfolio["pyramid_events"][0]
    assert event["ts"] == hist[74].ts


def test_historical_correlation_blocks_second_same_side(monkeypatch):
    import vortex.portfolio as pf

    def candidate(symbol, subset, *args, **kwargs):
        if len(subset) == 70:
            price = subset[-1].close
            return replace(signal(symbol), ts=subset[-1].ts, entry=price, stop=price - 10, target=price + 30)
        return None

    monkeypatch.setattr(pf, "analyze", candidate)
    h = bars()
    report = pf.run_portfolio(
        {"BTCUSDT": h, "ETHUSDT": h}, {"BTCUSDT": [], "ETHUSDT": []}, {"BTCUSDT": F, "ETHUSDT": F}, config()
    )
    assert report["open_positions"] == ["BTCUSDT"]
    assert any(("correlated exposure" in r["reason"] for r in report["correlation_rejections"]))


def test_reserved_cash_can_block_min_notional_without_rounding_up():
    c = config(starting_equity=20)
    reserve = ProfitReserve(c, reserved=19)
    assert size_trade(signal(), reserve.capital(20, 20), c, F) is None


def test_daily_breaker_prevents_pyramid(tmp_path):
    c = config(data_dir=tmp_path, starting_equity=4000)
    b = PaperBroker(c)
    b.positions["BTCUSDT"] = position()
    b.gate.blocked = True
    h = bars()
    h[-1] = replace(h[-1], close=120)
    assert b.pyramid("BTCUSDT", 120, 120, F, {"BTCUSDT": (120, 120)}, NOW, {"BTCUSDT": h}) is None
    assert b.positions["BTCUSDT"].pyramid_count == 0


def test_correlation_future_and_constant_data_fail_closed():
    histories = {"BTCUSDT": bars(), "ETHUSDT": bars()}
    pol = RiskPolicy(enabled=True)
    future = replace(histories["ETHUSDT"][-1], ts=NOW, close_ts=NOW + 299999)
    histories["ETHUSDT"].append(future)
    assert not correlation_gate(signal("ETHUSDT"), {"BTCUSDT": position()}, histories, NOW, pol)[0]
    histories = {"BTCUSDT": [replace(b, close=100) for b in bars()], "ETHUSDT": bars()}
    assert not correlation_gate(signal("ETHUSDT"), {"BTCUSDT": position()}, histories, NOW, pol)[0]


@pytest.mark.parametrize("fraction", [0, 1])
def test_compounding_fraction_endpoints(fraction):
    c = config()
    c = replace(c, phase2=replace(c.phase2, compounding_fraction=fraction))
    r = ProfitReserve(c)
    r.record(100)
    assert r.reserved == 100 * (1 - fraction)


def test_pyramid_invalid_observation_and_exhausted_margin():
    c = config()
    p = position()
    assert pyramid_plan(p, float("nan"), NOW, c, F, 4000, 100, 1, 120) is None
    assert pyramid_plan(p, 120, NOW, c, F, 4000, 1000, 1, 120) is None
    assert pyramid_plan(p, 120, NOW, c, F, 4000, 100, 1, float("nan")) is None


def test_minute_portfolio_replays_same_add_accounting(monkeypatch):
    import vortex.portfolio as pf

    def candidate(symbol, subset, *args, **kwargs):
        if len(subset) == 70:
            return replace(signal(symbol, score=9), ts=subset[-1].ts)
        return None

    monkeypatch.setattr(pf, "analyze", candidate)
    h = rising_bars()
    minutes = []
    for b in h:
        for i in range(5):
            minutes.append(replace(b, ts=b.ts + i * 60000, close_ts=b.ts + (i + 1) * 60000 - 1))
    c = config(starting_equity=4000, slippage_bps=0)
    out = pf.run_portfolio(
        {"BTCUSDT": h},
        {"BTCUSDT": []},
        {"BTCUSDT": F},
        c,
        minute={"BTCUSDT": minutes},
        execution_interval="1m",
        diagnostics=True,
    )
    assert len(out["pyramid_events"]) == 1 and out["closed_trades"] == 1
    assert out["reserved_profit"] > 0
    assert out["pyramid_events"][0]["ts"] == h[74].ts


def test_manual_phase2_snapshot_refuses_missing_correlation_state():
    from vortex.manual_signals import make_card

    sig = replace(signal(), ts=NOW - 300000)
    with pytest.raises(ValueError, match="correlation/reserve"):
        make_card(sig, 100, 100, NOW, config(), F, equity=1000, positions=1, day_start_equity=1000)


def test_multiple_pyramids_need_spacing_and_remain_bounded():
    c = config()
    c = replace(c, phase2=replace(c.phase2, pyramid_max_adds=2))
    p = position()
    q, m, f = pyramid_plan(p, 120, NOW, c, F, 4000, 100, 1, 120)
    apply_pyramid(p, 120, q, m, f, NOW)
    assert pyramid_plan(p, 122, NOW + 600000, c, F, 4000, p.margin, 1, 122) is None
    second = pyramid_plan(p, 125, NOW + 600000, c, F, 4000, p.margin, 1, 125)
    assert second
    apply_pyramid(p, 125, *second, NOW + 600000)
    assert p.total_entry_qty <= p.initial_qty * (1 + 2 * c.phase2.pyramid_size_fraction)
    assert pyramid_plan(p, 129, NOW + 1200000, c, F, 4000, p.margin, 1, 129) is None


def test_append_failure_is_retried_before_next_exit(tmp_path, monkeypatch):
    c = config(data_dir=tmp_path, starting_equity=4000, slippage_bps=0)
    c = replace(c, phase2=replace(c.phase2, correlation_filter=False))
    b = PaperBroker(c)
    b.positions["BTCUSDT"] = position()
    h = bars()
    h[-1] = replace(h[-1], close=120)
    original = b._write_journal

    def fail(event):
        raise OSError("simulated disk error")

    monkeypatch.setattr(b, "_write_journal", fail)
    with pytest.raises(OSError):
        b.pyramid("BTCUSDT", 120, 120, F, {"BTCUSDT": (120, 120)}, NOW, {"BTCUSDT": h})
    assert b.pending_journal["kind"] == "pyramid"
    monkeypatch.setattr(b, "_write_journal", original)
    b.mark({"BTCUSDT": (131, 131)}, NOW + 600000)
    assert len((tmp_path / "pyramids.jsonl").read_text().splitlines()) == 1
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    assert b.pending_journal is None
