"""Public Binance futures bookTicker WebSocket, stale-safe and reconnectable.

Uses updated Binance /public URL family for high-frequency bookTicker (2026). No REST fallback on stale data:
a missing/old quote is rejected rather than used for a simulated execution.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from websocket import WebSocketApp

STREAM_URL = "wss://fstream.binance.com/public/stream?streams="


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    received_monotonic: float
    exchange_ms: int | None = None


class QuoteStream:
    def __init__(
        self,
        symbols: tuple[str, ...],
        *,
        clock=time.monotonic,
        wall_ms=None,
        ws_factory=WebSocketApp,
        stale_seconds: float = 3.0,
    ):
        if not symbols or any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
            raise ValueError("Invalid stream symbols")
        if not 0.2 <= stale_seconds <= 30:
            raise ValueError("Invalid staleness bound")
        self.symbols = symbols
        self.clock = clock
        self.wall_ms = wall_ms or (lambda: int(time.time() * 1000))
        self.factory = ws_factory
        self.stale_seconds = stale_seconds
        self._quotes: dict[str, Quote] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors = 0

    @property
    def url(self):
        return STREAM_URL + "/".join(s.lower() + "@bookTicker" for s in self.symbols)

    def ingest(self, raw: str):
        data = json.loads(raw)
        if "data" in data:
            data = data["data"]
        symbol = data.get("s")
        if symbol not in self.symbols:
            return
        try:
            bid, ask = float(data["b"]), float(data["a"])
            event_ms = int(data["E"]) if "E" in data else None
        except (ValueError, TypeError, KeyError):
            return
        if not (0 < bid <= ask) or event_ms is None:
            return
        # Refuse delayed, future-dated and out-of-order exchange events.
        lag = self.wall_ms() - event_ms
        if lag < -1000 or lag > 3000:
            return
        with self._lock:
            prior = self._quotes.get(symbol)
            if prior is not None and prior.exchange_ms is not None and event_ms <= prior.exchange_ms:
                return
            self._quotes[symbol] = Quote(bid, ask, self.clock(), event_ms)

    def snapshot(self, symbols: tuple[str, ...] | None = None):
        now = self.clock()
        needed = symbols or self.symbols
        with self._lock:
            if any(
                s not in self._quotes
                or now - self._quotes[s].received_monotonic > self.stale_seconds
                or self.wall_ms() - self._quotes[s].exchange_ms > 3000
                or self.wall_ms() < self._quotes[s].exchange_ms - 1000
                for s in needed
            ):
                raise ValueError("Missing/stale WebSocket quote: refuse trading")
            return {s: (self._quotes[s].bid, self._quotes[s].ask) for s in needed}

    def _forever(self):
        attempts = 0
        while not self._stop.is_set():
            ws = self.factory(self.url, on_message=lambda _, raw: self.ingest(raw))
            try:
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                self.errors += 1
            finally:
                with self._lock:
                    self._quotes.clear()
            attempts += 1
            self._stop.wait(min(30, 2 ** min(attempts, 5)))

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._forever, daemon=True, name="vortex-ticker")
        self._thread.start()

    def stop(self):
        self._stop.set()
