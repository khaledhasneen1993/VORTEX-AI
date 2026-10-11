"""Command-line entrypoint: adopted PAPER operation and read-only monitoring."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

from .binance import Market, MarketError
from .config import Settings
from .locks import ProcessLock
from .paper import PaperBroker
from .strategy import analyze

log = logging.getLogger("vortex")


def refresh_open_position_atr(
    market, positions, timeframe: str, now_ms: int, latest: dict[str, float], refreshed: dict[str, int]
) -> None:
    """Read latest COMPLETED ATR for every open PAPER position before exits.

    A fresh candle is fetched once per symbol and timeframe bucket. If a public
    candle request fails, the position's previous observed ATR remains in force;
    never fabricate new values or skip an executable STOP because ATR is late.
    """
    from .indicators import atr

    width = 300000 if timeframe == "5m" else 900000
    bucket = now_ms // width
    for symbol in positions:
        if refreshed.get(symbol) == bucket:
            continue
        try:
            bars = market.candles(symbol, timeframe, 70, now_ms)
            if len(bars) < 16:
                log.warning("ATR unavailable for open %s; retaining last observed ATR", symbol)
                continue
            latest[symbol] = atr(bars)
            refreshed[symbol] = bucket
        except (MarketError, ValueError) as exc:
            log.warning("ATR refresh failed for open %s: %s", symbol, exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VORTEX AI / paper trading")
    parser.add_argument(
        "command",
        choices=("paper", "status", "dashboard", "reset-paper-halt"),
    )
    parser.add_argument("--once", action="store_true", help="Run one polling cycle")
    parser.add_argument("--port", type=int, default=8765, help="Dashboard loopback port")
    parser.add_argument("--ack-risk", action="store_true", help="Acknowledge a manual paper risk reset")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.getenv("VORTEX_DIAGNOSTICS", "false").lower() == "true":
        logging.getLogger("vortex.votes").setLevel(logging.DEBUG)
    cfg = Settings.from_env()
    if args.command == "reset-paper-halt":
        with ProcessLock(cfg.data_dir / "paper.lock"):
            broker = PaperBroker(cfg)
            broker.reset_halt(args.ack_risk)
        print("Paper risk halt reset; daily loss floor remains enforced")
        return 0
    if args.command == "status":
        broker = PaperBroker(cfg, read_only=True)
        print(
            json.dumps(
                {
                    "wallet": broker.wallet,
                    "positions": {s: vars(p) for s, p in broker.positions.items()},
                    "closed_trades": broker.closed_count,
                    "risk_halted": broker.gate.blocked or broker.protection.blocked or broker.account_floor_halted,
                    "journal_recovery_pending": broker.pending_journal is not None,
                    "basket": broker.basket,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "dashboard":
        from .dashboard import serve

        serve(cfg, args.port)
        return 0
    market = Market(resilient=cfg.runtime.live_resilience)
    if cfg.mode != "paper":
        raise ValueError("paper command requires RUN_MODE=paper")
    paper_lock = ProcessLock(cfg.data_dir / "paper.lock").acquire()
    broker = PaperBroker(cfg)
    histories = {}
    latest_atr: dict[str, float] = {}
    atr_refresh_bucket: dict[str, int] = {}
    use_radar = os.getenv("USE_RADAR", "true").lower() == "true"
    if cfg.operations.enabled and cfg.operations.focus_symbol:
        use_radar = False
    stream = None
    from .alerts import detailed_event, notify
    from .operations import DecisionJournal

    decision_journal = DecisionJournal(cfg.data_dir, cfg.phase1)
    logging.getLogger("vortex").addHandler(decision_journal)
    logging.getLogger("vortex.votes").setLevel(logging.DEBUG)
    from .derivatives import DerivativesTracker

    derivative_tracker = DerivativesTracker()
    symbols = [s for s in cfg.symbols if s in market.metadata()]
    if len(symbols) != len(cfg.symbols):
        raise ValueError("One or more symbols inactive / not USDT perpetuals")
    last_bucket = -1
    step = 300000 if cfg.timeframe == "5m" else 900000
    log.info("PAPER ONLY: no authentication, Binance orders, wallets, or API secrets")
    from .recorder import DataRecorder

    recorder = DataRecorder(cfg, [*broker.positions, *symbols])
    decision_journal.decision_hook = recorder.enqueue_decision
    recorder.start()
    from .health import LiveHealth

    health = LiveHealth(cfg)
    health.update(force=True, stage="startup")
    scanner = None
    if cfg.runtime.paper_fast_scan or cfg.basket.enabled:
        from .live_scan import CandidateScanner

        scanner = CandidateScanner(market, cfg)
    basket_loop = None
    if cfg.basket.enabled:
        from .basket_live import BasketLoop

        basket_loop = BasketLoop(
            market,
            broker,
            scanner,
            derivative_tracker,
            recorder,
            health,
            decision_journal,
            symbols,
            use_radar,
        )

    def live_quotes(checked_ms, candidate=None):
        if stream:
            result = stream.snapshot()
        elif cfg.runtime.live_resilience:
            required = tuple(dict.fromkeys([*broker.positions, *([candidate] if candidate else [])]))
            result = market.quotes(now_ms=checked_ms, required_symbols=required)
        else:
            result = market.quotes(now_ms=checked_ms)
        health.update(
            quotes_checked_ms=checked_ms,
            missing_quotes=[s for s in broker.positions if s not in result],
        )
        return result

    try:
        while True:
            try:
                if basket_loop:
                    basket_loop.cycle()
                    if args.once:
                        return 0
                    time.sleep(cfg.loop_seconds)
                    continue
                cycle_degraded = False
                health.update(stage="quotes", status="RUNNING")
                recorder.update_symbols([*broker.positions, *symbols])
                now = market.server_ms()
                quotes = live_quotes(now)
                health.update(
                    quotes_checked_ms=now,
                    missing_quotes=[s for s in [*broker.positions, *symbols] if s not in quotes],
                    recorder=recorder.status(),
                    stream=stream.health() if stream else None,
                )
                refresh_open_position_atr(
                    market, broker.positions, cfg.timeframe, now, latest_atr, atr_refresh_bucket
                )
                was_halted = broker.gate.blocked or broker.protection.blocked
                for closed in broker.mark(quotes, now, latest_atr):
                    log.info("CLOSED: %s", json.dumps(closed))
                    if not cfg.operations.enabled or cfg.operations.telegram_alerts:
                        notify(detailed_event("EXIT", closed))
                equity = broker.equity(quotes)
                today = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
                broker.gate.new_day(today, equity)
                broker.gate.can_open(equity, len(broker.positions))
                broker.protection.observe(now, equity)
                broker.save()
                daily_loss = max(0.0, 1 - equity / broker.gate.day_start_equity)
                if (
                    cfg.operations.enabled
                    and cfg.operations.telegram_alerts
                    and (daily_loss >= cfg.max_daily_loss * cfg.operations.daily_warning_fraction)
                    and (broker.protection.warning_day != today)
                ):
                    notify(
                        f"PAPER daily loss warning: {daily_loss:.1%}; limit={cfg.max_daily_loss:.1%}; equity={equity:.2f}"
                    )
                    broker.protection.warning_day = today
                    broker.save()
                if (broker.gate.blocked or broker.protection.blocked) and (not was_halted):
                    if not cfg.operations.enabled or cfg.operations.telegram_alerts:
                        notify(
                            f"RISK HALT: paper equity={equity:.2f}, consecutive_losses={broker.gate.consecutive_losses}"
                        )
                    log.error("Risk circuit breaker active: no new entries")
                if cfg.phase2.enabled:
                    for sym in broker.positions:
                        old = histories.get(sym, [])
                        if not old or old[-1].close_ts // 300000 != now // 300000 - 1:
                            histories[sym] = market.candles(
                                sym, "5m", max(70, cfg.phase2.correlation_lookback + 1), now
                            )
                    for sym in list(broker.positions):
                        p = broker.positions[sym]
                        if (
                            (
                                not cfg.experiment.enabled
                                and (
                                    not cfg.phase2.pyramiding
                                    or not p.tp2_done
                                    or p.pyramid_count >= cfg.phase2.pyramid_max_adds
                                )
                            )
                            or (
                                cfg.experiment.enabled
                                and (not cfg.experiment.average_enabled or p.average_count)
                            )
                            or (not broker.protection.allow(now)[0])
                            or broker.gate.blocked
                        ):
                            continue
                        if cfg.experiment.enabled:
                            if sym not in quotes or now - p.opened_ts < 60000:
                                continue
                            raw = quotes[sym][0 if p.side == "LONG" else 1]
                            sign = 1 if p.side == "LONG" else -1
                            if (
                                raw - p.anchor_entry
                            ) * sign > -cfg.experiment.average_trigger * p.anchor_entry:
                                continue
                        if sym in quotes:
                            bid, ask = quotes[sym]
                            depth = None
                            funding = None
                            if cfg.operations.enabled:
                                funding = derivative_tracker.timing(market, sym)
                                depth = market.get("/fapi/v1/depth", {"symbol": sym, "limit": 100})
                                now = market.server_ms()
                                quotes = live_quotes(now)
                                if sym not in quotes:
                                    log.info("ENTRY_SKIP %s reason=missing_fresh_pyramid_quote", sym)
                                    continue
                                bid, ask = quotes[sym]
                            event = broker.pyramid(
                                sym,
                                bid,
                                ask,
                                market.symbol_filters(sym),
                                quotes,
                                now,
                                histories,
                                funding=funding,
                                depth=depth,
                            )
                            if event:
                                log.info("PYRAMID: %s", json.dumps(event))
                                if cfg.operations.enabled and cfg.operations.telegram_alerts:
                                    notify(detailed_event("PYRAMID", event))
                bucket = now // step
                if bucket != last_bucket and now % step >= 5000:
                    if cfg.runtime.live_resilience:
                        last_bucket = bucket  # Do not restart this scan after a data failure.
                    if use_radar:
                        from .radar import discover

                        candidates = discover(
                            market, limit=cfg.radar_limit, fast_ranking=cfg.radar_fast_ranking
                        )
                        symbols = [candidate.symbol for candidate in candidates]
                        recorder.update_symbols([*broker.positions, *symbols])
                        log.info("RADAR ranked liquid movers: %s", symbols)
                    health.row["symbols"] = {s: v for s, v in health.row["symbols"].items() if s in symbols}
                    last_exit_poll = [0.0]

                    def scan_wait():
                        health.update(stage="scan_wait")
                        if not broker.positions or time.monotonic() - last_exit_poll[0] < cfg.loop_seconds:
                            return
                        last_exit_poll[0] = time.monotonic()
                        exit_now = market.server_ms()
                        exit_quotes = live_quotes(exit_now)
                        refresh_open_position_atr(
                            market, broker.positions, cfg.timeframe, exit_now, latest_atr, atr_refresh_bucket
                        )
                        for closed in broker.mark(exit_quotes, exit_now, latest_atr):
                            log.info("CLOSED: %s", json.dumps(closed))
                            if cfg.operations.telegram_alerts:
                                notify(detailed_event("EXIT", closed))

                    candidates_ready = (
                        scanner.results(symbols, now, scan_wait) if scanner else ((s, None) for s in symbols)
                    )
                    for symbol, prepared in candidates_ready:
                        health.update(stage="scan", current_symbol=symbol)
                        if cfg.runtime.live_resilience and broker.positions:
                            exit_now = market.server_ms()
                            exit_quotes = live_quotes(exit_now)
                            for closed in broker.mark(exit_quotes, exit_now, latest_atr):
                                log.info("CLOSED: %s", json.dumps(closed))
                                if cfg.operations.telegram_alerts:
                                    notify(detailed_event("EXIT", closed))
                            # Missing another position freezes new entries; fresh exits already ran.
                            missing = [s for s in broker.positions if s not in exit_quotes]
                            if missing:
                                cycle_degraded = True
                                log.warning(
                                    "ENTRY_SKIP %s reason=missing_open_position_quote positions=%s",
                                    symbol,
                                    missing,
                                )
                                continue
                            broker.equity(exit_quotes)
                            quotes = exit_quotes
                        try:
                            if scanner:
                                if isinstance(prepared, Exception):
                                    log.info(
                                        "ENTRY_SKIP %s reason=scan_deadline_or_data_failure detail=%s",
                                        symbol,
                                        prepared,
                                    )
                                    cycle_degraded = True
                                    continue
                                data, upper, macro, minute = (
                                    prepared.data,
                                    prepared.upper,
                                    prepared.macro,
                                    prepared.minute,
                                )
                            else:
                                data = market.candles(symbol, cfg.timeframe, 220, now)
                                histories[symbol] = data
                                upper = market.candles(symbol, "15m", 120, now)
                                macro = market.candles(symbol, "1h", 260, now)
                                minute = market.candles(symbol, "1m", 120, now)
                            histories[symbol] = data
                            if not data or not upper or (not macro):
                                log.info(
                                    "ENTRY_SKIP %s reason=empty_candle_history counts=%d,%d,%d",
                                    symbol,
                                    len(data),
                                    len(upper),
                                    len(macro),
                                )
                                continue
                            from .indicators import atr

                            if len(data) >= 16:
                                latest_atr[symbol] = atr(data)
                            if scanner:
                                deriv, flow = prepared.derivatives, prepared.flow
                                derivative_tracker.funding_timing.pop(symbol, None)
                                if prepared.funding is not None:
                                    derivative_tracker.funding_timing[symbol] = prepared.funding
                                # Revalidate queued observations at actual analysis time.
                                decision_ms = market.server_ms()
                            else:
                                try:
                                    deriv = derivative_tracker.sample(market, symbol, now)
                                except (MarketError, KeyError, ValueError) as exc:
                                    log.warning("Unavailable derivative snapshot for %s: %s", symbol, exc)
                                    deriv = None
                                decision_ms = derivative_tracker.checked_ms
                                if decision_ms is None:
                                    decision_ms = market.server_ms()
                                flow = None
                                if cfg.phase1.flow_enabled:
                                    from .orderflow import collect_flow

                                    flow = collect_flow(market, symbol, decision_ms, cfg.phase1)
                                    decision_ms = market.server_ms()
                            health.observe(
                                symbol,
                                decision_ms,
                                derivative_tracker.funding_timing.get(symbol),
                                flow,
                                cfg.phase1,
                            )
                            log.info(
                                "ANALYZE %s decision_ms=%d bars=%d,%d,%d,%d",
                                symbol,
                                decision_ms,
                                len(data),
                                len(upper),
                                len(macro),
                                len(minute),
                            )
                            signal = analyze(
                                symbol,
                                data,
                                upper,
                                cfg.min_score,
                                macro=macro,
                                derivatives=deriv,
                                decision_ms=decision_ms,
                                minute=minute,
                                policy=cfg.phase1,
                                flow=flow,
                                capture=cfg.experiment.enabled and cfg.experiment.capture_enabled,
                            )
                            if signal is None:
                                log.info("ENTRY_SKIP %s reason=strategy_filters_not_satisfied", symbol)
                        except (MarketError, KeyError, ValueError) as exc:
                            if not (cfg.runtime.live_resilience or scanner):
                                raise
                            cycle_degraded = True
                            health.update(
                                force=True, status="DEGRADED", current_symbol=symbol, error=type(exc).__name__
                            )
                            log.warning("ENTRY_SKIP %s reason=candidate_data_unavailable", symbol)
                            continue
                        if signal and symbol in quotes:
                            from .signal_features import feature_snapshot

                            features = feature_snapshot(data, signal)
                            signal = replace(signal, features={**signal.features, **features})
                            if decision_ms - data[-1].close_ts > 90000:
                                log.info(
                                    "ENTRY_SKIP %s reason=stale_signal age_ms=%d",
                                    symbol,
                                    decision_ms - data[-1].close_ts,
                                )
                                continue
                            if cfg.phase2.enabled or cfg.operations.enabled:
                                now = market.server_ms()
                                quotes = live_quotes(now, symbol)
                                if symbol not in quotes or now - data[-1].close_ts > 90000:
                                    log.info("ENTRY_SKIP %s reason=stale_book_or_signal_after_scan", symbol)
                                    continue
                            bid, ask = quotes[symbol]
                            depth = None
                            if cfg.experiment.enabled and cfg.operations.funding_guard:
                                # Refresh the execution guard after queue wait. Never
                                # re-stamp cached observations or bypass freshness.
                                derivative_tracker.timing(market, symbol)
                                now = market.server_ms()
                                quotes = live_quotes(now, symbol)
                                if symbol not in quotes or now - data[-1].close_ts > 90000:
                                    log.info("ENTRY_SKIP %s reason=stale_after_funding_refresh", symbol)
                                    continue
                                bid, ask = quotes[symbol]
                            if cfg.operations.enabled and cfg.operations.liquidity_guard:
                                depth = market.get("/fapi/v1/depth", {"symbol": symbol, "limit": 100})
                                now = market.server_ms()
                                quotes = live_quotes(now, symbol)
                                if symbol not in quotes or now - data[-1].close_ts > 90000:
                                    log.info("ENTRY_SKIP %s reason=stale_after_depth_request", symbol)
                                    continue
                                bid, ask = quotes[symbol]
                            ok, reason = broker.open(
                                signal,
                                bid,
                                ask,
                                market.symbol_filters(symbol),
                                quotes,
                                now,
                                histories=histories,
                                funding=derivative_tracker.funding_timing.get(symbol),
                                depth=depth,
                            )
                            log.info(
                                "SIGNAL %s score=%s accepted=%s: %s (%s)",
                                symbol,
                                signal.score,
                                ok,
                                reason,
                                signal.reason,
                            )
                            if ok:
                                if not cfg.operations.enabled or cfg.operations.telegram_alerts:
                                    notify(
                                        detailed_event(
                                            "ENTRY", {**vars(broker.positions[symbol]), "score": signal.score}
                                        )
                                    )
                        elif signal:
                            log.info("ENTRY_SKIP %s reason=missing_fresh_quote", symbol)
                    last_bucket = bucket
                health.update(
                    force=True,
                    status="DEGRADED" if cycle_degraded else "RUNNING",
                    stage="cycle_complete",
                    cycle_complete_ms=int(time.time() * 1000),
                    recorder=recorder.status(),
                )
                broker.save()
                from .monitoring import save_telemetry

                save_telemetry(broker, quotes, now, decision_journal.count)
                log.info(
                    "PAPER equity=%.2f USDT positions=%d risk_halted=%s",
                    broker.equity(quotes),
                    len(broker.positions),
                    broker.gate.blocked,
                )
            except (MarketError, ValueError, KeyError, OSError) as exc:
                health.update(
                    force=True,
                    status="DEGRADED",
                    stage="cycle_failed",
                    error=type(exc).__name__,
                    error_detail=str(exc),
                    recorder=recorder.status(),
                )
                log.error("Cycle failed closed: %s", exc)
                if isinstance(exc, OSError):
                    # Never continue with memory diverging from an uncertain state write.
                    log.critical(
                        "Persistence failed: stopping PAPER; inspect saved state/journal before restarting"
                    )
                    return 2
                if args.once:
                    return 2
            if args.once:
                return 0
            time.sleep(cfg.loop_seconds)

    finally:
        if scanner:
            scanner.close()
        health.update(force=True, status="STOPPED", stage="shutdown")
        logging.getLogger("vortex").removeHandler(decision_journal)
        recorder.stop()
        if stream:
            stream.stop()
        health.update(force=True, status="STOPPED", stage="shutdown_complete", recorder=recorder.status())
        paper_lock.release()


if __name__ == "__main__":
    sys.exit(main())
