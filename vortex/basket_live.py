"""Opt-in basket orchestration on existing bounded REST scanning and PAPER fills."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone

from .basket import Candidate, add_group, open_group, projected_net, strength
from .binance import MarketError
from .monitoring import save_telemetry
from .strategy import analyze

log = logging.getLogger("vortex")


class BasketLoop:
    def __init__(self, market, broker, scanner, tracker, recorder, health, journal, symbols, use_radar):
        self.market, self.broker, self.scanner, self.tracker = market, broker, scanner, tracker
        self.recorder, self.health, self.journal = recorder, health, journal
        self.cfg = broker.cfg
        self.symbols = symbols
        self.use_radar = use_radar
        self.histories = {}
        self.last_scan = -1
        self.last_exit_poll = 0.0
        self.degraded = False

    def _mark(self):
        now, quotes = self._quotes(tuple(self.broker.positions))
        self.last_exit_poll = time.monotonic()
        self.health.update(
            stage="basket_quotes",
            quotes_checked_ms=now,
            missing_quotes=[s for s in self.broker.positions if s not in quotes],
        )
        for event in self.broker.mark(quotes, now):
            log.info("CLOSED: %s", event)
        # Fresh legs above may close even when one held symbol is missing.
        equity = self.broker.equity(quotes)
        today = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
        self.broker.gate.new_day(today, equity)
        self.broker.gate.can_open(equity, len(self.broker.positions))
        self.broker.protection.observe(now, equity)
        self.broker.save()
        return now, quotes

    def _quotes(self, required):
        before = self.market.server_ms()
        quotes = self.market.quotes(now_ms=before, required_symbols=required)
        # No further network request between validated books and simulated execution.
        return getattr(self.market, "quotes_checked_ms", before), quotes

    def _wait(self):
        self.health.update(stage="basket_scan_wait")
        if self.broker.positions and time.monotonic() - self.last_exit_poll >= self.cfg.loop_seconds:
            self._mark()

    def _scan(self, symbols, now):
        """Collect then rank, retaining execution time inside the SAME 90s window."""
        ready = []
        self.recorder.update_symbols([*self.broker.positions, *symbols])
        for symbol, prepared in self.scanner.results(symbols, now, self._wait, reserve_seconds=20):
            if isinstance(prepared, Exception):
                self.degraded = True
                log.info("ENTRY_SKIP %s reason=basket_scan_data_unavailable detail=%s", symbol, prepared)
                continue
            data = prepared.data
            self.histories[symbol] = data
            checked = self.market.server_ms()
            self.health.observe(symbol, checked, prepared.funding, prepared.flow, self.cfg.phase1)
            log.info(
                "ANALYZE %s decision_ms=%d bars=%d,%d,%d,%d",
                symbol,
                checked,
                len(data),
                len(prepared.upper),
                len(prepared.macro),
                len(prepared.minute),
            )
            signal = analyze(
                symbol,
                data,
                prepared.upper,
                self.cfg.min_score,
                macro=prepared.macro,
                derivatives=prepared.derivatives,
                decision_ms=checked,
                minute=prepared.minute,
                policy=self.cfg.phase1,
                flow=prepared.flow,
                capture=True,
            )
            if (
                signal is None
                or not data
                or not 0 <= checked - data[-1].close_ts <= min(90000, self.cfg.phase1.max_signal_age_ms)
            ):
                log.info("ENTRY_SKIP %s reason=basket_strategy_or_stale_signal", symbol)
                continue
            from .signal_features import feature_snapshot

            signal = replace(signal, features={**signal.features, **feature_snapshot(data, signal)})
            ready.append(Candidate(signal, self.market.symbol_filters(symbol), data[-1].close_ts))
        return sorted(ready, key=strength)

    def _guards(self, candidates):
        guarded = []
        for c in candidates:
            self._wait()  # Protective exits also run between public guard requests.
            now = self.market.server_ms()
            if now - c.close_ms > min(85000, self.cfg.phase1.max_signal_age_ms):
                log.info("ENTRY_SKIP %s reason=basket_execution_window_exhausted", c.signal.symbol)
                break
            try:
                funding = (
                    self.tracker.timing(self.market, c.signal.symbol)
                    if self.cfg.operations.funding_guard
                    else None
                )
                depth = (
                    self.market.get("/fapi/v1/depth", {"symbol": c.signal.symbol, "limit": 100})
                    if self.cfg.operations.liquidity_guard
                    else None
                )
                guarded.append(replace(c, funding=funding, depth=depth))
            except (MarketError, KeyError, ValueError) as exc:
                self.degraded = True
                log.info("ENTRY_SKIP %s reason=basket_guard_data_unavailable detail=%s", c.signal.symbol, exc)
        return guarded

    def cycle(self):
        self.degraded = False
        now, quotes = self._mark()
        group = self.broker.basket
        if group and group["phase"] == "CLOSING":
            self._report(now, quotes)
            return
        active = bool(self.broker.positions)
        add_due = (
            active
            and not group["add_decided"]
            and now >= group["opened_ms"] + self.cfg.basket.add_after_seconds * 1000
        )
        bucket = now // 300000
        if (not active or add_due) and self.last_scan != bucket and 5000 <= now % 300000 <= 65000:
            self.last_scan = bucket
            old_id = group["id"] if active else None
            symbols = list(self.broker.positions) if active else self.symbols
            if not active and self.use_radar:
                from .radar import discover

                self.symbols = symbols = [
                    c.symbol
                    for c in discover(
                        self.market, limit=self.cfg.radar_limit, fast_ranking=self.cfg.radar_fast_ranking
                    )
                ]
                log.info("RADAR ranked liquid movers: %s", symbols)
            self.histories = {s: bars for s, bars in self.histories.items() if s in symbols}
            self.health.row["symbols"] = {
                s: row for s, row in self.health.row["symbols"].items() if s in symbols
            }
            ready = self._scan(symbols, now)
            if active:
                ready = [
                    c
                    for c in ready
                    if c.signal.symbol in self.broker.positions
                    and c.signal.side == self.broker.positions[c.signal.symbol].side
                ][:2]
            guarded = self._guards(ready)
            # A new final quote snapshot, never the book used before collection.
            required = tuple(self.broker.positions) if active else tuple(c.signal.symbol for c in guarded[:6])
            now, quotes = self._quotes(required)
            for event in self.broker.mark(quotes, now):
                log.info("CLOSED: %s", event)
            if active:
                if self.broker.positions and self.broker.basket["id"] == old_id:
                    ok, reason = add_group(self.broker, guarded, quotes, now, self.histories)
                    log.info("BASKET_ADD accepted=%s reason=%s", ok, reason)
            elif not self.broker.positions:
                ok, reason = open_group(self.broker, guarded, quotes, now, self.histories)
                log.info("BASKET_ENTRY accepted=%s reason=%s", ok, reason)
        self._report(now, quotes)

    def _report(self, now, quotes):
        save_telemetry(self.broker, quotes, now, self.journal.count)
        group = self.broker.basket
        self.health.update(
            force=True,
            stage="cycle_complete",
            status="DEGRADED" if self.degraded else "RUNNING",
            cycle_complete_ms=int(time.time() * 1000),
            recorder=self.recorder.status(),
            basket=group,
        )
        log.info(
            "PAPER equity=%.2f USDT positions=%d risk_halted=%s",
            self.broker.equity(quotes),
            len(self.broker.positions),
            self.broker.gate.blocked or self.broker.protection.blocked,
        )
        if group:
            log.info(
                "BASKET id=%s phase=%s net=%s target=%.8f deadline_ms=%d add_decided=%s",
                group["id"],
                group["phase"],
                projected_net(self.broker, quotes),
                group["total_margin"] * self.cfg.basket.profit_margin,
                group["deadline_ms"],
                group["add_decided"],
            )
