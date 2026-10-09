"""Offline scenario replay and version comparison. No exchange access or orders.

Dataset is user-supplied real Binance arrays, not generated candles. Synthetic
shock scenarios are explicitly labeled; none establishes a strategy's edge.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from vortex.backtest import run
from vortex.config import Settings
from vortex.models import Candle
from vortex.risk import Filters


def shocked(bars, stamp, fraction):
    # A permanent price level change creates a genuine gap from previous close.
    return [
        replace(
            b,
            open=b.open * (1 + fraction),
            high=b.high * (1 + fraction),
            low=b.low * (1 + fraction),
            close=b.close * (1 + fraction),
        )
        if b.ts >= stamp
        else b
        for b in bars
    ]


def compare(reports):
    rows = []
    for report in reports:
        for name, result in report["scenarios"].items():
            rows.append(
                {
                    "version": report["version"],
                    "dataset_sha256": report["dataset_sha256"],
                    "scenario": name,
                    "equity": result["equity_with_unrealized"],
                    "trades": result["closed_trades"],
                    "pf": result["profit_factor"],
                    "drawdown_pct": result["max_drawdown_pct"],
                    "open_position": result["open_position"],
                }
            )
    if len({r["dataset_sha256"] for r in rows}) > 1:
        raise ValueError("Version comparison requires identical source dataset hash")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path, action="append", default=[])
    parser.add_argument(
        "--incomplete-execution-model",
        action="store_true",
        help="Explicitly disable unavailable historical funding/depth guards",
    )
    args = parser.parse_args()
    cfg = Settings.from_env()
    if args.incomplete_execution_model:
        cfg = replace(cfg, operations=replace(cfg.operations, funding_guard=False, liquidity_guard=False))
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    small, higher, macro = (
        [Candle.from_binance(b) for b in dataset[key]] for key in ("small", "higher", "macro")
    )
    if len(small) < 100:
        raise ValueError("Insufficient replay bars")
    for bars, width in ((small, 300000), (higher, 900000), (macro, 3600000)):
        if any(b.ts - a.ts != width for a, b in itertools.pairwise(bars)) or any(
            b.close_ts != b.ts + width - 1 for b in bars
        ):
            raise ValueError("Missing, duplicate or invalid candle times")
    symbol = dataset["symbol"]
    filt = Filters(**dataset["filters"])
    # Worst observed return selects a stress window, never a parameter/edge test.
    crash = min(small[66:], key=lambda b: b.close / b.open - 1).ts // 3600000 * 3600000
    scenarios = {}
    for name, fee_mult, slip_mult, shock, latency in (
        ("baseline", 1, 1, 0, cfg.operations.modeled_latency_ms),
        ("double_costs", 2, 2, 0, cfg.operations.modeled_latency_ms),
        ("crash_gap_15pct", 2, 2, -0.15, 2000),
        ("up_gap_15pct", 2, 2, 0.15, 2000),
        ("slow_latency_model", 2, 2, 0, 5000),
    ):
        policy = replace(
            cfg.operations,
            modeled_latency_ms=latency,
            cost_multiplier=cfg.operations.cost_multiplier * slip_mult,
        )
        if name != "baseline" and not policy.enabled:
            raise ValueError("Stress latency model requires OPS_ENABLED=true")
        settings = replace(
            cfg, fee_rate=cfg.fee_rate * fee_mult, slippage_bps=cfg.slippage_bps, operations=policy
        )
        result = run(
            symbol,
            shocked(small, crash, shock),
            shocked(higher, crash, shock),
            filt,
            settings,
            macro=shocked(macro, crash, shock),
        )
        scenarios[name] = {
            **result,
            "synthetic_shock": shock,
            "shock_ms": crash if shock else None,
            "settings": asdict(settings),
            "latency_is_modeled_not_measured": True,
        }
    report = {
        "version": args.version,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "created_utc": datetime.now(UTC).isoformat(),
        "scenarios": scenarios,
        "source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("vortex").glob("*.py"))
        },
        "limitations": [
            "No historical funding or depth; guards must be explicitly disabled",
            "Stress scenarios are modeled, not independent out-of-sample validation",
            "No measured execution latency, funding payments or liquidation in this engine",
        ],
    }
    previous = [json.loads(path.read_text()) for path in args.compare]
    report["comparison"] = compare(previous + [report])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as f:  # Never erase evidence.
        json.dump(report, f, indent=2, default=str)
    print(args.output)


if __name__ == "__main__":
    main()
