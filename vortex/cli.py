"""Command-line entrypoint: status, historical backtest, or read-only paper."""
from __future__ import annotations
import argparse
from dataclasses import replace
import os
import json
import logging
import sys
import time
from datetime import datetime, timezone
from .binance import Market, MarketError
from .config import Settings
from .paper import PaperBroker
from .backtest import run as backtest
from .strategy import analyze
from .locks import ProcessLock

log = logging.getLogger("vortex")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VORTEX AI / paper trading")
    parser.add_argument("command", choices=("paper", "backtest", "portfolio-backtest", "status", "dashboard", "reset-paper-halt", "testnet-doctor", "testnet-once", "testnet-watch", "train-ai"))
    parser.add_argument("--symbol", default="BTCUSDT", help="Backtest symbol")
    parser.add_argument("--bars", type=int, default=1200, help="Backtest candle count 300-1500")
    parser.add_argument("--days", type=int, default=None, help="Paginated backtest span 1-45 days")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle")
    parser.add_argument("--port", type=int, default=8765, help="Dashboard loopback port")
    parser.add_argument("--ack-risk", action="store_true", help="Acknowledge a manual paper risk reset")
    parser.add_argument("--ack-testnet", action="store_true", help="Acknowledge TESTNET-only order; requires matching env gate")
    parser.add_argument("--dataset", type=str, default="", help="JSONL with confirmed closed-trade labels")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
        print(json.dumps({"wallet": broker.wallet,
                          "positions": {s: vars(p) for s, p in broker.positions.items()},
                          "closed_trades": broker.closed_count, "risk_halted": broker.gate.blocked}, indent=2))
        return 0
    if args.command == "dashboard":
        from .dashboard import serve
        serve(cfg, args.port)
        return 0
    if args.command in {"testnet-doctor", "testnet-once", "testnet-watch"}:
        from .testnet_runner import prepare, doctor, once
        if args.command == "testnet-doctor":
            print(json.dumps(doctor(cfg), indent=2))
            return 0
        if args.command == "testnet-once":
            print(json.dumps(once(cfg, args.symbol, acknowledge=args.ack_testnet), indent=2))
            return 0
        if not args.ack_testnet or os.getenv("VORTEX_TESTNET_ARM") != "TESTNET_ONLY":
            raise PermissionError("Testnet watchdog requires explicit arming for emergency close")
        testnet_lock = ProcessLock(cfg.data_dir / "testnet.lock").acquire()
        api, guardian = prepare(cfg, armed=True)
        from .binance import TESTNET
        from .testnet_stages import maintain
        testnet_market = Market(base=TESTNET)
        while True:
            # TESTNET-only armed watchdog: reconcile before any partial close.
            observed = guardian.audit(may_flatten=True)
            if observed.get("phase") == "PROTECTED":
                symbol = observed["symbol"]
                fresh_quote = testnet_market.quotes()
                if symbol not in fresh_quote:
                    raise ValueError("No TESTNET bid/ask; no staged actions")
                bid, ask = fresh_quote[symbol]
                observed["management"] = maintain(guardian, bid, ask)
            print(json.dumps(observed, indent=2))
            time.sleep(10)
    market = Market()
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
        print(json.dumps(run_portfolio(data, higher, filters, cfg, macro=macro, minute=minute), indent=2))
        return 0
    if args.command == "backtest":
        if (args.days is None and not 300 <= args.bars <= 1500) or (args.days is not None and not 1 <= args.days <= 45) or args.symbol not in market.metadata():
            parser.error("bars=300..1500 and a valid futures symbol required")
        server = market.server_ms()
        bars = (market.history(args.symbol, cfg.timeframe, args.days, server) if args.days else market.candles(args.symbol, cfg.timeframe, args.bars, server))
        upper = (market.history(args.symbol, "15m", args.days, server) if args.days else market.candles(args.symbol, "15m", 1500, server))
        macro = (market.history(args.symbol, "1h", max(10, args.days), server)
                 if args.days else market.candles(args.symbol, "1h", 500, server))
        duration_days = args.days or max(1, (args.bars * (5 if cfg.timeframe == "5m" else 15) + 1439) // 1440)
        minute = market.history(args.symbol, "1m", min(45, duration_days), server)
        report = backtest(args.symbol, bars, upper, market.symbol_filters(args.symbol), cfg,
                          macro=macro, minute=minute)
        print(json.dumps(report, indent=2))
        return 0
    if cfg.mode != "paper":
        raise ValueError("paper command requires RUN_MODE=paper")
    paper_lock = ProcessLock(cfg.data_dir / "paper.lock").acquire()
    broker = PaperBroker(cfg)
    use_ai = os.getenv("USE_AI_MODEL", "false").lower() == "true"
    use_claude = os.getenv("USE_CLAUDE", "false").lower() == "true"
    ai_model = None
    if use_ai:
        from .ml import load_model
        ai_model = load_model(cfg.data_dir / "ai_model.json")  # fails closed without validated model
    use_stream = os.getenv("USE_WEBSOCKET", "false").lower() == "true"
    use_micro = os.getenv("USE_MICROSTRUCTURE", "false").lower() == "true"
    use_radar = os.getenv("USE_RADAR", "false").lower() == "true"
    if use_radar and use_stream:
        raise ValueError("Dynamic radar is incompatible with the fixed-symbol WS stream; disable one")
    stream = None
    if use_stream:
        from .stream import QuoteStream
        stream = QuoteStream(cfg.symbols)
        stream.start()
    from .alerts import notify
    from .derivatives import DerivativesTracker
    derivative_tracker = DerivativesTracker()
    symbols = [s for s in cfg.symbols if s in market.metadata()]
    if len(symbols) != len(cfg.symbols):
        raise ValueError("One or more symbols inactive / not USDT perpetuals")
    last_bucket = -1
    step = 300_000 if cfg.timeframe == "5m" else 900_000
    log.info("PAPER ONLY: no authentication, Binance orders, wallets, or API secrets")
    while True:
        try:
            now = market.server_ms()
            quotes = stream.snapshot() if stream else market.quotes(now_ms=now)
            was_halted = broker.gate.blocked
            for closed in broker.mark(quotes, now):
                log.info("CLOSED: %s", json.dumps(closed))
                notify("Closed paper trade: " + json.dumps(closed))
            equity = broker.equity(quotes)
            today = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
            broker.gate.new_day(today, equity)
            broker.gate.can_open(equity, len(broker.positions))
            if broker.gate.blocked and not was_halted:
                notify(f"RISK HALT: paper equity={equity:.2f}, consecutive_losses={broker.gate.consecutive_losses}")
                log.error("Risk circuit breaker active: no new entries")
            bucket = now // step
            # 5s into the new period; market data must have CLOSE time < server now.
            if bucket != last_bucket and now % step >= 5000:
                if use_radar:
                    from .radar import discover
                    candidates = discover(market, limit=12)
                    symbols = [candidate.symbol for candidate in candidates]
                    log.info("RADAR ranked liquid movers: %s", symbols)
                for symbol in symbols:
                    data = market.candles(symbol, cfg.timeframe, 220, now)
                    upper = market.candles(symbol, "15m", 120, now)
                    macro = market.candles(symbol, "1h", 260, now)
                    minute = market.candles(symbol, "1m", 120, now)
                    if not data or not upper or not macro:
                        continue
                    try:
                        deriv = derivative_tracker.sample(market, symbol, now)
                    except (MarketError, KeyError, ValueError) as exc:
                        log.warning("Unavailable derivative snapshot for %s: %s", symbol, exc)
                        deriv = None  # funding strategy abstains; other votes remain valid
                    signal = analyze(symbol, data, upper, cfg.min_score,
                                     macro=macro, derivatives=deriv, decision_ms=now,
                                     minute=minute)
                    if signal and symbol in quotes:
                        from .ml import feature_snapshot, evaluate
                        # Capture only features observable at this completed entry signal.
                        features = feature_snapshot(data, signal)
                        signal = replace(signal, features=features)
                        if use_ai:
                            probability = evaluate(ai_model, features)
                            if probability is None or probability < 0.56:
                                log.info("ML REJECT %s probability=%s", symbol, probability)
                                continue
                        # Never enter on an old signal (e.g. after a stalled connection).
                        if now - data[-1].close_ts > 90_000:
                            continue
                        if use_claude:
                            from .claude_review import confirm, ReviewUnavailable
                            try:
                                approved, confidence, explanation = confirm(signal)
                            except ReviewUnavailable as exc:
                                log.error("AI review unavailable: %s; skip candidate", exc)
                                continue
                            if not approved:
                                log.info("Claude rejected %s (%s): %s",
                                         symbol, confidence, explanation)
                                continue
                        if use_micro:
                            from .microstructure import collect_micro
                            micro = collect_micro(market, symbol, signal.side, now)
                            if not micro.accepted:
                                log.info("MICRO FILTER %s: %s", symbol, micro.reason)
                                continue
                        bid, ask = quotes[symbol]
                        ok, reason = broker.open(signal, bid, ask,
                                                  market.symbol_filters(symbol), quotes, now)
                        log.info("SIGNAL %s score=%s accepted=%s: %s (%s)",
                                 symbol, signal.score, ok, reason, signal.reason)
                        if ok:
                            notify(f"Paper entry: {symbol}, score={signal.score}, {reason}")
                last_bucket = bucket
            broker.save()
            log.info("PAPER equity=%.2f USDT positions=%d risk_halted=%s",
                     broker.equity(quotes), len(broker.positions), broker.gate.blocked)
        except (MarketError, ValueError, KeyError, OSError) as exc:
            # No fictitious fills and NO new trades on faulty market data.
            log.error("Cycle failed closed: %s", exc)
            if args.once:
                return 2
        if args.once:
            return 0
        time.sleep(cfg.loop_seconds)


if __name__ == "__main__":
    sys.exit(main())
