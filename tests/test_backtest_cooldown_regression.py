"""Regression: temporary entry cooldown MUST NOT end the historical replay.

Synthetic fixtures only: this is a software invariant, not profit evidence.
"""
from dataclasses import replace

from vortex import backtest
from vortex.config import Settings
from vortex.models import Candle
from vortex.operations import Protection
from vortex.risk import Filters


def test_cooldown_skips_entries_but_continues_future_completed_bars(monkeypatch):
    start = 1_789_000_000_000
    start -= start % 300000
    bars = [
        Candle(start + i * 300000, 100.0, 101.0, 99.0, 100.0, 1000.0,
               start + (i + 1) * 300000 - 1, 500.0)
        for i in range(115)
    ]
    cfg = Settings(
        mode="backtest",
        operations=replace(Settings().operations, funding_guard=False, liquidity_guard=False),
    )
    first_allowed = bars[80].close_ts
    observed = []
    original_allow = Protection.allow

    def temporary_veto(self, timestamp):
        if timestamp < first_allowed:
            return False, "progressive losing-streak cooldown"
        return original_allow(self, timestamp)

    def record_signal(*args, **kwargs):
        observed.append(kwargs.get("macro") is not None)
        return None

    monkeypatch.setattr(Protection, "allow", temporary_veto)
    monkeypatch.setattr(backtest, "analyze", record_signal)
    report = backtest.run(
        "BTCUSDT",
        bars,
        bars,
        Filters(0.001, 0.001, 5.0, 0.01),
        cfg,
        macro=bars,
        minute=bars,
    )
    assert observed, "Signal checks must resume after a temporary cooldown"
    assert report["metrics"]["closed_trades"] == 0
    assert len(report["equity_curve"]) == len(bars) - 65 + 1
    assert report["equity_curve"][-1]["ts"] == bars[-1].close_ts
    assert report["halted"] is False
