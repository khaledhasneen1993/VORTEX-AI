"""Opt-in bounded public-data collection; execution stays in the PAPER thread.

Each symbol owns its derivative history; each worker owns its HTTP session.
Results are consumed as ready and never extend the existing signal-age window.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

from .binance import Market, MarketError
from .derivatives import DerivativesTracker
from .orderflow import collect_flow

log = logging.getLogger("vortex")


class ScanExpired(ValueError):
    pass


@dataclass
class Prepared:
    data: list
    upper: list
    macro: list
    minute: list
    derivatives: object
    flow: object
    funding: object
    checked_ms: int


class CandidateScanner:
    def __init__(self, market, cfg, market_factory=None, clock=time.monotonic):
        self.cfg = cfg
        self.clock = clock
        self.factory = market_factory or (lambda: Market(base=market.base, resilient=True))
        self.metadata = market.metadata()
        self.pool = ThreadPoolExecutor(
            max_workers=cfg.runtime.paper_scan_workers, thread_name_prefix="vortex-scan"
        )
        self.trackers = {}
        self.inflight = {}
        self.closed = threading.Event()

    def _prepare(self, symbol, now_ms, deadline, tracker):
        market = self.factory()
        market._exchange = self.metadata  # Read-only shared metadata, independent HTTP sessions.
        try:
            return self._collect(market, symbol, now_ms, deadline, tracker)
        finally:
            if hasattr(market, "http"):
                market.http.close()

    def _collect(self, market, symbol, now_ms, deadline, tracker):
        def check():
            if self.closed.is_set() or self.clock() >= deadline:
                raise ScanExpired("scan deadline reached")

        bars = []
        for interval, limit in ((self.cfg.timeframe, 220), ("15m", 120), ("1h", 260), ("1m", 120)):
            check()
            bars.append(market.candles(symbol, interval, limit, now_ms))
        check()
        tracker.funding_timing.pop(symbol, None)
        try:
            derivatives = tracker.sample(market, symbol, now_ms)
        except (MarketError, KeyError, ValueError) as exc:
            log.warning("Unavailable derivative snapshot for %s: %s", symbol, exc)
            derivatives = None
        check()
        checked = market.server_ms()
        flow = collect_flow(market, symbol, checked, self.cfg.phase1)
        check()
        checked = market.server_ms()
        return Prepared(*bars, derivatives, flow, tracker.funding_timing.get(symbol), checked)

    def results(self, symbols, now_ms, on_wait=lambda: None):
        width = 300000 if self.cfg.timeframe == "5m" else 900000
        close_ms = now_ms // width * width - 1
        remaining = (min(90000, self.cfg.phase1.max_signal_age_ms) - (now_ms - close_ms)) / 1000
        deadline = self.clock() + max(0, remaining)
        active = set(symbols)
        self.trackers = {s: t for s, t in self.trackers.items() if s in active or s in self.inflight}
        # Retire previous late results; never allow two tasks for the same symbol.
        for symbol, future in list(self.inflight.items()):
            if future.done():
                del self.inflight[symbol]
        pending = {}
        order = {symbol: i for i, symbol in enumerate(symbols)}
        for symbol in symbols:
            if symbol in self.inflight:
                yield symbol, ScanExpired("previous collection still running")
            elif remaining <= 0:
                yield symbol, ScanExpired("completed candle already outside signal window")
            else:
                tracker = self.trackers.setdefault(symbol, DerivativesTracker())
                future = self.pool.submit(self._prepare, symbol, now_ms, deadline, tracker)
                self.inflight[symbol] = future
                pending[future] = symbol
        try:
            while pending and self.clock() < deadline and not self.closed.is_set():
                on_wait()  # Main-thread protective exits/progress remain available.
                done, _ = wait(
                    pending, timeout=min(0.25, max(0, deadline - self.clock())), return_when=FIRST_COMPLETED
                )
                for future in sorted(done, key=lambda f: order[pending[f]]):
                    symbol = pending.pop(future)
                    self.inflight.pop(symbol, None)
                    try:
                        result = future.result()
                    except (MarketError, KeyError, ValueError) as exc:
                        result = exc
                    yield symbol, result
            for future, symbol in list(pending.items()):
                future.cancel()
                yield symbol, ScanExpired("collection missed signal deadline")
        finally:
            for future in pending:
                future.cancel()  # Running read-only requests finish; their result is not traded.

    def close(self):
        self.closed.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        # Each job closes its own session after active read-only requests return.
