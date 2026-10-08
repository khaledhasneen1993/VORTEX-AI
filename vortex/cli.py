"""Command-line entrypoint: status, historical backtest, or read-only paper."""
from __future__ import annotations
import argparse
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

log = logging.getLogger("vortex")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VORTEX AI / paper trading")
    parser.add_argument("command", choices=("paper", "backtest", "status"))
    parser.add_argument("--symbol", default="BTCUSDT", help="Backtest symbol")
    parser.add_argument("--bars", type=int, default=1200, help="Backtest candle count 300-1500")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Settings.from_env()
    if args.command == "status":
        broker = PaperBroker(cfg)
        print(json.dumps({"wallet": broker.wallet,
                          "positions": {s: vars(p) for s, p in broker.positions.items()},
                          "closed_trades": broker.closed_count, "risk_halted": broker.gate.blocked}, indent=2))
        return 0
    market = Market()
    if args.command == "backtest":
        if not 300 <= args.bars <= 1500 or args.symbol not in market.metadata():
            parser.error("bars=300..1500 and a valid futures symbol required")
        server = market.server_ms()
        bars = market.candles(args.symbol, cfg.timeframe, args.bars, server)
        upper = market.candles(args.symbol, "15m", 1500, server)
        report = backtest(args.symbol, bars, upper, market.symbol_filters(args.symbol), cfg)
        print(json.dumps(report, indent=2))
        return 0
    if cfg.mode != "paper":
        raise ValueError("paper command requires RUN_MODE=paper")
    broker = PaperBroker(cfg)
    symbols = [s for s in cfg.symbols if s in market.metadata()]
    if len(symbols) != len(cfg.symbols):
        raise ValueError("One or more symbols inactive / not USDT perpetuals")
    last_bucket = -1
    step = 300_000 if cfg.timeframe == "5m" else 900_000
    log.info("PAPER ONLY: no authentication, Binance orders, wallets, or API secrets")
    while True:
        try:
            now = market.server_ms()
            quotes = market.quotes()
            for closed in broker.mark(quotes, now):
                log.info("CLOSED: %s", json.dumps(closed))
            equity = broker.equity(quotes)
            today = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
            broker.gate.new_day(today, equity)
            bucket = now // step
            # 5s into the new period; market data must have CLOSE time < server now.
            if bucket != last_bucket and now % step >= 5000:
                for symbol in symbols:
                    data = market.candles(symbol, cfg.timeframe, 220, now)
                    upper = market.candles(symbol, "15m", 120, now)
                    if not data or not upper:
                        continue
                    signal = analyze(symbol, data, upper, cfg.min_score)
                    if signal and symbol in quotes:
                        # Never enter on an old signal (e.g. after a stalled connection).
                        if now - data[-1].close_ts > 90_000:
                            continue
                        bid, ask = quotes[symbol]
                        ok, reason = broker.open(signal, bid, ask,
                                                  market.symbol_filters(symbol), quotes, now)
                        log.info("SIGNAL %s score=%s accepted=%s: %s (%s)",
                                 symbol, signal.score, ok, reason, signal.reason)
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
