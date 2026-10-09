"""Read-only operational snapshots. Marked equity is sampled, never continuous."""

import json
from collections import Counter
from datetime import UTC, datetime


def save_telemetry(broker, quotes, now_ms, rejection_count):
    equity = broker.equity(quotes)
    row = {
        "mode": "PAPER",
        "observed_ms": now_ms,
        "observed_utc": datetime.fromtimestamp(now_ms / 1000, UTC).isoformat(),
        "marked_equity": equity,
        "wallet": broker.wallet,
        "unrealized_after_estimated_exit_fee": equity - broker.wallet,
        "reserved_profit": broker.reserve.reserved,
        "trading_capital": broker.reserve.capital(broker.wallet, equity),
        "daily_loss_fraction": max(0.0, 1 - equity / broker.gate.day_start_equity),
        "daily_loss_limit": broker.cfg.max_daily_loss,
        "margin": sum(p.margin for p in broker.positions.values()),
        "current_process_rejections": rejection_count,
        "protection": broker.protection.state(),
    }
    path = broker.folder / "telemetry.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(row, indent=2))
    temp.replace(path)


def recent_decisions(folder, limit=100):
    path = folder / "decisions.jsonl"
    rows = []
    if path.exists():
        from collections import deque

        with path.open(encoding="utf-8") as f:
            for line in deque(f, maxlen=limit):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # Concurrent incomplete final append is retried on refresh.
    return rows


def rejection_counts(rows):
    return dict(Counter(row["reason"].split("reason=", 1)[-1] for row in rows))
