from vortex.operations import OperationsPolicy

"""Offline hardening contract tests; no network, no API credentials or orders."""
import json

import pytest
import requests

from vortex.config import Settings
from vortex.models import Candle, Signal
from vortex.risk import Filters

F = Filters(0.001, 0.001, 5, 0.1)
S = Signal("BTCUSDT", "LONG", 1000, 100, 98, 104, 7, "fixture")


def test_paper_close_journal_crash_is_recoverable(monkeypatch, tmp_path):
    from vortex.paper import PaperBroker

    p = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    ok, _ = p.open(S, 99.99, 100.01, F, {"BTCUSDT": (99.99, 100.01)}, 1000000)
    assert ok
    original = p._write_journal

    def fail_before_append(event):
        raise OSError("simulated disk interruption")

    monkeypatch.setattr(p, "_write_journal", fail_before_append)
    with pytest.raises(OSError):
        p.mark({"BTCUSDT": (97, 97.01)}, 1050000)
    reloaded = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    assert reloaded.closed_count == 1
    assert not reloaded.positions
    assert reloaded.pending_journal is None
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
    reloaded.save()
    after = PaperBroker(
        Settings(
            data_dir=tmp_path,
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True),
        )
    )
    assert after.closed_count == 1
    assert len((tmp_path / "closed_trades.jsonl").read_text().splitlines()) == 1
