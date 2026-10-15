"""Independent 913 contract; deterministic mechanics, not performance."""

import json
from dataclasses import replace

import pytest

from vortex.approved import APPROVED_ENV, select_strategy
from vortex.basket_config import BasketPolicy
from vortex.config import Settings
from vortex.configure import configure
from vortex.models import Signal
from vortex.operations import OperationsPolicy
from vortex.paper import PaperBroker
from vortex.paper_experiment import PaperExperiment
from vortex.phase2 import RiskPolicy
from vortex.risk import Filters, RiskGate, effective_leverage
from vortex.strategy913 import IndividualLoop

FILT = Filters(0.00001, 0.00001, 5, 0.00001)


def broker(tmp_path):
    cfg = Settings(
        strategy_913_enabled=True, basket=BasketPolicy(), starting_equity=100,
        max_positions=15, max_leverage=10, paper_10x_leverage=True,
        max_margin_fraction=0.60, data_dir=tmp_path,
        experiment=PaperExperiment(enabled=True, average_enabled=False),
        phase2=RiskPolicy(pyramiding=False, correlation_filter=False),
        operations=OperationsPolicy(funding_guard=False, liquidity_guard=False,
                                    volatility_slip_factor=0, modeled_latency_ms=0),
    )
    return PaperBroker(cfg)


def entry(b, symbol="AUSDT", side="LONG", now=305000):
    s = Signal(symbol, side, 0, 10, 9.7 if side == "LONG" else 10.3, 11,
               6, "synthetic", features={"strong_signal": 0}, atr_value=0.1)
    quotes = {s: (10, 10) for s in [*b.positions, symbol]}
    return b.open(s, 10, 10, FILT, quotes, now)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("which,fraction", [("target", 0.01), ("stop", -0.05)])
def test_individual_net_margin_exit_after_costs(tmp_path, side, which, fraction):
    b = broker(tmp_path)
    assert entry(b, side=side)[0]
    p = b.positions["AUSDT"]
    assert effective_leverage(b.cfg) == 10 and p.margin == pytest.approx(10, abs=0.0001)
    margin = p.margin
    threshold = getattr(p, which)
    inside = threshold * (1 - (1 if side == "LONG" else -1) * 0.00001 * (1 if which == "target" else -1))
    assert not b.mark({"AUSDT": (inside, inside)}, 306000)
    events = b.mark({"AUSDT": (threshold, threshold)}, 307000)
    assert len(events) == 1 and not b.positions
    assert events[0]["reason"] == "913_net_margin_" + which
    assert events[0]["net_pnl"] == pytest.approx(margin * fraction, abs=1e-8)
    assert b.wallet == pytest.approx(100 + margin * fraction)
    assert PaperBroker(b.cfg).closed_count == 1


def test_one_exit_leaves_other_positions_and_forbids_adds(tmp_path):
    b = broker(tmp_path)
    assert entry(b)[0] and entry(b, "BUSDT")[0]
    target = b.positions["AUSDT"].target
    book = {"AUSDT": (target, target), "BUSDT": (10, 10)}
    assert len(b.mark(book, 306000)) == 1
    assert set(b.positions) == {"BUSDT"} and b.basket is None
    assert b.pyramid("BUSDT", 10, 10, FILT, book, 307000) is None
    assert not entry(b, "BUSDT")[0]
    with pytest.raises(ValueError, match="Missing quote"):
        b.equity({})


def test_fifteen_is_a_cap_not_unfunded_capacity(tmp_path):
    b = broker(tmp_path)
    gate = RiskGate(b.cfg, 100)
    assert gate.can_open(100, 14)[0]
    assert not gate.can_open(100, 15)[0]
    with pytest.raises(ValueError, match="Position/leverage"):
        replace(b.cfg, max_positions=16)
    for i in range(16):
        entry(b, f"S{i}USDT")
    # 60% aggregate margin and fees/capital cannot fund fifteen 10% stakes.
    assert 1 < len(b.positions) < 15
    assert sum(p.margin for p in b.positions.values()) <= b.equity({s: (10, 10) for s in b.positions}) * 0.60
    assert all(p.average_count == 0 for p in b.positions.values())


def test_policy_binding_and_default_911_are_preserved(tmp_path, monkeypatch):
    b = broker(tmp_path)
    assert entry(b)[0]
    state = json.loads(b.state_file.read_text())
    assert state["strategy_913_policy"]["target_margin"] == 0.01
    assert state["strategy_913_policy"]["stop_margin"] == 0.05
    assert PaperBroker(b.cfg).positions == b.positions
    with pytest.raises(ValueError, match="913 policy changed"):
        PaperBroker(replace(b.cfg, strategy_913_enabled=False, max_positions=5,
                            max_margin_fraction=0.25))
    monkeypatch.setattr("vortex.config.load_dotenv", lambda: None)
    for key in APPROVED_ENV:
        monkeypatch.delenv(key, raising=False)
    cfg = Settings.from_env()
    assert not cfg.strategy_913_enabled and cfg.basket.enabled and cfg.max_positions == 5
    for key, value in select_strategy(APPROVED_ENV, "913").items():
        monkeypatch.setenv(key, value)
    cfg = Settings.from_env()
    assert cfg.strategy_913_enabled and not cfg.basket.enabled and cfg.max_positions == 15
    assert not cfg.experiment.average_enabled and not cfg.phase2.pyramiding
    assert cfg.max_leverage == 10 and cfg.max_margin_fraction == 0.60
    assert cfg.phase1 == Settings.from_env().phase1
    configure(tmp_path / "913.env", 100, strategy="913")
    assert "STRATEGY_913_ENABLED='true'" in (tmp_path / "913.env").read_text()
    with pytest.raises(ValueError):
        select_strategy(APPROVED_ENV, "mainnet")


def test_913_launch_selection_and_unsafe_modes(tmp_path):
    from vortex.session import session_args
    from vortex.recorder import DataRecorder

    b = broker(tmp_path)
    assert session_args(["--strategy", "913"]).strategy == "913"
    assert session_args([]).strategy == "911"
    for changes in ({"mode": "backtest"}, {"paper_10x_leverage": False},
                    {"max_leverage": 5}, {"experiment": replace(b.cfg.experiment, average_enabled=True)},
                    {"phase2": replace(b.cfg.phase2, pyramiding=True)}):
        with pytest.raises(ValueError):
            replace(b.cfg, **changes)
    recorder = DataRecorder(b.cfg, [])
    names = [f"S{i}USDT" for i in range(45)]
    recorder.update_symbols(names)
    assert list(recorder.symbols) == names
    recorder.update_symbols([*names, "OVERUSDT"])
    assert list(recorder.symbols) == names


def test_913_minimum_liquidity_and_cost_refusal(tmp_path):
    b = broker(tmp_path)
    s = Signal("AUSDT", "LONG", 0, 10, 9, 11, 6, "synthetic", atr_value=0.1)
    assert not b.open(s, 10, 10, replace(FILT, min_notional=200), {"AUSDT": (10, 10)}, 305000)[0]
    b.cfg = replace(b.cfg, operations=replace(b.cfg.operations, liquidity_guard=True))
    assert not b.open(s, 10, 10, FILT, {"AUSDT": (10, 10)}, 305000)[0]
    b.cfg = replace(b.cfg, slippage_bps=100,
                    operations=replace(b.cfg.operations, liquidity_guard=False))
    ok, reason = b.open(s, 10, 10, FILT, {"AUSDT": (10, 10)}, 305000)
    assert not ok and "costs exhaust" in reason
    assert not b.positions and b.wallet == 100


def test_913_loop_refills_without_waiting_for_all_members(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from vortex.basket import Candidate
    b = broker(tmp_path)
    assert entry(b)[0] and entry(b, "BUSDT")[0]
    target = b.positions["AUSDT"].target
    c = Candidate(Signal("CUSDT", "LONG", 0, 10, 9, 11, 6, "synthetic", atr_value=0.1), FILT, 299999)
    loop = IndividualLoop.__new__(IndividualLoop)
    loop.broker, loop.cfg = b, b.cfg
    loop.last_scan, loop.reselect_due = 1, False
    loop.symbols, loop.use_radar, loop.histories = ["CUSDT"], False, {}
    loop.health = SimpleNamespace(row={"symbols": {}})
    book = {"AUSDT": (target, target), "BUSDT": (10, 10), "CUSDT": (10, 10)}
    def mark():
        b.mark(book, 306000)
        return 306000, book
    loop._mark = mark
    loop._scan = lambda symbols, now: [c]
    loop._guards = lambda cs: cs
    loop._quotes = lambda required: (306000, book)
    loop._report = lambda now, quotes: None
    loop.cycle()
    assert set(b.positions) == {"BUSDT", "CUSDT"}
    assert b.basket is None
    # Never send a new entry without fresh quotes for every remaining member.
    loop.last_scan = -1
    loop._mark = lambda: (605000, {"CUSDT": (10, 10)})
    loop._quotes = lambda required: (605000, {"CUSDT": (10, 10)})
    with pytest.raises(ValueError, match="Missing quote"):
        loop.cycle()


def test_913_live_loop_uses_real_execution_batch_before_broker_entry(tmp_path):
    from types import SimpleNamespace
    from vortex.basket import Candidate
    from vortex.live_scan import CandidateScanner

    b = broker(tmp_path)
    b.cfg = replace(b.cfg, operations=replace(b.cfg.operations,
                                             funding_guard=True, liquidity_guard=True))
    class Public:
        def metadata(self):
            return {"AUSDT": {}}

        def server_ms(self):
            return 305000

        def get(self, endpoint, params):
            if endpoint.endswith("/depth"):
                return {"T": 305000, "bids": [["10", "10000"]], "asks": [["10", "10000"]]}
            return {"symbol": params["symbol"], "time": 305000,
                    "lastFundingRate": "0", "nextFundingTime": 900000}

        def quotes(self, **kwargs):
            return {"AUSDT": (10, 10)}

    scanner = CandidateScanner(Public(), b.cfg, market_factory=Public)
    recorder = SimpleNamespace(status=lambda: {}, update_symbols=lambda symbols: None)
    health = SimpleNamespace(row={"symbols": {}}, update=lambda **kwargs: None)
    loop = IndividualLoop(Public(), b, scanner, None, recorder, health,
                          SimpleNamespace(count=0), ["AUSDT"], False)
    s = Signal("AUSDT", "LONG", 0, 10, 9, 11, 6, "synthetic", atr_value=0.1)
    loop._scan = lambda symbols, now: [Candidate(s, FILT, 299999)]
    try:
        loop.cycle()
        assert set(b.positions) == {"AUSDT"}
        assert b.basket is None and b.positions["AUSDT"].margin > 0
    finally:
        scanner.close()


@pytest.mark.parametrize('count', [1, 7, 15, 30])
def test_913_cli_real_guard_and_market_quote_paths_accept_multiple_candidates(tmp_path, monkeypatch, count):
    from vortex import cli, live_scan
    from vortex.basket import Candidate
    from vortex.binance import Market
    names = [f'S{i}USDT' for i in range(count)]
    b = broker(tmp_path)
    cfg = replace(b.cfg, symbols=tuple(names),
                  runtime=replace(b.cfg.runtime, recorder_enabled=False, health_enabled=False, live_resilience=True),
                  operations=replace(b.cfg.operations, funding_guard=True, liquidity_guard=True))
    required_counts = []
    limits = []
    class Public(Market):
        def __init__(self, **kwargs):
            limits.append(kwargs.get('critical_symbol_limit', 6))
            super().__init__(**kwargs)

        def metadata(self):
            return {s: {} for s in names}

        def get(self, path, params=None):
            if path.endswith('/time'):
                return {'serverTime': 305000}
            if path.endswith('/bookTicker'):
                return [{'symbol': s, 'bidPrice': '10', 'askPrice': '10', 'time': 305000} for s in names]
            if path.endswith('/depth'):
                return {'T': 305000, 'bids': [['10', '10000']], 'asks': [['10', '10000']]}
            assert path.endswith('/premiumIndex')
            return {'symbol': params['symbol'], 'time': 305000,
                    'lastFundingRate': '0', 'nextFundingTime': 900000}

        def quotes(self, **kwargs):
            required_counts.append(len(kwargs.get('required_symbols', ())))
            return super().quotes(**kwargs)

    candidates = [Candidate(Signal(s, 'LONG', 0, 10, 9, 11, 6, 'synthetic', atr_value=0.1),
                            FILT, 299999) for s in names]
    monkeypatch.setattr(cli.Settings, 'from_env', lambda: cfg)
    monkeypatch.setattr(cli, 'Market', Public)
    monkeypatch.setattr(live_scan, 'Market', Public)
    monkeypatch.setenv('USE_RADAR', 'false')
    monkeypatch.setattr(IndividualLoop, '_scan', lambda self, symbols, now: candidates)
    assert cli.main(['paper', '--once']) == 0
    restored = PaperBroker(cfg)
    assert restored.positions and len(restored.positions) <= min(count, 15)
    assert limits[0] == 15
    assert max(required_counts) == min(count, 15)
    assert restored.basket is None
