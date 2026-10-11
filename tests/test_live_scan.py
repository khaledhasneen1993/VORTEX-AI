import threading
import pytest
from dataclasses import replace

from vortex.config import Settings
from vortex.live_scan import CandidateScanner, Prepared, ScanExpired
from vortex.runtime_config import RuntimePolicy
from vortex.paper import PaperBroker


def test_ready_symbol_not_held_behind_slow_symbol_and_no_shared_tracker():
    blocked = threading.Event()
    cfg = Settings(
        symbols=("ETHUSDT", "BTCUSDT"), runtime=RuntimePolicy(paper_fast_scan=True, paper_scan_workers=2)
    )

    class Public:
        def metadata(self):
            return {s: {} for s in cfg.symbols}

        def candles(self, symbol, interval, limit, now):
            if symbol == "ETHUSDT":
                assert blocked.wait(2)
            return []

        def server_ms(self):
            return 300010

        def get(self, path, params):
            return {
                "symbol": params["symbol"],
                "time": 300010,
                "lastFundingRate": "0.0",
                "openInterest": "100",
                "markPrice": "100",
                "nextFundingTime": 600000,
            }

    scanner = CandidateScanner(Public(), cfg, market_factory=Public)
    try:
        result = scanner.results(list(cfg.symbols), 300010)
        symbol, prepared = next(result)
        assert symbol == "BTCUSDT" and isinstance(prepared, Prepared)
        blocked.set()
        rest = list(result)
        assert rest[0][0] == "ETHUSDT"
        assert scanner.trackers["BTCUSDT"] is not scanner.trackers["ETHUSDT"]
        assert list(scanner.trackers["BTCUSDT"].last) == ["BTCUSDT"]
        assert list(scanner.trackers["ETHUSDT"].last) == ["ETHUSDT"]
    finally:
        blocked.set()
        scanner.close()


def test_deadline_cancels_collection_without_extending_signal_age():
    clock = [0.0]
    cfg = Settings(symbols=("BTCUSDT",), runtime=RuntimePolicy(paper_fast_scan=True, paper_scan_workers=1))

    class Public:
        def metadata(self):
            return {"BTCUSDT": {}}

        def candles(self, *args):
            clock[0] += 30
            return []

    scanner = CandidateScanner(Public(), cfg, market_factory=Public, clock=lambda: clock[0])
    try:
        results = list(scanner.results(["BTCUSDT"], 300010))
        assert isinstance(results[0][1], ScanExpired)
        assert clock[0] <= 90
    finally:
        scanner.close()


def test_fast_scan_is_off_default_and_bound_to_saved_policy(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    assert not cfg.runtime.paper_fast_scan
    broker = PaperBroker(cfg)
    broker.save()
    fast = replace(cfg, runtime=RuntimePolicy(paper_fast_scan=True))
    import pytest

    with pytest.raises(ValueError, match="Entry policy changed"):
        PaperBroker(fast)


@pytest.mark.parametrize("experiment", [False, True])
@pytest.mark.parametrize("resilient", [False, True])
def test_paper_cli_uses_prepared_data_and_shuts_down_scanner(tmp_path, monkeypatch, experiment, resilient):
    from vortex import cli, live_scan
    from vortex.models import Candle, Signal
    from vortex.paper_experiment import PaperExperiment
    from vortex.operations import OperationsPolicy
    from vortex.risk import Filters

    cfg = Settings(
        symbols=("BTCUSDT",),
        data_dir=tmp_path,
        runtime=RuntimePolicy(paper_fast_scan=True, live_resilience=resilient),
    )
    if experiment:
        cfg = replace(
            cfg, experiment=PaperExperiment(enabled=True), operations=OperationsPolicy(liquidity_guard=False)
        )
    monkeypatch.setattr(cli.Settings, "from_env", lambda: cfg)
    monkeypatch.setenv("USE_RADAR", "false")
    monkeypatch.setenv("USE_WEBSOCKET", "false")
    monkeypatch.setenv("USE_AI_MODEL", "false")
    monkeypatch.setenv("USE_CLAUDE", "false")

    class Public:
        def __init__(self, **kwargs):
            pass

        def metadata(self):
            return {"BTCUSDT": {}}

        def server_ms(self):
            return 305010

        def quotes(self, **kwargs):
            state.setdefault("required", []).append(kwargs.get("required_symbols", ()))
            return {"BTCUSDT": (100, 100.01)}

        def candles(self, *args):
            raise AssertionError("duplicate main-thread collection")

        def symbol_filters(self, symbol):
            return Filters(0.001, 0.001, 5, 0.01)

        def get(self, endpoint, params):
            assert experiment and endpoint == "/fapi/v1/premiumIndex"
            state["funding_refreshed"] = True
            return dict(symbol="BTCUSDT", lastFundingRate="0", time=305000, nextFundingTime=900000)

    state = {"closed": False, "analyzed": 0}
    bar = Candle(0, 100, 101, 99, 100, 100, close_ts=299999)

    class Scanner:
        def __init__(self, *args):
            pass

        def results(self, symbols, now, on_wait):
            on_wait()
            yield "BTCUSDT", Prepared([bar], [bar], [bar], [bar], None, None, None, 305010)

        def close(self):
            state["closed"] = True

    def analyze(*args, **kwargs):
        state["analyzed"] += 1
        if experiment:
            assert kwargs["capture"]
            return Signal("BTCUSDT", "LONG", 0, 100, 98, 106, 8, "synthetic", atr_value=1)
        return None

    monkeypatch.setattr(cli, "Market", Public)
    monkeypatch.setattr(live_scan, "CandidateScanner", Scanner)
    monkeypatch.setattr(cli, "analyze", analyze)
    if experiment:
        monkeypatch.setattr("vortex.signal_features.feature_snapshot", lambda *args: {})
    assert cli.main(["paper", "--once"]) == 0
    assert state["closed"] and state["analyzed"] == 1
    if experiment:
        assert state["funding_refreshed"]
        if resilient:
            assert ("BTCUSDT",) in state["required"]
        assert "BTCUSDT" in PaperBroker(cfg).positions
    assert (tmp_path / "paper_state.json").exists()


def test_basket_execution_batch_is_parallel_bounded_and_keeps_exchange_timestamps():
    from vortex.basket_config import BasketPolicy
    from vortex.paper_experiment import PaperExperiment

    cfg = Settings(
        basket=BasketPolicy(enabled=True),
        experiment=PaperExperiment(enabled=True, capture_enabled=True),
        max_positions=5,
        max_margin_fraction=0.6,
        runtime=RuntimePolicy(paper_fast_scan=True, paper_scan_workers=2),
    )
    mutex, together = threading.Lock(), threading.Barrier(2)
    state = {"active": 0, "peak": 0, "closed": 0, "sessions": []}

    class Public:
        def __init__(self):
            self.calls = []
            self.http = self

        def metadata(self):
            return {s: {} for s in cfg.symbols}

        def get(self, path, params):
            self.calls.append(path)
            if path.endswith("/depth"):
                with mutex:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                together.wait(timeout=2)
                with mutex:
                    state["active"] -= 1
                return {"T": 305000, "bids": [["100", "1000"]], "asks": [["100.01", "1000"]]}
            return {
                "symbol": params["symbol"],
                "time": 305000,
                "lastFundingRate": "0",
                "nextFundingTime": 900000,
            }

        def server_ms(self):
            return 305000

        def close(self):
            with mutex:
                state["closed"] += 1
                state["sessions"].append(self)

    scanner = CandidateScanner(Public(), cfg, market_factory=Public)
    try:
        result = dict(scanner.execution(cfg.symbols))
        assert len(result) == 6 and state["peak"] == 2 and state["closed"] == 6
        assert len({id(s) for s in state["sessions"]}) == 6
        assert all(s.calls == ["/fapi/v1/depth", "/fapi/v1/premiumIndex"] for s in state["sessions"])
        assert all(snapshot[0] == (305000, 0, 900000) for snapshot in result.values())
    finally:
        scanner.close()


def test_execution_deadline_and_stale_funding_never_create_fresh_observations():
    from vortex.basket_config import BasketPolicy
    from vortex.paper_experiment import PaperExperiment

    cfg = Settings(
        basket=BasketPolicy(enabled=True),
        experiment=PaperExperiment(enabled=True, capture_enabled=True),
        max_positions=5,
        max_margin_fraction=0.6,
        runtime=RuntimePolicy(paper_fast_scan=True, paper_scan_workers=1),
    )
    clock = [0.0]
    delayed = [False]

    class Public:
        def metadata(self):
            return {"BTCUSDT": {}}

        def get(self, path, params):
            if delayed[0]:
                clock[0] += 6
            if path.endswith("/depth"):
                return {"T": 305000, "bids": [], "asks": []}
            return {"symbol": "BTCUSDT", "time": 285000, "lastFundingRate": "0", "nextFundingTime": 900000}

        def server_ms(self):
            return 305000

    scanner = CandidateScanner(Public(), cfg, market_factory=Public, clock=lambda: clock[0])
    try:
        result = list(scanner.execution(["BTCUSDT"]))
        assert result[0][1][0] is None  # Old exchange funding stays unavailable.
        delayed[0] = True
        result = list(scanner.execution(["BTCUSDT"]))
        assert isinstance(result[0][1], ScanExpired)
    finally:
        scanner.close()
