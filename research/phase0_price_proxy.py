"""Opt-in research price-only what-if; never accepted historical execution PnL.

The production BACKTEST and PAPER fail-closed funding/depth guards remain
unchanged. This entirely separate research entry point evaluates the canonical
OHLC signal/exit engine with *explicit absent-execution-data assumptions*.
Its numbers are only hypothetical scenario outputs, NOT market-fill evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json

from vortex.backtest import run as run_single_backtest
from vortex.config import Settings
from vortex.local_data import LocalMarket, digest

MARKET_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
MISSING_DATA = (
    "historical as-of bid/ask and 20bps price-level order book (no executable fills)",
    "historical as-of funding timing/forecast and OI paired observations",
    "funding settlement cash flows and liquidation model",
    "contract filters provably effective at each simulated timestamp",
    "observed maker/taker execution mix and slippage/latency",
)


def proxy_configuration(cfg: Settings, *, doubled_costs: bool = False) -> Settings:
    """Clone configuration only; omission of unknown gates is LOCAL to this proxy."""
    if cfg.mode not in ("paper", "backtest"):
        raise ValueError("Unrecognized trading mode")
    if not cfg.operations.funding_guard or not cfg.operations.liquidity_guard:
        raise ValueError("Parent configuration must preserve funding and liquidity guards")
    ops = replace(
        cfg.operations,
        funding_guard=False,
        liquidity_guard=False,
        cost_multiplier=2.0 if doubled_costs else cfg.operations.cost_multiplier,
    )
    # No production guard, strategy, risk or user configuration is ever changed.
    return replace(
        cfg,
        mode="backtest",
        operations=ops,
        fee_rate=cfg.fee_rate * (2.0 if doubled_costs else 1.0),
    )


def measure_symbol(market, symbol, days, end_ms, settings):
    if symbol not in MARKET_SYMBOLS or days not in (30, 90):
        raise ValueError("Explicitly supported symbols and 30/90-day periods only")
    if market.server_ms() != end_ms:
        raise ValueError("Mismatched fixed sample end")
    price5 = market.history(symbol, "5m", days, end_ms)
    price15 = market.history(symbol, "15m", days, end_ms)
    price1h = market.history(symbol, "1h", days, end_ms)
    price1m = market.history(symbol, "1m", days, end_ms)
    filters = market.symbol_filters(symbol)
    src = {
        "source_file_count": len(market.sources),
        "current_filter_snapshot_sha256": digest(market.root / "exchange_info.json"),
        "official_candle_sources_verified": True,
        "historical_filter_validity_proven": False,
    }
    scenarios = {}
    for key, stress in (("ordinary_modeled_costs", False), ("doubled_modeled_costs", True)):
        cfg = proxy_configuration(settings, doubled_costs=stress)
        result = run_single_backtest(
            symbol, price5, price15, filters, cfg, macro=price1h,
            minute=price1m, execution_observations=None,
        )
        scenarios[key] = {
            "closed_trades": result["metrics"]["closed_trades"],
            "win_rate_pct": result["metrics"]["win_rate_pct"],
            "profit_factor_model": result["metrics"]["profit_factor"],
            "max_drawdown_pct_model": result["max_drawdown_pct"],
            "average_r_model": result["metrics"]["average_r"],
            "starting_virtual_equity": result["start_equity"],
            "final_wallet_virtual": result["wallet"],
            "equity_with_unrealized_virtual": result["equity_with_unrealized"],
            "open_position_at_cutoff": result["open_position"],
            "halted_model": result["halted"],
            "virtual_closed_positions": result["trades"],
            "risk_parameters_unchanged": True,
            "funding_guard_omitted_only_for_price_only_proxy": True,
            "liquidity_guard_omitted_only_for_price_only_proxy": True,
            "fee_rate_per_side_model": cfg.fee_rate,
            "assumed_slippage_base_bps": cfg.slippage_bps,
            "cost_multiplier": cfg.operations.cost_multiplier,
        }
    return {
        "kind": "historical_OHLC_only_non_executable_proxy",
        "symbol": symbol,
        "days": days,
        "end_exclusive_utc": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(),
        "source": src,
        "missing_required_data": MISSING_DATA,
        "economic_phase0_accepted": False,
        "live_guard_configuration_unchanged": True,
        "valid_real_market_fills": None,
        "warning": (
            "Proxy trade outcomes are modeled OHLC scenarios, NOT executable PnL or validated profitability. "
            "Funding/depth are unavailable and NOT inferred; their entry vetoes are omitted in this isolated "
            "research script, never in production. Historical instrument filters are current-only. "
            "OHLC bar path, portfolio correlation and position selection can alter outcomes materially."
        ),
        "scenarios": scenarios,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ohlcv-dir", required=True)
    p.add_argument("--symbol", choices=MARKET_SYMBOLS, required=True)
    p.add_argument("--days", choices=(30, 90), type=int, required=True)
    p.add_argument("--end-utc", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    end = datetime.strptime(args.end_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int(end.timestamp() * 1000)
    if args.output.exists():
        raise FileExistsError("Existing research baseline cannot be overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = Settings.from_env()
    # Mandatory provenance: reject a made-up or undocumented market filter file.
    root = Path(args.ohlcv_dir)
    exchange = root / "exchange_info.json"
    exchange_data = json.loads(exchange.read_text())
    provenance = exchange_data.get("provenance")
    if (
        not isinstance(provenance, dict)
        or provenance.get("historical_asof_proven") is not False
        or not provenance.get("original_json_sha256")
    ):
        raise ValueError("Require explicit real source provenance for current-only filters")
    report = measure_symbol(LocalMarket(root, end_ms), args.symbol, args.days, end_ms, config)
    report["original_exchange_info_source_sha256"] = provenance["original_json_sha256"]
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({
        "symbol": args.symbol, "days": args.days,
        "scenarios": {
            key: {k: v for k, v in scenario.items() if k != "virtual_closed_positions"}
            for key, scenario in report["scenarios"].items()
        },
        "economic_phase0_accepted": False,
    }, indent=2))


if __name__ == "__main__":
    main()
