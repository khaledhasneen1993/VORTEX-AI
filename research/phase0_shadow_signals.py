"""Opt-in OHLC-only shadow audit. Measures canonical signals, NEVER executes or reports trade PnL.

Future prices are read only after a canonical decision and only for descriptive
shadow outcomes. No historical funding, order book, fills or acceptance is invented.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from vortex.config import Settings
from vortex.local_data import LocalMarket
from vortex.strategy import analyze

DAY_MS = 86_400_000
HORIZON = 12  # Completed 5-minute bars; one hour of forward market movement.


def future_market_move(bars, index, horizon=HORIZON):
    """Future *market movement*, never a trade fill or PnL.

    A missing future bar is unknown. Never borrow out-of-window prices.
    """
    if horizon <= 0:
        raise ValueError("Horizon must be positive")
    if index < 0 or index + horizon >= len(bars):
        return None
    entry, end = bars[index], bars[index + horizon]
    if entry.close <= 0 or end.close <= 0 or end.ts - entry.ts != 300000 * horizon:
        return None
    return round(100 * (end.close / entry.close - 1), 8)


def audit_symbol(market, symbol, days, end_ms, output, cfg=None):
    """Isolated per-symbol measurement; no broker, risk-gate bypass or orders."""
    if days not in (30, 90) or market.server_ms() != end_ms:
        raise ValueError("30/90-day fixed-UTC local archives only")
    cfg = cfg or Settings()
    if cfg.timeframe != "5m":
        raise ValueError("Shadow tool only supports the unchanged 5m strategy")
    output = Path(output)
    if output.exists() or output.with_suffix(".summary.json").exists():
        raise FileExistsError("Shadow outputs are append-protected; use a new filename")
    output.parent.mkdir(parents=True, exist_ok=True)

    candles = market.history(symbol, "5m", days, end_ms)
    higher = market.history(symbol, "15m", days, end_ms)
    macro = market.history(symbol, "1h", days, end_ms)
    minute = market.history(symbol, "1m", days, end_ms)
    # These are source candle closing timestamps, not future insights.
    hclose = [bar.close_ts for bar in higher]
    mclose = [bar.close_ts for bar in macro]
    minuteclose = [bar.close_ts for bar in minute]
    start_ms = end_ms - days * DAY_MS
    reasons = Counter()
    total = accepted = forward_measured = 0
    with output.open("x", encoding="utf-8") as stream:
        for i, candle in enumerate(candles):
            if not start_ms <= candle.ts < end_ms:
                continue
            h = bisect_right(hclose, candle.close_ts)
            m = bisect_right(mclose, candle.close_ts)
            n = bisect_right(minuteclose, candle.close_ts)
            decisions = []
            signal = analyze(
                symbol,
                candles[max(0, i - 219):i + 1],
                higher[max(0, h - 120):h],
                cfg.min_score,
                macro=macro[max(0, m - 250):m],
                minute=minute[max(0, n - 90):n],
                decision_ms=candle.close_ts,
                policy=cfg.phase1,
                derivatives=None,  # Missing as-of funding/OI never becomes a vote.
                audit=decisions.append,
            )
            if len(decisions) != 1:
                raise RuntimeError("Canonical strategy failed to publish exactly one decision")
            row = decisions[0]
            if row["accepted"] != (signal is not None):
                raise RuntimeError("Canonical audit disagrees with strategy")
            move = future_market_move(candles, i)
            # Never cross fixed evaluation-window end when attaching forward observations.
            if i + HORIZON < len(candles) and candles[i + HORIZON].ts >= end_ms:
                move = None
            row["shadow_outcome"] = {
                "horizon_minutes": 60,
                "forward_market_return_pct": move,
                "accepted_signal_directional_return_pct": (
                    round(move if signal.side == "LONG" else -move, 8)
                    if move is not None and signal is not None else None
                ),
                "trade_pnl": None,
                "trade_fill": None,
            }
            row["shadow_status"] = (
                "observed_forward_price_only_not_execution" if move is not None
                else "insufficient_forward_window"
            )
            row["scope"] = "historical_ohlcv_signal_only"
            row["asof_derivatives_available"] = False
            row["execution_book_available"] = False
            row["financial_validation"] = False
            stream.write(json.dumps(row, allow_nan=False, sort_keys=True) + "\n")
            total += 1
            accepted += bool(signal)
            forward_measured += move is not None
            if not signal:
                reasons[str(row["veto_reason"])] += 1
    checksum = sha256()
    with output.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            checksum.update(chunk)
    summary = {
        "scope": "historical_ohlcv_signal_only",
        "symbol": symbol,
        "days": days,
        "start_utc": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
        "end_exclusive_utc": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(),
        "decisions": total,
        "canonical_strategy_signals": accepted,
        "vetoed": total - accepted,
        "forward_market_moves_observed": forward_measured,
        "veto_reasons": dict(sorted(reasons.items())),
        "jsonl_sha256": checksum.hexdigest(),
        "archive_sources_sha256": {
            k: v.get("csv_sha256", v.get("sha256")) for k, v in sorted(market.sources.items())
        },
        "economic_baseline": False,
        "closed_trades": None,
        "profit_factor": None,
        "net_pnl": None,
        "max_drawdown": None,
        "missing": [
            "as-of funding/OI/forecast signal observations",
            "historical bid-ask quotes and near-price order-book levels",
            "execution/fill/liquidation validation and funding settlement",
            "historically effective exchange contract filters",
        ],
        "warning": (
            "Forward returns describe subsequent OHLC market movement only; they do not "
            "establish executable entries, profitability, or causal voter attribution."
        ),
    }
    output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlcv-dir", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--days", required=True, type=int, choices=(30, 90))
    parser.add_argument("--end-utc", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        end = datetime.strptime(args.end_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        parser.error("--end-utc must be YYYY-MM-DD")
    result = audit_symbol(
        LocalMarket(args.ohlcv_dir, int(end.timestamp() * 1000)),
        args.symbol, args.days, int(end.timestamp() * 1000), args.output
    )
    print(json.dumps({key: val for key, val in result.items() if key != "archive_sources_sha256"}, indent=2))


if __name__ == "__main__":
    main()
