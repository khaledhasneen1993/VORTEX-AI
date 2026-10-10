"""Phase 0: descriptive, no-fill exit-path touch study over verified 1m OHLCV.

This is NOT a backtest of broker execution or PnL. Every accepted canonical signal
is studied independently, without funding, spreads, exchange-book or position gates.
Future candles are used ONLY for ex-post labels, never for the signal decision.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

from vortex.local_data import digest, read_csv

DAY_MS = 86_400_000
MINUTE_MS = 60_000
HORIZON = 240
LEVELS = (1.0, 1.5, 2.0, 3.0)


def load_accepted(jsonl_path, summary_path, symbol, days, end_ms):
    """Require authentic, matching frozen shadow evidence; reject tampered JSONL."""
    summary = json.loads(Path(summary_path).read_text())
    expected_start = end_ms - days * DAY_MS
    if (summary.get("scope") != "historical_ohlcv_signal_only"
        or summary.get("symbol") != symbol or summary.get("days") != days
        or summary.get("economic_baseline") is not False
        or summary.get("end_exclusive_utc") != datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat()):
        raise ValueError("Mismatched/invalid canonical shadow summary")
    if digest(jsonl_path) != summary.get("jsonl_sha256"):
        raise ValueError("Shadow decision JSONL SHA256 mismatch")
    rows = []
    seen = set()
    decisions = accepted = 0
    with Path(jsonl_path).open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("symbol") != symbol or row.get("financial_validation") is not False:
                raise ValueError("Out-of-scope or financial-looking shadow row")
            ts = row.get("decision_ms")
            if not isinstance(ts, int) or not expected_start <= ts < end_ms or ts in seen:
                raise ValueError("Invalid/out-of-order/duplicate shadow decision")
            seen.add(ts)
            decisions += 1
            if row.get("accepted"):
                accepted += 1
                signal = row.get("signal") or {}
                if signal.get("symbol") != symbol or signal.get("side") not in ("LONG", "SHORT"):
                    raise ValueError("Malformed canonical signal")
                rows.append({
                    "symbol": symbol, "decision_ms": ts,
                    "side": signal["side"], "score": signal.get("score"),
                    "votes": signal.get("votes", []),
                    "reference_entry": float(signal["entry"]),
                    "reference_stop": float(signal["stop"]),
                    "atr": float(signal["atr_value"]),
                })
    if decisions != summary.get("decisions") or accepted != summary.get("canonical_strategy_signals"):
        raise ValueError("Decision count mismatch against source audit")
    rows.sort(key=lambda r: r["decision_ms"])
    return rows, summary["jsonl_sha256"]


def new_event(signal):
    event = dict(signal)
    event["start_ms"] = signal["decision_ms"] + 1
    event["end_ms"] = event["start_ms"] + HORIZON * MINUTE_MS
    event["entry_open"] = None
    event["risk_price_units"] = None
    event["entry_eligible_by_gap"] = None
    event["skip_reason"] = None
    event["first_barrier"] = {str(level): None for level in LEVELS}
    event["barrier_first_ms"] = {str(level): None for level in LEVELS}
    event["ambiguous_same_minute"] = {str(level): False for level in LEVELS}
    event["mfe_r_60m"] = event["mae_r_60m"] = 0.0
    event["mfe_r_240m"] = event["mae_r_240m"] = 0.0
    event["observed_minutes"] = 0
    return event


def observe(event, bar):
    """Independent hypothetical touch evidence. Never an executable trade fill."""
    if event["skip_reason"] is not None:
        return
    if bar.ts < event["start_ms"] or bar.ts >= event["end_ms"]:
        return
    if event["entry_open"] is None:
        if bar.ts != event["start_ms"]:
            raise ValueError("Missing exact next-minute candidate entry")
        reference = event["reference_entry"]
        risk = abs(reference - event["reference_stop"])
        if not risk > 0 or not reference > 0 or not bar.open > 0:
            raise ValueError("Malformed reference risk/entry")
        if abs(bar.open - reference) > 0.35 * risk:
            event["skip_reason"] = "entry_gap_exceeds_existing_035R_guard"
            event["entry_eligible_by_gap"] = False
            return
        event["entry_open"] = bar.open
        event["risk_price_units"] = risk
        event["entry_eligible_by_gap"] = True
    if bar.ts != event["start_ms"] + event["observed_minutes"] * MINUTE_MS:
        raise ValueError("Gap inside event observation window")
    risk = event["risk_price_units"]
    if event["side"] == "LONG":
        favorable = (bar.high - event["entry_open"]) / risk
        adverse = (event["entry_open"] - bar.low) / risk
    else:
        favorable = (event["entry_open"] - bar.low) / risk
        adverse = (bar.high - event["entry_open"]) / risk
    event["mfe_r_240m"] = max(event["mfe_r_240m"], favorable)
    event["mae_r_240m"] = max(event["mae_r_240m"], adverse)
    if event["observed_minutes"] < 60:
        event["mfe_r_60m"] = max(event["mfe_r_60m"], favorable)
        event["mae_r_60m"] = max(event["mae_r_60m"], adverse)
    for level in LEVELS:
        label = str(level)
        if event["first_barrier"][label] is not None:
            continue
        hit_stop, hit_favorable = adverse >= 1.0, favorable >= level
        if hit_stop or hit_favorable:
            # Same 1m OHLC does not establish tick-level order of touches.
            event["first_barrier"][label] = (
                "both_touch_stop_first_conservative" if hit_stop and hit_favorable
                else "stop_touch_first" if hit_stop else "favorable_touch_first"
            )
            event["ambiguous_same_minute"][label] = hit_stop and hit_favorable
            event["barrier_first_ms"][label] = bar.ts
    event["observed_minutes"] += 1


def replay(root, signals, start_ms, end_ms):
    """Stream each verified source CSV exactly once; retain only pending events."""
    root = Path(root)
    sorted_events = sorted((new_event(x) for x in signals), key=lambda x: x["start_ms"])
    pending = deque()
    cursor = 0
    day_ms = start_ms
    while day_ms < end_ms:
        day = datetime.fromtimestamp(day_ms / 1000, timezone.utc).date().isoformat()
        symbol = signals[0]["symbol"] if signals else None
        if symbol is None:
            break
        csv = root / symbol / "1m" / f"{symbol}-1m-{day}.csv"
        manifest = csv.with_suffix(".json")
        if not csv.is_file() or not manifest.is_file():
            raise ValueError(f"Missing verified source day {day}")
        source = json.loads(manifest.read_text())
        if digest(csv) != source.get("csv_sha256"):
            raise ValueError(f"Source checksum mismatch for {day}")
        bars = 0
        for bar in read_csv(csv, "1m"):
            if not bars and bar.ts != day_ms:
                raise ValueError(f"Missing first minute on {day}")
            while cursor < len(sorted_events) and sorted_events[cursor]["start_ms"] <= bar.ts:
                if sorted_events[cursor]["start_ms"] < bar.ts:
                    raise ValueError("Candidate start missing in market source")
                pending.append(sorted_events[cursor])
                cursor += 1
            for event in pending:
                observe(event, bar)
            while pending and pending[0]["end_ms"] <= bar.ts:
                pending.popleft()
            bars += 1
        if bars != 1440:
            raise ValueError(f"Incomplete 1m day {day}: {bars} bars")
        day_ms += DAY_MS
    if cursor != len(sorted_events):
        raise ValueError("Source never reached some signals")
    for event in sorted_events:
        event["full_240m_observed"] = event["observed_minutes"] == HORIZON
        event["full_60m_observed"] = event["observed_minutes"] >= 60
        event["horizon_censored"] = event["entry_eligible_by_gap"] is not False and not event["full_240m_observed"]
    return sorted_events


def summarise(events, symbol, days, source_sha):
    counts = {}
    for level in LEVELS:
        label = str(level)
        counted = Counter(
            e["first_barrier"][label] or "no_touch_within_observed_window"
            for e in events if e["entry_eligible_by_gap"] is True
        )
        counts[label] = {
            "touch_categories": dict(sorted(counted.items())),
            "unambiguous_favorable_first": counted["favorable_touch_first"],
            "unambiguous_stop_first": counted["stop_touch_first"],
            "ambiguous_stop_first_conservative": counted["both_touch_stop_first_conservative"],
        }
    return {
        "symbol": symbol, "days": days, "signal_count": len(events),
        "modeled_entries_from_next_1m_open": sum(e["entry_eligible_by_gap"] is True for e in events),
        "gap_ineligible": sum(e["entry_eligible_by_gap"] is False for e in events),
        "complete_60m_market_windows": sum(e["full_60m_observed"] for e in events),
        "complete_240m_market_windows": sum(e["full_240m_observed"] for e in events),
        "price_touch_counts": counts,
        "source_shadow_sha256": source_sha,
        "model": "descriptive_next_1m_open_plus_static_initial_R_touch_only",
        "real_fills": None, "real_net_pnl": None, "profit_factor": None,
        "economic_baseline_complete": False,
        "warning": "Independent, overlapping signal studies; not trades. Candle OHLC cannot determine same-minute tick order; stop-first labels are conservative. No funding, level-2 orderbook, quotes, slippage, liquidation, position exclusivity, staged exits or actual executable fills."
    }


def run(root, signals_path, summary_path, symbol, days, end_date, output):
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    events, source_sha = load_accepted(signals_path, summary_path, symbol, days, end_ms)
    outfile = Path(output)
    reportfile = outfile.with_suffix(".summary.json")
    if outfile.exists() or reportfile.exists():
        raise FileExistsError("Never overwrite existing event evidence")
    outfile.parent.mkdir(parents=True, exist_ok=True)
    events = replay(root, events, end_ms - days * DAY_MS, end_ms)
    with outfile.open("x", encoding="utf-8") as out:
        for event in events:
            out.write(json.dumps(event, allow_nan=False, sort_keys=True) + "\n")
    report = summarise(events, symbol, days, source_sha)
    report["event_jsonl_sha256"] = digest(outfile)
    reportfile.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ohlcv-dir", required=True)
    p.add_argument("--signals", required=True)
    p.add_argument("--signals-summary", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--days", type=int, required=True, choices=[30, 90])
    p.add_argument("--end-utc", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    print(json.dumps(run(a.ohlcv_dir, a.signals, a.signals_summary, a.symbol, a.days, a.end_utc, a.output), indent=2))


if __name__ == "__main__":
    main()
