"""Historical, read-only full calendar-month VORTEX portfolio replay.

Download verified-duration public Binance USD-M candle ZIPs, then use the
actual vortex.portfolio.run_portfolio engine (not a substitute strategy).
No private endpoints, order signing, exchange accounts, or live funds.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
from collections import defaultdict

import requests

from vortex.config import Settings
from vortex.models import Candle
from vortex.portfolio import run_portfolio
from vortex.risk import Filters


MONTH = "2026-09"
START = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000
STEP = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
# Current Binance USD-M exchangeInfo filters (snapshot, not historical).
# In the absence of archived September filters, disclosed in the report.
FILTERS = {
    "BTCUSDT": Filters(.001, .001, 50., .1),
    "ETHUSDT": Filters(.001, .001, 20., .01),
    "SOLUSDT": Filters(.01, .01, 5., .01),
    "BNBUSDT": Filters(.01, .01, 5., .01),
    "XRPUSDT": Filters(.1, .1, 5., .0001),
    "DOGEUSDT": Filters(1., 1., 5., .00001),
}


def _download(session: requests.Session, symbol: str, interval: str,
              month: str) -> tuple[list[Candle], dict]:
    url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
           f"{symbol}/{interval}/{symbol}-{interval}-{month}.zip")
    last = None
    for attempt in range(4):
        try:
            response = session.get(url, timeout=90)
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"PK"):
                raise ValueError("Not a Binance Vision zip archive")
            break
        except (requests.RequestException, ValueError) as exc:
            last = exc
            time.sleep(min(8, attempt + 1))
    else:
        raise RuntimeError(f"Historical data retrieval failed for {url}: {last}")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"Unexpected ZIP members: {url}")
        bars = []
        with archive.open(csv_names[0]) as raw:
            rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
            for row in rows:
                if not row or not row[0].strip().isdigit():
                    continue  # Binance datasets may include a CSV header
                opening = int(row[0])
                closing = int(row[6])
                # Binance Vision's older exports used ms; newer files may use us.
                if opening > 10**14:
                    opening //= 1000
                    closing //= 1000
                bars.append(Candle(opening, float(row[1]), float(row[2]),
                                   float(row[3]), float(row[4]), float(row[5]),
                                   closing))
    bars.sort(key=lambda bar: bar.ts)
    if not bars:
        raise ValueError(f"Empty historical candles: {url}")
    step = STEP[interval]
    if any(y.ts - x.ts != step for x, y in zip(bars, bars[1:])):
        raise ValueError(f"Historical gaps/duplications detected in {url}")
    meta = {"source": url, "sha256_zip": hashlib.sha256(payload).hexdigest(),
            "rows": len(bars), "first_ms": bars[0].ts, "last_ms": bars[-1].ts}
    return bars, meta


def _complete_window(bars: list[Candle], interval: str, symbol: str) -> list[Candle]:
    step = STEP[interval]
    selected = [c for c in bars if START <= c.ts < END]
    expected = (END - START) // step
    if (len(selected) != expected or not selected or selected[0].ts != START
            or selected[-1].ts != END - step
            or any(b.ts-a.ts != step for a, b in zip(selected, selected[1:]))):
        raise ValueError(f"REJECTED: incomplete September {symbol} {interval}, "
                         f"expected {expected} contiguous candles, got {len(selected)}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/backtests/september_2026.json")
    opts = parser.parse_args()
    cfg = Settings()  # frozen canonical defaults, no locally overridden .env
    if (cfg.risk_per_trade != .10 or cfg.max_daily_loss != .50
            or cfg.max_leverage != 5 or cfg.max_positions != 3):
        raise RuntimeError("Risk defaults changed: cannot silently run other settings")
    symbols = list(cfg.symbols)
    session = requests.Session()
    session.headers["User-Agent"] = "VORTEX-historical-calendar-replay/1.0 (read-only)"
    data: dict[str, list[Candle]] = {}
    higher: dict[str, list[Candle]] = {}
    macro: dict[str, list[Candle]] = {}
    minute: dict[str, list[Candle]] = {}
    sources = []
    for symbol in symbols:
        by_tf = {}
        for interval in ("5m", "15m", "1h", "1m"):
            sep, m = _download(session, symbol, interval, MONTH)
            sources.append({"symbol": symbol, "interval": interval, "month": MONTH, **m})
            sep = _complete_window(sep, interval, symbol)
            if interval == "5m":
                by_tf[interval] = sep
                continue
            august, aug_info = _download(session, symbol, interval, "2026-08")
            sources.append({"symbol": symbol, "interval": interval, "month": "2026-08",
                            **aug_info})
            warmup = {"15m": 3 * DAY, "1h": 12 * DAY, "1m": 120 * 60_000}[interval]
            seed = [c for c in august if START - warmup <= c.ts < START]
            expected = warmup // STEP[interval]
            if (len(seed) != expected or seed[0].ts != START-warmup
                    or seed[-1].ts != START - STEP[interval]):
                raise ValueError(f"REJECTED: {symbol}/{interval} August warmup missing")
            by_tf[interval] = seed + sep
        data[symbol], higher[symbol] = by_tf["5m"], by_tf["15m"]
        macro[symbol], minute[symbol] = by_tf["1h"], by_tf["1m"]
        print(f"DATA_OK {symbol}: 5m={len(data[symbol])} 15m={len(higher[symbol])}"
              f" 1h={len(macro[symbol])} 1m={len(minute[symbol])}", flush=True)

    print("BACKTEST_START 2026-09-01T00:00:00Z", flush=True)
    report = run_portfolio(data, higher, FILTERS, cfg, macro=macro, minute=minute)
    print("BACKTEST_FINISHED", flush=True)
    daily = defaultdict(lambda: {"pnl": 0., "closed_trades": 0})
    for trade in report["trades"]:
        day = datetime.fromtimestamp(trade["exit_ts"]/1000, tz=timezone.utc).date().isoformat()
        daily[day]["pnl"] += trade["net_pnl"]
        daily[day]["closed_trades"] += 1
    result = {
        "period_utc": {"start_inclusive": "2026-09-01T00:00:00Z",
                       "end_exclusive": "2026-10-01T00:00:00Z"},
        "exchange": "Binance USD-M perpetual historical OHLC (public monthly CSV)",
        "market": "PAPER BACKTEST ONLY; no signed writes",
        "git_strategy": "vortex.portfolio.run_portfolio",
        "config": {
            "starting_equity": cfg.starting_equity,
            "risk_per_trade": cfg.risk_per_trade,
            "max_leverage": cfg.max_leverage,
            "max_positions": cfg.max_positions,
            "max_margin_fraction": cfg.max_margin_fraction,
            "max_daily_loss": cfg.max_daily_loss,
            "max_consecutive_losses": cfg.max_consecutive_losses,
            "strict_votes": cfg.strict_votes,
            "min_strong_score": cfg.min_strong_score,
            "trailing_atr_mult": cfg.trailing_atr_mult,
            "timeframe": cfg.timeframe,
            "symbols": symbols
        },
        "history": {
            "complete_month_5m_per_symbol": 8640,
            "complete_month_1m_per_symbol": 43200,
            "first_5m_warmup_bars_without_entries": 65,
            "sources": sources,
            "filter_note": "Current exchangeInfo filters; historical September filters not available"
        },
        "report": report,
        "daily_closed": dict(sorted(daily.items())),
        "limitations": [
            "5m portfolio indicator warmup begins September 1 (first ~65 bars not signal-eligible)",
            "1m/15m/1h HTF candles prewarmed with actual August exchange history",
            "Historical tick-level spread/order book, funding and liquidations NOT replayed",
            "Trade fills use OHLC approximations and configured fee/slippage only",
            "No hindsight optimization or parameter tuning"
        ]
    }
    destination = Path(opts.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    summary = {
        "date": "2026-09-01 through 2026-09-30 UTC",
        "symbols": symbols,
        "start_equity": report["start_equity"],
        "end_equity": report["equity_with_unrealized"],
        "cash_wallet": report["cash_wallet"],
        "realized_net_pnl": report["realized_net_pnl"],
        "open_positions_unrealized_net": report["open_positions_unrealized_net"],
        "closed_trades": report["closed_trades"],
        "win_rate_pct": report["metrics"]["win_rate_pct"],
        "profit_factor": report["metrics"]["profit_factor"],
        "max_drawdown_pct": report["max_drawdown_pct"],
        "average_r": report["average_r"],
        "open_positions": report["open_positions"],
        "risk_halted": report["halted"],
        "total_fees": report["total_fees"],
        "sha256_report": digest,
        "report_file": str(destination),
    }
    print("MONTH_SUMMARY_JSON " + json.dumps(summary, ensure_ascii=False), flush=True)
    print("DAILY_CLOSED_JSON " + json.dumps(dict(sorted(daily.items()))), flush=True)
    print("TRADES_JSON " + json.dumps(report["trades"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
