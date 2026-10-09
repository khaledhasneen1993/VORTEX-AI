"""Command-line entrypoint: status, historical backtest, or read-only paper."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

from .backtest import run as backtest
from .binance import Market, MarketError
from .config import Settings
from .locks import ProcessLock
from .paper import PaperBroker
from .reports import save_report
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
        choices=(
            "paper",
            "backtest",
            "portfolio-backtest",
            "status",
            "dashboard",
            "reset-paper-halt",
            "testnet-doctor",
            "testnet-watch",
            "train-ai",
        ),
    )
    parser.add_argument("--symbol", default="BTCUSDT", help="Backtest symbol")
    parser.add_argument("--bars", type=int, default=1200, help="Backtest candle count 300-1500")
    parser.add_argument("--days", type=int, default=None, help="Paginated backtest span 1-45 days")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle")
    parser.add_argument("--port", type=int, default=8765, help="Dashboard loopback port")
    parser.add_argument("--ack-risk", action="store_true", help="Acknowledge a manual paper risk reset")
    parser.add_argument(
        "--ack-testnet",
        action="store_true",
        help="Arm TESTNET-only protection watchdog; requires matching env gate",
    )
    parser.add_argument("--dataset", type=str, default="", help="JSONL with confirmed closed-trade labels")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.getenv("VORTEX_DIAGNOSTICS", "false").lower() == "true":
        logging.getLogger("vortex.votes").setLevel(logging.DEBUG)
    cfg = Settings.from_env()
    if args.command == "train-ai":
        from pathlib import Path

        from .ml import train_jsonl

        if not args.dataset:
            parser.error("train-ai requires --dataset file.jsonl")
        print(json.dumps(train_jsonl(Path(args.dataset), cfg.data_dir / "ai_model.json"), indent=2))
        return 0
    if args.command == "reset-paper-halt":
        with ProcessLock(cfg.data_dir / "paper.lock"):
            broker = PaperBroker(cfg)
            broker.reset_halt(args.ack_risk)
        print("Paper risk halt reset; daily loss floor remains enforced")
        return 0
    if args.command == "status":
        broker = PaperBroker(cfg)
        print(
            json.dumps(
                {
                    "wallet": broker.wallet,
                    "positions": {s: vars(p) for s, p in broker.positions.items()},
                    "closed_trades": broker.closed_count,
                    "risk_halted": broker.gate.blocked,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "dashboard":
        from .dashboard import serve

        serve(cfg, args.port)
        return 0
    if args.command in {"testnet-doctor", "testnet-watch"}:
        from .testnet_runner import doctor, prepare

        if args.command == "testnet-doctor":
            print(json.dumps(doctor(cfg), indent=2))
            return 0
        if not args.ack_testnet or os.getenv("VORTEX_TESTNET_ARM") != "TESTNET_ONLY":
            raise PermissionError("Testnet watchdog requires explicit arming for emergency close")
        testnet_lock = ProcessLock(cfg.data_dir / "testnet.lock").acquire()
        api, guardian = prepare(cfg, armed=True)
        from .binance import TESTNET
        from .testnet_stages import maintain

        testnet_market = Market(base=TESTNET)
        while True:
            observed = guardian.audit(may_flatten=True)
            if observed.get("phase") == "PROTECTED":
                symbol = observed["symbol"]
                fresh_quote = testnet_market.quotes()
                if symbol not in fresh_quote:
                    raise ValueError("No TESTNET bid/ask; no staged actions")
                bid, ask = fresh_quote[symbol]
                from .indicators import atr

                now_testnet = testnet_market.server_ms()
                observed_bars = testnet_market.candles(symbol, cfg.timeframe, 60, now_testnet)
                current_atr = atr(observed_bars) if len(observed_bars) >= 16 else None
                observed["management"] = maintain(
                    guardian, bid, ask, atr_value=current_atr, trailing_atr_mult=cfg.trailing_atr_mult
                )
            print(json.dumps(observed, indent=2))
            time.sleep(10)
    market = Market()

    def output_report(report: dict, kind: str, label: str) -> None:
        path = save_report(cfg.data_dir, kind, report, symbol=label)
        metrics = report["metrics"]
        print(
            json.dumps(
                {
                    "file": str(path),
                    "closed_trades": metrics["closed_trades"],
                    "win_rate_pct": metrics["win_rate_pct"],
                    "profit_factor": metrics["profit_factor"],
                    "max_drawdown_pct": report["max_drawdown_pct"],
                    "average_r": metrics["average_r"],
                    "equity_curve": metrics["equity_curve"],
                },
                indent=2,
            )
        )

    if args.command == "portfolio-backtest":
        from .portfolio import run_portfolio

        if args.days is None or not 1 <= args.days <= 45:
            parser.error("Portfolio backtest requires --days 1..45")
        now = market.server_ms()
        data = {s: market.history(s, cfg.timeframe, args.days, now) for s in cfg.symbols}
        higher = {s: market.history(s, "15m", args.days, now) for s in cfg.symbols}
        macro = {s: market.history(s, "1h", max(10, args.days), now) for s in cfg.symbols}
        minute = {s: market.history(s, "1m", args.days, now) for s in cfg.symbols}
        filters = {s: market.symbol_filters(s) for s in cfg.symbols}
        report = run_portfolio(data, higher, filters, cfg, macro=macro, minute=minute)
        output_report(report, "portfolio", "portfolio")
        return 0
    if args.command == "backtest":
        if (
            args.days is None
            and (not 300 <= args.bars <= 1500)
            or (args.days is not None and (not 1 <= args.days <= 45))
            or args.symbol not in market.metadata()
        ):
            parser.error("bars=300..1500 and a valid futures symbol required")
        server = market.server_ms()
        bars = (
            market.history(args.symbol, cfg.timeframe, args.days, server)
            if args.days
            else market.candles(args.symbol, cfg.timeframe, args.bars, server)
        )
        upper = (
            market.history(args.symbol, "15m", args.days, server)
            if args.days
            else market.candles(args.symbol, "15m", 1500, server)
        )
        macro = (
            market.history(args.symbol, "1h", max(10, args.days), server)
            if args.days
            else market.candles(args.symbol, "1h", 500, server)
        )
        duration_days = args.days or max(1, (args.bars * (5 if cfg.timeframe == "5m" else 15) + 1439) // 1440)
        minute = market.history(args.symbol, "1m", min(45, duration_days), server)
        report = backtest(
            args.symbol, bars, upper, market.symbol_filters(args.symbol), cfg, macro=macro, minute=minute
        )
        output_report(report, "backtest", args.symbol)
        return 0
    if cfg.mode != "paper":
        raise ValueError("paper command requires RUN_MODE=paper")
    paper_lock = ProcessLock(cfg.data_dir / "paper.lock").acquire()
    broker = PaperBroker(cfg)
    histories = {}
    latest_atr: dict[str, float] = {}
    atr_refresh_bucket: dict[str, int] = {}
    use_ai = os.getenv("USE_AI_MODEL", "false").lower() == "true"
    use_claude = os.getenv("USE_CLAUDE", "false").lower() == "true"
    ai_model = None
    if use_ai:
        from .ml import load_model

        ai_model = load_model(cfg.data_dir / "ai_model.json")
    use_stream = os.getenv("USE_WEBSOCKET", "false").lower() == "true"
    use_micro = os.getenv("USE_MICROSTRUCTURE", "false").lower() == "true"
    use_radar = os.getenv("USE_RADAR", "true").lower() == "true"
    if cfg.operations.enabled and cfg.operations.focus_symbol:
        use_radar = False
    if use_radar and use_stream:
        raise ValueError("Dynamic radar is incompatible with the fixed-symbol WS stream; disable one")
    stream = None
    if use_stream:
        from .stream import QuoteStream

        stream = QuoteStream(cfg.symbols)
        stream.start()
    from .alerts import detailed_event, notify
    from .operations import DecisionJournal

    decision_journal = DecisionJournal(cfg.data_dir)
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
    while True:
        try:
            now = market.server_ms()
            quotes = stream.snapshot() if stream else market.quotes(now_ms=now)
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
                        not cfg.phase2.pyramiding
                        or not p.tp2_done
                        or p.pyramid_count >= cfg.phase2.pyramid_max_adds
                        or (not broker.protection.allow(now)[0])
                        or broker.gate.blocked
                    ):
                        continue
                    if sym in quotes:
                        bid, ask = quotes[sym]
                        depth = None
                        funding = None
                        if cfg.operations.enabled:
                            funding = derivative_tracker.timing(market, sym)
                            depth = market.get("/fapi/v1/depth", {"symbol": sym, "limit": 100})
                            now = market.server_ms()
                            quotes = stream.snapshot() if stream else market.quotes(now_ms=now)
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
                if use_radar:
                    from .radar import discover

                    candidates = discover(market, limit=24)
                    symbols = [candidate.symbol for candidate in candidates]
                    log.info("RADAR ranked liquid movers: %s", symbols)
                for symbol in symbols:
                    data = market.candles(symbol, cfg.timeframe, 220, now)
                    histories[symbol] = data
                    upper = market.candles(symbol, "15m", 120, now)
                    macro = market.candles(symbol, "1h", 260, now)
                    minute = market.candles(symbol, "1m", 120, now)
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
                    try:
                        deriv = derivative_tracker.sample(market, symbol, now)
                    except (MarketError, KeyError, ValueError) as exc:
                        log.warning("Unavailable derivative snapshot for %s: %s", symbol, exc)
                        deriv = None
                    decision_ms = derivative_tracker.checked_ms
                    if decision_ms is None:
                        decision_ms = market.server_ms()
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
                    )
                    if signal is None:
                        log.info("ENTRY_SKIP %s reason=strategy_filters_not_satisfied", symbol)
                    if signal and symbol in quotes:
                        from .ml import evaluate, feature_snapshot

                        features = feature_snapshot(data, signal)
                        signal = replace(signal, features={**signal.features, **features})
                        if use_ai:
                            probability = evaluate(ai_model, features)
                            if probability is None or probability < 0.56:
                                log.info("ML REJECT %s probability=%s", symbol, probability)
                                continue
                        if decision_ms - data[-1].close_ts > 90000:
                            log.info(
                                "ENTRY_SKIP %s reason=stale_signal age_ms=%d",
                                symbol,
                                decision_ms - data[-1].close_ts,
                            )
                            continue
                        if use_claude:
                            from .claude_review import ReviewUnavailable, confirm

                            try:
                                approved, confidence, explanation = confirm(signal)
                            except ReviewUnavailable as exc:
                                log.error("AI review unavailable: %s; skip candidate", exc)
                                continue
                            if not approved:
                                log.info("Claude rejected %s (%s): %s", symbol, confidence, explanation)
                                continue
                        if use_micro:
                            from .microstructure import collect_micro

                            micro = collect_micro(market, symbol, signal.side, now)
                            if not micro.accepted:
                                log.info("MICRO FILTER %s: %s", symbol, micro.reason)
                                continue
                        if cfg.phase2.enabled or cfg.operations.enabled:
                            now = market.server_ms()
                            quotes = stream.snapshot() if stream else market.quotes(now_ms=now)
                            if symbol not in quotes or now - data[-1].close_ts > 90000:
                                log.info("ENTRY_SKIP %s reason=stale_book_or_signal_after_scan", symbol)
                                continue
                        bid, ask = quotes[symbol]
                        depth = None
                        if cfg.operations.enabled and cfg.operations.liquidity_guard:
                            depth = market.get("/fapi/v1/depth", {"symbol": symbol, "limit": 100})
                            now = market.server_ms()
                            quotes = stream.snapshot() if stream else market.quotes(now_ms=now)
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
            log.error("Cycle failed closed: %s", exc)
            if args.once:
                return 2
        if args.once:
            return 0
        time.sleep(cfg.loop_seconds)


if __name__ == "__main__":
    sys.exit(main())
