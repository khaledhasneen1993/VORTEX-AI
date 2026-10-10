import threading
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
