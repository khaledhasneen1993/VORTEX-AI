"""Price-only shadow evidence contracts. Synthetic fixtures are not performance results."""
import json
from pathlib import Path

import pytest

from research import phase0_shadow_signals as shadow
from vortex.models import Candle, Signal


def candle(t, close):
    return Candle(t, close, close, close, close, 1.0, t + 299999, 0.5)


def test_shadow_future_market_move_never_implies_fill():
    bars = [candle(i * 300000, 100.0 + i) for i in range(14)]
    assert shadow.future_market_move(bars, 0) == 12.0
    assert shadow.future_market_move(bars, 2) is None
    with pytest.raises(ValueError, match="positive"):
        shadow.future_market_move(bars, 0, 0)
    gap = [bars[0], candle(10 * 300000, 100.0)]
    assert shadow.future_market_move(gap, 0, horizon=1) is None


def test_shadow_jsonl_always_null_financial_validation_and_no_rewrites(tmp_path, monkeypatch):
    end_ms = 40 * shadow.DAY_MS
    start = end_ms - shadow.DAY_MS
    bars = [candle(start + 300000 * i, 100 + i / 10) for i in range(20)]
    class Market:
        sources = {"verified.csv": {"csv_sha256": "abc"}}
        def server_ms(self):
            return end_ms
        def history(self, symbol, interval, days, now):
            assert symbol == "BTCUSDT" and days == 30 and now == end_ms
            return bars
    calls = []
    def fake_analyze(symbol, small, higher, *args, audit=None, **kwargs):
        calls.append(small[-1].ts)
        is_accepted = len(calls) % 2 == 0
        audit({
            "accepted": is_accepted, "veto_reason": None if is_accepted else "synthetic_veto",
            "votes": {"trend": None}, "signal": None,
            "shadow_outcome": None, "regime": "synthetic",
        })
        return Signal(symbol, "LONG", small[-1].ts, 101, 100, 110, 7, "fixture") if is_accepted else None
    monkeypatch.setattr(shadow, "analyze", fake_analyze)
    target = tmp_path / "shadow.jsonl"
    result = shadow.audit_symbol(Market(), "BTCUSDT", 30, end_ms, target)
    assert result["decisions"] == 20
    assert result["canonical_strategy_signals"] == 10
    assert result["forward_market_moves_observed"] == 8
    assert result["economic_baseline"] is False
    assert result["net_pnl"] is None and result["profit_factor"] is None
    assert result["veto_reasons"]["synthetic_veto"] == 10
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert all(x["shadow_outcome"]["trade_pnl"] is None for x in rows)
    assert all(not x["financial_validation"] for x in rows)
    assert rows[0]["shadow_outcome"]["accepted_signal_directional_return_pct"] is None
    assert rows[1]["shadow_outcome"]["accepted_signal_directional_return_pct"] is not None
    assert rows[-1]["shadow_outcome"]["forward_market_return_pct"] is None
    assert Path(tmp_path / "shadow.summary.json").exists()
    with pytest.raises(FileExistsError):
        shadow.audit_symbol(Market(), "BTCUSDT", 30, end_ms, target)
