"""Synthetic measurement contracts; no performance evidence."""

import json
from dataclasses import replace

import pytest

from vortex.measurement import append_decision, voter_attribution
from vortex.phase1_config import StrategyPolicy
from vortex.strategy import analyze
from test_phase1 import setup


def test_audit_has_no_entry_effect_and_records_both_results():
    small, higher, macro, now = setup()
    policy = StrategyPolicy(session_filter=False, volatility_filter=False)
    rows = []
    plain = analyze("BTCUSDT", small, higher, macro=macro, decision_ms=now, policy=policy)
    audited = analyze(
        "BTCUSDT", small, higher, macro=macro, decision_ms=now, policy=policy, audit=rows.append
    )
    assert plain == audited and rows[0]["accepted"]
    assert rows[0]["votes"]["trend"] == 1
    assert rows[0]["shadow_outcome"] is None
    assert rows[0]["indicators"]["atr_percentile"] is not None
    assert analyze("BTCUSDT", small, higher, macro=None, policy=policy, audit=rows.append) is None
    assert rows[1]["veto_reason"] == "insufficient_history"
    assert all(value is None for value in rows[1]["votes"].values())
    assert rows[1]["regime"] == "not_evaluated"
    assert (
        analyze(
            "BTCUSDT",
            small,
            higher,
            macro=macro,
            decision_ms=now,
            policy=replace(policy, strong_enabled=False, normal_weight=100),
            audit=rows.append,
        )
        is None
    )
    assert rows[-1]["veto_reason"] == "weighted_consensus"


def test_jsonl_optional_env_and_write_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("VORTEX_SIGNAL_AUDIT", raising=False)
    assert analyze("BTCUSDT", [], []) is None
    assert not (tmp_path / "signals.jsonl").exists()
    monkeypatch.setenv("VORTEX_SIGNAL_AUDIT", "true")
    assert analyze("BTCUSDT", [], []) is None
    assert json.loads((tmp_path / "signals.jsonl").read_text())["accepted"] is False
    with pytest.raises(ValueError):
        append_decision(tmp_path, {"invalid": float("nan")})


def test_attribution_never_invents_empty_or_causal_metrics():
    empty = voter_attribution([])
    assert all(row["win_rate_pct"] is None for row in empty.values())
    rows = [
        {"net_pnl": 10, "r_multiple": 1, "votes": ["trend", "breakout"]},
        {"net_pnl": -5, "r_multiple": -0.5, "votes": ["trend"]},
    ]
    result = voter_attribution(rows)
    assert result["trend"]["profit_factor"] == 2
    assert result["trend"]["win_rate_pct"] == 50
    assert result["trend"]["average_r"] == 0.25
    assert result["trend"]["marginal_contribution"] is None
    assert result["breakout"]["closed_trades"] == 1
    assert result["funding_fade"]["profit_factor"] is None
    assert all(row["low_sample_warning"] for row in result.values())


def test_extended_history_requires_opt_in_and_complete_range(monkeypatch):
    from vortex.binance import Market, MarketError

    market = Market()
    market._exchange = {"BTCUSDT": {}}
    monkeypatch.delenv("VORTEX_EXTENDED_HISTORY", raising=False)
    with pytest.raises(MarketError, match="Invalid history"):
        market.history("BTCUSDT", "1h", 90, 200 * 86400000)
    monkeypatch.setenv("VORTEX_EXTENDED_HISTORY", "true")
    now = 200 * 86400000

    def get(path, params):
        start = params["startTime"]
        return [
            [ts, 100, 101, 99, 100, 100, ts + 3599999]
            for ts in range(start, min(start + 1500 * 3600000, now), 3600000)
        ]

    monkeypatch.setattr(market, "get", get)
    assert len(market.history("BTCUSDT", "1h", 90, now)) == 2400
    monkeypatch.setattr(market, "get", lambda *args: get(*args)[:100])
    with pytest.raises(MarketError, match="Incomplete extended"):
        market.history("BTCUSDT", "1h", 90, now)


def test_failed_attempts_are_preserved_without_performance(tmp_path):
    from subprocess import CompletedProcess
    from research.phase0_attempts import collect

    seen = []

    def fail(argv, **kwargs):
        seen.append(argv)
        assert kwargs["env"]["FEE_RATE"] == "0.0005"
        assert kwargs["env"]["VORTEX_EXTENDED_HISTORY"] == "true"
        return CompletedProcess(argv, 1, "", "synthetic download unavailable\n")

    output = tmp_path / "attempt"
    report = collect(output, "fixture-reference", executor=fail)
    assert len(seen) == 4
    assert all(row["metrics"] is None and row["attribution"] is None for row in report["attempts"])
    assert not report["economic_validation"]
    assert len(list(output.glob("*.log"))) == 4
    with pytest.raises(FileExistsError):
        collect(output, "fixture-reference", executor=fail)
