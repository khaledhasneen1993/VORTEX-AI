"""Auditable backtest summaries and atomic on-disk JSON reports."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def summary(trades: list[dict], curve: list[dict]) -> dict:
    pnl = [float(t["net_pnl"]) for t in trades]
    wins = sum(x > 0 for x in pnl)
    gains = sum(x for x in pnl if x > 0)
    losses = -sum(x for x in pnl if x < 0)
    ratios = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    peak, drawdown = (float(curve[0]["equity"]), 0.0) if curve else (0.0, 0.0)
    for row in curve:
        equity = float(row["equity"])
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak if peak > 0 else 0)
    return {
        "closed_trades": len(trades),
        "win_rate_pct": round(wins * 100 / len(trades), 3) if trades else 0.0,
        "profit_factor": round(gains / losses, 4) if losses else None,
        "max_drawdown_pct": round(drawdown * 100, 3),
        "average_r": round(sum(ratios) / len(ratios), 4) if ratios else None,
        "equity_curve": downsample(curve),
    }


def downsample(curve: list[dict], limit: int = 120) -> list[dict]:
    if len(curve) <= limit:
        return curve
    indexes = sorted({round(i * (len(curve) - 1) / (limit - 1)) for i in range(limit)})
    return [curve[i] for i in indexes]


def save_report(data_dir: Path, kind: str, report: dict, *, symbol: str = "portfolio") -> Path:
    if kind not in {"backtest", "portfolio"} or not symbol.isalnum():
        raise ValueError("Invalid historical report identity")
    folder = Path(data_dir) / "backtests"
    folder.mkdir(parents=True, exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = folder / f"{kind}_{symbol}_{label}_{uuid4().hex[:8]}.json"
    tmp = dest.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, allow_nan=False)
        fp.flush()
        os.fsync(fp.fileno())
    tmp.replace(dest)
    return dest
