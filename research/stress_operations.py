"""Internal deterministic replay comparison helpers for safety tests only."""

from dataclasses import replace

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
