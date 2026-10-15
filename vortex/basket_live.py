"""Opt-in basket orchestration on existing bounded REST scanning and PAPER fills."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone

from .basket import (
    Candidate,
    add_group,
    open_group,
    projected_net,
    strength,
    next_add_due,
    smart_add_eligible,
    target_net,
)
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
        self.reselect_due = False
        self.last_add_scan = -1
        self.add_group_id = None
        self.prepared = {}
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
            self.prepared[symbol] = prepared
            candidate = self._evaluate(symbol, prepared, self.market.server_ms())
            if candidate:
                ready.append(candidate)
        return sorted(ready, key=strength)

    def _evaluate(self, symbol, prepared, checked):
        # Reevaluate cached CLOSED candles at actual decision time. Old flow/OI
        # must abstain under existing strategy rules; their timestamps never move.
        data = prepared.data
        self.histories[symbol] = data
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
            return None
        from .signal_features import feature_snapshot

        signal = replace(signal, features={**signal.features, **feature_snapshot(data, signal)})
        return Candidate(signal, self.market.symbol_filters(symbol), data[-1].close_ts)

    def _guards(self, candidates):
        if not candidates:
            return []
        if not self.cfg.operations.funding_guard and not self.cfg.operations.liquidity_guard:
            return candidates
        now = self.market.server_ms()
        remaining = min(90000, self.cfg.phase1.max_signal_age_ms) - (
            now - min(c.close_ms for c in candidates)
        )
        budget = min(10, max(0, (remaining - 5000) / 1000))
        lookup = {c.signal.symbol: c for c in candidates}
        guarded = []
        for symbol, result in self.scanner.execution(lookup, self._wait, budget_seconds=budget):
            if isinstance(result, Exception):
                self.degraded = True
                log.info("ENTRY_SKIP %s reason=basket_guard_data_unavailable detail=%s", symbol, result)
                continue
            funding, depth = result
            guarded.append(replace(lookup[symbol], funding=funding, depth=depth))
        return sorted(guarded, key=strength)

    def _manage_add(self, now, quotes):
        group = self.broker.basket
        due = next_add_due(self.broker)
        if due is None:
            return now, quotes
        if self.add_group_id != group["id"]:
            self.add_group_id = group["id"]
            self.prepared = {}
            self.last_add_scan = -1
        bucket = now // 300000
        # Prepare the next completed candle before the group-relative timer.
        # Entry at :01:14 means a :06:14 add, not waiting for the :10 scan.
        if due // 300000 == bucket and self.last_add_scan != bucket and 5000 <= now % 300000 <= 65000:
            self.last_add_scan = bucket
            self._scan(list(self.broker.positions), now)
            now, quotes = self._mark()
        if not self.broker.positions or group["phase"] != "ACTIVE" or now < due:
            return now, quotes
        net = projected_net(self.broker, quotes)
        ready = []
        if net is not None and (net < 0 or self.cfg.basket.smart_adds):
            for symbol, prepared in self.prepared.items():
                if symbol in self.broker.positions:
                    c = self._evaluate(symbol, prepared, now)
                    if c and c.signal.side == self.broker.positions[symbol].side:
                        if not self.cfg.basket.smart_adds or (
                            symbol in quotes
                            and smart_add_eligible(
                                self.broker, self.broker.positions[symbol], *quotes[symbol]
                            )[0]
                        ):
                            ready.append(c)
            ranked = sorted(ready, key=strength)
            ready = self._guards(ranked if self.cfg.basket.smart_adds else ranked[:2])
            now, quotes = self._quotes(tuple(self.broker.positions))
            for event in self.broker.mark(quotes, now):
                log.info("CLOSED: %s", event)
        if self.broker.positions and group["phase"] == "ACTIVE":
            ok, reason = add_group(self.broker, ready, quotes, now, self.histories)
            log.info(
                "BASKET_ADD accepted=%s reason=%s due_ms=%d delay_ms=%d", ok, reason, due, max(0, now - due)
            )
        return now, quotes

    def cycle(self):
        self.degraded = False
        was_open = bool(self.broker.positions)
        now, quotes = self._mark()
        group = self.broker.basket
        if was_open and not self.broker.positions and self.cfg.basket.rescan_after_close:
            self.reselect_due = True  # Search immediately after ALL selected members exit.
        if group and group["phase"] == "CLOSING":
            self._report(now, quotes)
            return
        active = bool(self.broker.positions)
        if active:
            now, quotes = self._manage_add(now, quotes)
            if not self.broker.positions and self.cfg.basket.rescan_after_close:
                self.reselect_due = True
            self._report(now, quotes)
            return
        bucket = now // 300000
        if self.reselect_due or (self.last_scan != bucket and 5000 <= now % 300000 <= 65000):
            self.reselect_due = False
            self.last_scan = bucket
            symbols = self.symbols
            if self.use_radar:
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
            guarded = self._guards(ready)
            # A new final quote snapshot, never the book used before collection.
            required = tuple(c.signal.symbol for c in guarded[:6])
            now, quotes = self._quotes(required)
            for event in self.broker.mark(quotes, now):
                log.info("CLOSED: %s", event)
            if not self.broker.positions:
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
                "BASKET id=%s phase=%s net=%s target=%.8f deadline_ms=%s loss_limit=%.8f add_decided=%s",
                group["id"],
                group["phase"],
                projected_net(self.broker, quotes),
                target_net(self.broker, now),
                "disabled" if self.cfg.basket.hold_until_target else group["deadline_ms"],
                self.cfg.starting_equity * self.cfg.basket.loss_starting_equity_fraction,
                group["add_decided"],
            )
