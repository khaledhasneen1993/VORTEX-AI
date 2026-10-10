"""Synthetic Phase 0 touch-label tests; no claim about real market results."""
import json
from datetime import datetime, timezone

import pytest

from research.phase0_exit_paths import (
    DAY_MS, LEVELS, load_accepted, new_event, observe, replay, summarise,
)
from vortex.local_data import digest
from vortex.models import Candle


def bar(ts, opening, low, high, close=None):
    return Candle(ts, opening, high, low, close if close is not None else opening, 5.0,
                  ts + 59999, 2.0)


def sig(side="LONG", decision_ms=299999, entry=100.0, stop=90.0):
    return dict(symbol="BTCUSDT", decision_ms=decision_ms, side=side, score=7,
                votes=["trend", "breakout"], reference_entry=entry,
                reference_stop=stop, atr=1.0)


def test_long_conservative_stop_first_ambiguous_ohlc():
    e = new_event(sig())
    observe(e, bar(300000, 100, 89, 122))
    assert e["first_barrier"]["1.0"] == "both_touch_stop_first_conservative"
    assert e["first_barrier"]["2.0"] == "both_touch_stop_first_conservative"
    assert e["first_barrier"]["3.0"] == "stop_touch_first"
    assert e["ambiguous_same_minute"]["1.0"] is True
    assert e["mfe_r_240m"] == 2.2 and e["mae_r_240m"] == 1.1
    assert e["observed_minutes"] == 1
    assert summarise([e], "BTCUSDT", 30, "abc")["real_net_pnl"] is None


def test_short_favorable_then_stop_keeps_first_event():
    e = new_event(sig(side="SHORT", stop=110))
    observe(e, bar(300000, 100, 84, 104))
    assert e["first_barrier"]["1.0"] == "favorable_touch_first"
    assert e["first_barrier"]["1.5"] == "favorable_touch_first"
    assert e["first_barrier"]["2.0"] is None
    observe(e, bar(360000, 89, 87, 111))
    assert e["first_barrier"]["1.0"] == "favorable_touch_first"
    assert e["first_barrier"]["2.0"] == "stop_touch_first"


def test_entry_repricing_gap_and_missing_minute_fail_closed():
    gap = new_event(sig())
    observe(gap, bar(300000, 106, 104, 107))
    assert gap["skip_reason"] == "entry_gap_exceeds_existing_035R_guard"
    assert gap["entry_eligible_by_gap"] is False
    e = new_event(sig())
    observe(e, bar(300000, 100, 95, 105))
    with pytest.raises(ValueError, match="Gap inside"):
        observe(e, bar(420000, 100, 95, 105))


def test_shadow_inputs_require_verified_hash_and_consistent_counts(tmp_path):
    end_ms = 32 * DAY_MS
    signal_time = end_ms - DAY_MS + 299999
    row = dict(
        symbol="BTCUSDT", decision_ms=signal_time, financial_validation=False,
        accepted=True, signal=dict(
            symbol="BTCUSDT", side="LONG", entry=100, stop=90, atr_value=1,
            score=7, votes=["trend"]
        )
    )
    data = tmp_path / "signals.jsonl"
    data.write_text(json.dumps(row) + "\n")
    summary = tmp_path / "signals.summary.json"
    summary.write_text(json.dumps({
        "scope": "historical_ohlcv_signal_only",
        "symbol": "BTCUSDT", "days": 30, "economic_baseline": False,
        "end_exclusive_utc": datetime.fromtimestamp(end_ms/1000, timezone.utc).isoformat(),
        "decisions": 1, "canonical_strategy_signals": 1,
        "jsonl_sha256": digest(data)
    }))
    rows, sha = load_accepted(data, summary, "BTCUSDT", 30, end_ms)
    assert len(rows) == 1 and sha == digest(data)
    data.write_text(data.read_text() + " ")
    with pytest.raises(ValueError, match="SHA256"):
        load_accepted(data, summary, "BTCUSDT", 30, end_ms)


def test_missing_verified_source_day_not_a_no_touch(tmp_path):
    with pytest.raises(ValueError, match="Missing verified source day"):
        replay(tmp_path, [sig(decision_ms=100 * DAY_MS + 299999)], 100 * DAY_MS, 101 * DAY_MS)


def test_horizon_censored_not_marked_as_failure():
    e = new_event(sig())
    observe(e, bar(300000, 100, 96, 102))
    e["full_240m_observed"] = e["observed_minutes"] == 240
    e["full_60m_observed"] = e["observed_minutes"] >= 60
    e["horizon_censored"] = not e["full_240m_observed"]
    x = summarise([e], "BTCUSDT", 30, "sha")
    assert x["price_touch_counts"]["1.0"]["touch_categories"]["no_touch_within_observed_window"] == 1
    assert x["economic_baseline_complete"] is False
    assert all(str(level) in x["price_touch_counts"] for level in LEVELS)
