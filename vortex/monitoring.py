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


def recent_jsonl(path, limit=100, max_bytes=262144):
    """Bound dashboard I/O as append-only journals grow; tolerate torn last line."""
    rows = []
    try:
        with path.open("rb") as fp:
            fp.seek(0, 2)
            start = max(0, fp.tell() - max_bytes)
            fp.seek(start)
            data = fp.read(max_bytes)
        lines = data.splitlines()
        if start:
            lines = lines[1:]  # First line may have been cut by the byte window.
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def recent_decisions(folder, limit=100):
    return recent_jsonl(folder / "decisions.jsonl", limit)


def rejection_counts(rows):
    return dict(
        Counter(
            row["reason"].split("reason=", 1)[-1]
            for row in rows
            if row.get("code") not in {"SIGNAL_ACCEPTED", "ENTRY_ACCEPTED"}
        )
    )
