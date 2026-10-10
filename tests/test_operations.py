"""Deterministic execution/protection tests; synthetic data are not performance evidence."""

import json
import logging
from dataclasses import asdict, replace

import pytest

from vortex.alerts import detailed_event
from vortex.config import Settings
from vortex.exits import decide_tick, levels_for_bar
from vortex.models import Position, Signal
from vortex.monitoring import recent_decisions, save_telemetry
from vortex.operations import (
    DecisionJournal,
    OperationsPolicy,
    Protection,
    depth_capacity,
    funding_gate,
    historical_context,
    slippage_bps,
)
from vortex.paper import PaperBroker
from vortex.risk import Filters

NOW = 1791547200000
P = OperationsPolicy(enabled=True, funding_guard=False, liquidity_guard=False)
F = Filters(0.001, 0.001, 5.0, 0.01)


def position(side="LONG"):
    return Position(
        "BTCUSDT",
        side,
        NOW,
        100.0,
        98.0 if side == "LONG" else 102.0,
        106.0 if side == "LONG" else 94.0,
        10.0,
        0.5,
        200.0,
        initial_qty=10.0,
        initial_risk=2.0,
        peak=100.0,
        step=0.001,
        atr_value=1.0,
    )


@pytest.mark.parametrize("side,price", [("LONG", 101.6), ("SHORT", 98.4)])
def test_early_break_even_is_monotonic(side, price):
    p = position(side)
    assert decide_tick(p, price, policy=P, now_ms=NOW) is None
    assert p.stop == 100 and not p.tp1_done
    assert decide_tick(p, 100, policy=P, now_ms=NOW + 1).reason == "stop"


@pytest.mark.parametrize("side,first,second,run", [("LONG", 102, 103, 107), ("SHORT", 98, 97, 93)])
def test_30_30_40_runner_has_no_terminal_target(side, first, second, run):
    p = position(side)
    a = decide_tick(p, first, policy=P)
    assert a.qty == 3 and a.reason == "tp1"
    p.qty -= a.qty
    a = decide_tick(p, second, policy=P)
    assert a.qty == 3 and a.reason == "tp2"
    p.qty -= a.qty
    assert p.qty == 4
    assert decide_tick(p, run, policy=P) is None
    assert p.stop != 100


def test_conservative_ohlc_break_even_not_retroactive():
    p = position()
    assert levels_for_bar(p, 99.0, 101.7, 100, policy=P, now_ms=NOW) == []
    assert p.stop == 100
    assert levels_for_bar(p, 99.5, 104.0, 100.5, policy=P, now_ms=NOW + 60000)[0].reason == "stop"


def test_stop_wins_even_when_time_exit_due():
    p = position()
    result = levels_for_bar(p, 97, 105, 99, policy=P, now_ms=NOW + 3600000)
    assert result[0].reason == "stop" and result[0].price == 98


def test_time_exit_only_stagnant_trade():
    p = position()
    assert decide_tick(p, 100.2, policy=P, now_ms=NOW + 3600000).reason == "time_stagnation"
    p = position()
    p.peak = 101.2
    assert decide_tick(p, 100.2, policy=P, now_ms=NOW + 3600000) is None


def test_time_ohlc_does_not_use_unseen_current_peak():
    p = position()
    assert levels_for_bar(p, 99.5, 108, 100, policy=P, now_ms=NOW + 3600000)[0].reason == "time_stagnation"


@pytest.mark.parametrize(
    "snapshot,ok",
    [
        (None, False),
        ((NOW, 0.002, NOW + 10000), False),
        ((NOW, 0.0001, NOW + 10000), True),
        ((NOW, 0.002, NOW + 600000), True),
        ((NOW - 16000, 0.002, NOW + 600000), False),
        ((NOW + 1, 0.002, NOW + 600000), False),
    ],
)
def test_funding_timing(snapshot, ok):
    assert funding_gate(snapshot, NOW, replace(P, funding_guard=True))[0] == ok


def test_depth_requires_both_sides_fresh_inside_band():
    policy = replace(P, liquidity_guard=True)
    depth = {"T": NOW, "bids": [["99.99", "200"]], "asks": [["100.01", "200"]]}
    capacity, _ = depth_capacity(depth, 99.99, 100.01, NOW, policy)
    assert capacity == pytest.approx(399.96)
    for bad in ({**depth, "T": NOW - 16000}, {**depth, "asks": [["101", "10000"]]}, None):
        assert depth_capacity(bad, 99.99, 100.01, NOW, policy)[0] == 0


def test_slippage_increases_volatility_spread_latency_and_never_discount():
    base = slippage_bps(3, 0.01, 2, P)
    assert slippage_bps(3, 0.05, 2, P) > base
    assert slippage_bps(3, 0.01, 10, P) > base
    assert slippage_bps(3, 0.01, 2, replace(P, modeled_latency_ms=5000)) > base
    assert slippage_bps(20, 0.1, 20, replace(P, max_slippage_bps=5)) == 20
    with pytest.raises(ValueError):
        slippage_bps(3, float("nan"), 0, P)


def test_rolling_halt_survives_reload_and_window_expiry():
    guard = Protection(P)
    guard.observe(NOW, 100)
    guard.observe(NOW + 60000, 88)
    assert not guard.allow(NOW + 60000)[0]
    recovered = Protection(P, json.loads(json.dumps(guard.state())))
    recovered.observe(NOW + 10000000, 120)
    assert not recovered.allow(NOW + 10000000)[0]


def test_2h_window_and_progressive_cooldown():
    guard = Protection(P)
    guard.observe(NOW, 100)
    guard.observe(NOW + 4000000, 90)  # 1h prior peak has expired.
    assert guard.allow(NOW + 4000000)[0]
    guard.observe(NOW + 4100000, 81)
    assert guard.blocked and "2h" in guard.reason
    guard = Protection(P)
    guard.closed(-1, NOW)
    assert guard.allow(NOW)[0]
    guard.closed(-1, NOW + 1)
    assert not guard.allow(NOW + 1)[0]
    first = guard.cooldown_until
    guard.closed(-1, NOW + 2)
    assert guard.cooldown_until > first
    assert Protection(P, guard.state()).cooldown_until == guard.cooldown_until
    fast = Protection(replace(P, short_loss_cooldown=True))
    fast.closed(-1, NOW)
    fast.closed(-1, NOW)
    assert fast.cooldown_until == NOW + 10 * 60000
    assert not fast.allow(NOW + 9 * 60000)[0]
    assert fast.allow(NOW + 10 * 60000)[0]
    for _ in range(8):
        fast.closed(-1, NOW)
    assert fast.cooldown_until == NOW + 40 * 60000
    restored = Protection(fast.policy, fast.state())
    assert restored.cooldown_until == fast.cooldown_until
    restored.observe(NOW, 100)
    restored.observe(NOW + 1, 87)
    assert not restored.allow(NOW + 3 * 3600000)[0]


def test_same_clock_keeps_peak_for_drawdown():
    guard = Protection(P)
    guard.observe(NOW, 100)
    guard.observe(NOW, 80)
    assert guard.blocked


def test_paper_timing_fail_closed_and_policy_reload(tmp_path):
    cfg = Settings(data_dir=tmp_path, operations=replace(P, funding_guard=True))
    broker = PaperBroker(cfg)
    s = Signal("BTCUSDT", "LONG", NOW, 100, 98, 106, 7, "test", atr_value=1)
    ok, reason = broker.open(s, 100, 100, F, {}, NOW)
    assert not ok and "funding" in reason
    ok, _ = broker.open(s, 100, 100, F, {}, NOW, funding=(NOW, 0, NOW + 600000))
    assert ok
    assert PaperBroker(cfg).positions["BTCUSDT"].qty > 0
    with pytest.raises(ValueError, match="policy changed"):
        PaperBroker(replace(cfg, operations=replace(P, funding_guard=False)))


def test_paper_size_rejects_depth_participation(tmp_path):
    cfg = Settings(
        data_dir=tmp_path, operations=replace(P, liquidity_guard=True, max_depth_participation=0.001)
    )
    broker = PaperBroker(cfg)
    s = Signal("BTCUSDT", "LONG", NOW, 100, 98, 106, 7, "test", atr_value=1)
    depth = {"T": NOW, "bids": [["100", "110"]], "asks": [["100", "110"]]}
    ok, reason = broker.open(s, 100, 100, F, {}, NOW, depth=depth)
    assert not ok and "participation" in reason and broker.wallet == 1000


def test_profiles_focus_and_invalid_settings(monkeypatch):
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    monkeypatch.setenv("OPS_ENABLED", "true")
    monkeypatch.setenv("OPS_PROFILE", "conservative")
    monkeypatch.setenv("OPS_FOCUS_SYMBOL", "ethusdt")
    cfg = Settings.from_env()
    assert cfg.symbols == ("ETHUSDT",) and cfg.risk_per_trade <= 0.08 and cfg.max_positions <= 2
    with pytest.raises(ValueError):
        OperationsPolicy(tp1_fraction=0.5, tp2_fraction=0.5)
    monkeypatch.setenv("OPS_ENABLED", "yes")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_journal_and_readonly_telemetry(tmp_path):
    handler = DecisionJournal(tmp_path)
    handler.emit(
        logging.LogRecord("vortex.votes", logging.DEBUG, "", 0, "REJECT BTCUSDT reason=bad votes", (), None)
    )
    handler.emit(logging.LogRecord("vortex", logging.INFO, "", 0, "ACCEPT BTCUSDT", (), None))
    rows = recent_decisions(tmp_path)
    assert len(rows) == 2 and any("bad votes" in row["reason"] for row in rows)
    assert all(row["flow"] == "FLOW_DISABLED" and row["regime"] == "REGIME_DISABLED" for row in rows)
    assert {row["code"] for row in rows} == {"BAD", "SIGNAL_ACCEPTED"}
    broker = PaperBroker(Settings(data_dir=tmp_path, operations=P))
    save_telemetry(broker, {}, NOW, 1)
    state = json.loads((tmp_path / "telemetry.json").read_text())
    assert state["marked_equity"] == 1000 and state["mode"] == "PAPER"
    text = detailed_event("EXIT", {"symbol": "BTCUSDT", "stage_net_pnl": 1, "net_pnl": 3, "final": True})
    assert "stage_net_pnl: 1" in text and "net_pnl: 3" in text


def test_historical_observations_no_future_funding():
    ok, _, _, _ = historical_context(
        {("BTCUSDT", NOW): {"funding": (NOW + 1, 0, NOW + 60000)}},
        "BTCUSDT",
        NOW,
        replace(P, funding_guard=True),
    )
    assert not ok


def test_missing_history_stops_replay():
    from vortex.backtest import run

    with pytest.raises(ValueError, match="timestamped"):
        run("BTCUSDT", [], [], F, Settings(operations=replace(P, funding_guard=True)))


def test_testnet_operations_rejected_before_auth(monkeypatch):
    from vortex.testnet_runner import _once_locked

    monkeypatch.setattr("vortex.testnet_runner.prepare", lambda *_args, **_kwargs: pytest.fail("auth called"))
    assert not _once_locked(Settings(operations=P), "BTCUSDT", acknowledge=True)["ok"]


def test_stress_gap_and_comparison_require_identical_dataset():
    from research.stress_operations import compare, shocked
    from vortex.models import Candle

    bars = [Candle(NOW, 100, 101, 99, 100, 1, NOW + 59999)]
    changed = shocked(bars, NOW, -0.15)
    assert changed[0].open == 85 and bars[0].open == 100
    row = {
        "equity_with_unrealized": 20,
        "closed_trades": 0,
        "profit_factor": None,
        "max_drawdown_pct": 0,
        "open_position": False,
    }
    one = {"version": "a", "dataset_sha256": "x", "scenarios": {"base": row}}
    assert compare([one])[0]["equity"] == 20
    with pytest.raises(ValueError):
        compare([one, {**one, "dataset_sha256": "y"}])


def test_every_operations_field_has_environment_mapping(monkeypatch):
    for key, value in asdict(P).items():
        if isinstance(value, bool):
            monkeypatch.setenv("OPS_" + key.upper(), str(value).lower())
        else:
            monkeypatch.setenv("OPS_" + key.upper(), str(value))
    assert OperationsPolicy.from_env() == P


def test_paper_stagnation_close_and_protection_persist(tmp_path):
    cfg = Settings(data_dir=tmp_path, operations=P)
    broker = PaperBroker(cfg)
    s = Signal("BTCUSDT", "LONG", NOW, 100, 98, 106, 7, "test", atr_value=1)
    assert broker.open(s, 100, 100, F, {}, NOW)[0]
    events = broker.mark({"BTCUSDT": (100, 100)}, NOW + 3600000)
    assert events[0]["reason"] == "time_stagnation" and events[0]["final"]
    assert not broker.positions and PaperBroker(cfg).closed_count == 1


def test_full_profile_historical_context_allows_only_observed_inputs():
    policy = replace(P, funding_guard=True, liquidity_guard=True)
    observation = {
        "funding": (NOW, 0.0001, NOW + 600000),
        "bid": 99.99,
        "ask": 100.01,
        "depth": {"T": NOW, "bids": [["99.99", "200"]], "asks": [["100.01", "200"]]},
    }
    ok, _, capacity, spread = historical_context({("BTCUSDT", NOW): observation}, "BTCUSDT", NOW, policy)
    assert ok and capacity > 0 and spread == pytest.approx(2)
    assert not historical_context({("BTCUSDT", NOW): observation}, "BTCUSDT", NOW + 1, policy)[0]


def test_double_costs_doubles_full_slippage_model():
    original = slippage_bps(3, 0.05, 10, P)
    assert slippage_bps(3, 0.05, 10, replace(P, cost_multiplier=2)) == original * 2


def test_dashboard_exposes_risk_telemetry_and_escaped_rejections(tmp_path, monkeypatch):
    from io import BytesIO

    from vortex import dashboard

    broker = PaperBroker(Settings(data_dir=tmp_path, operations=P))
    broker.save()
    save_telemetry(broker, {}, NOW, 1)
    (tmp_path / "decisions.jsonl").write_text(json.dumps({"reason": "<script>bad</script>"}) + "\n")
    captured = {}

    class Server:
        def __init__(self, address, handler):
            assert address[0] == "127.0.0.1"
            captured["handler"] = handler

        def serve_forever(self):
            pass

    monkeypatch.setattr(dashboard, "ThreadingHTTPServer", Server)
    dashboard.serve(broker.cfg)
    handler = captured["handler"].__new__(captured["handler"])
    handler.wfile = BytesIO()
    handler.send_response = lambda *_: None
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.path = "/"
    handler.do_GET()
    page = handler.wfile.getvalue().decode()
    assert "&lt;script&gt;" in page and "<script>bad" not in page and "refresh" in page
    handler.wfile = BytesIO()
    handler.path = "/api/telemetry"
    handler.do_GET()
    assert json.loads(handler.wfile.getvalue())["marked_equity"] == 1000


def test_operations_single_and_portfolio_replay_synthetic_parity(monkeypatch):
    from vortex import backtest, portfolio
    from vortex.models import Candle

    bars = [
        Candle(NOW + i * 300000, 100, 100.5, 99.5, 100, 1000, NOW + (i + 1) * 300000 - 1) for i in range(100)
    ]

    def analyze(*args, **kwargs):
        data = args[1]
        if data[-1].ts == bars[65].ts:
            return Signal("BTCUSDT", "LONG", data[-1].ts, 100, 98, 106, 7, "synthetic test", atr_value=1)
        return None

    monkeypatch.setattr(backtest, "analyze", analyze)
    monkeypatch.setattr(portfolio, "analyze", analyze)
    cfg = Settings(operations=replace(P, stagnant_minutes=15))
    one = backtest.run("BTCUSDT", bars, bars, F, cfg)
    many = portfolio.run_portfolio({"BTCUSDT": bars}, {"BTCUSDT": bars}, {"BTCUSDT": F}, cfg)
    assert one["trades"][0]["reason"] == many["trades"][0]["reason"] == "time_stagnation"
    assert one["trades"][0]["net_pnl"] == pytest.approx(many["trades"][0]["net_pnl"], abs=1e-5)


def test_funding_timing_refresh_does_not_reset_oi_vote_interval():
    from vortex.derivatives import DerivativesTracker

    tracker = DerivativesTracker()
    tracker.last["BTCUSDT"] = (NOW - 300000, 100)

    class Market:
        def get(self, path, params):
            assert path == "/fapi/v1/premiumIndex"
            return {
                "symbol": "BTCUSDT",
                "lastFundingRate": ".001",
                "time": NOW,
                "nextFundingTime": NOW + 600000,
            }

        def server_ms(self):
            return NOW

    assert tracker.timing(Market(), "BTCUSDT") == (NOW, 0.001, NOW + 600000)
    assert tracker.last["BTCUSDT"] == (NOW - 300000, 100)


def experiment_config(path, **kw):
    from vortex.paper_experiment import PaperExperiment
    from vortex.phase2 import RiskPolicy
    return Settings(data_dir=path, starting_equity=20, experiment=PaperExperiment(enabled=True),
                    operations=P, phase2=RiskPolicy(correlation_filter=False), max_positions=5, **kw)


@pytest.mark.parametrize('side', ['LONG', 'SHORT'])
def test_experiment_full_net_margin_exit_keeps_wide_original_stop(tmp_path, side):
    from vortex.paper_experiment import net_margin_target
    cfg = experiment_config(tmp_path)
    broker = PaperBroker(cfg)
    sig = Signal('BTCUSDT', side, NOW-300000, 100, 98 if side=='LONG' else 102,
                 106 if side=='LONG' else 94, 8, 'synthetic', atr_value=1)
    assert broker.open(sig, 100, 100, F, {}, NOW)[0]
    p = broker.positions['BTCUSDT']
    sign = 1 if side == 'LONG' else -1
    assert (p.entry-p.stop)*sign == pytest.approx(p.entry*0.10)
    assert broker.mark({'BTCUSDT': (p.entry, p.entry)}, NOW+1) == []
    assert not p.tp1_done and p.stop == p.initial_stop
    slip = slippage_bps(cfg.slippage_bps, p.atr_value/p.entry, 0, cfg.operations)/10000
    target = net_margin_target(p, cfg.fee_rate, slip, cfg.experiment)
    margin = p.margin
    event = broker.mark({'BTCUSDT': (target+sign*1e-7, target+sign*1e-7)}, NOW+2)[0]
    assert event['reason'] == 'experiment_net_margin_target' and event['final']
    assert event['net_pnl'] == pytest.approx(margin*0.04, abs=1e-6)
    assert not broker.positions


def test_experiment_account_floor_persists_and_uses_initial_bankroll(tmp_path):
    cfg = experiment_config(tmp_path)
    broker = PaperBroker(cfg)
    p = position(); p.qty=0.01; p.entry_fee=0.0005; p.margin=0.2
    broker.positions['BTCUSDT'] = p
    broker.wallet = 15.0005
    # Missing position price freezes detection; never invent a flattening price.
    assert broker.mark({}, NOW) == [] and not broker.account_floor_halted
    events = broker.mark({'BTCUSDT': (100, 100)}, NOW+1)
    assert events[0]['reason'] == 'account_equity_floor'
    resumed = PaperBroker(cfg)
    assert resumed.account_floor_halted and resumed.gate.blocked and not resumed.positions
    resumed.gate.new_day('2026-10-11', 100)
    resumed.wallet=30
    assert resumed._account_floor({})
    with pytest.raises(ValueError, match='permanent'):
        resumed.reset_halt(True)
    with pytest.raises(ValueError, match='experiment policy changed'):
        PaperBroker(replace(cfg, starting_equity=21))
    with pytest.raises(ValueError):
        replace(cfg, mode='backtest')
    with pytest.raises(ValueError):
        Settings(max_positions=5)
