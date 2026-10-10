import json

import pytest

from vortex.config import Settings
from vortex.health import LiveHealth, read_health
from vortex.monitoring import recent_jsonl
from vortex.runtime_config import RuntimePolicy
from vortex.stream import QuoteStream


def test_partial_ws_quotes_never_promote_stale_and_silence_closes():
    monotonic = [1.0]
    wall = [1000]
    stream = QuoteStream(
        ("BTCUSDT", "ETHUSDT"),
        clock=lambda: monotonic[0],
        wall_ms=lambda: wall[0],
        resilient=True,
        silence_seconds=10,
    )
    stream.ingest("{invalid")
    stream.ingest(json.dumps({"s": "BTCUSDT", "b": "10", "a": "11", "E": 1000}))
    assert stream.snapshot() == {"BTCUSDT": (10.0, 11.0)}
    monotonic[0] = 12

    class Socket:
        closed = False

        def close(self):
            self.closed = True

    socket = Socket()
    stream._ws = socket
    with pytest.raises(ValueError, match="stale"):
        stream.snapshot()
    assert socket.closed


def test_health_disabled_and_stopped_progress(tmp_path):
    off = LiveHealth(Settings(data_dir=tmp_path))
    off.update(status="RUNNING")
    assert not (tmp_path / "health.json").exists()
    on = LiveHealth(Settings(data_dir=tmp_path, runtime=RuntimePolicy(health_enabled=True)))
    on.update(force=True, status="RUNNING")
    raw = json.loads((tmp_path / "health.json").read_text())
    assert read_health(tmp_path, now_ms=raw["progress_ms"] + 31000)["health"]["status"] == "STALE_OR_STOPPED"
    journal = tmp_path / "decisions.jsonl"
    journal.write_text("".join(json.dumps({"seq": i}) + "\n" for i in range(1000)) + "{torn")
    rows = recent_jsonl(journal, limit=5, max_bytes=100)
    assert rows[-1]["seq"] == 999
    assert len(rows) <= 5


def test_original_r_survives_cost_entry_and_stop_changes():
    from vortex.models import Position
    from vortex.r_units import anchor_entry, price_r, net_r

    p = Position(
        "BTCUSDT",
        "LONG",
        0,
        105,
        104,
        130,
        1,
        0,
        10,
        initial_qty=2,
        initial_risk=10,
        anchor_entry=100,
        initial_stop=90,
    )
    assert price_r(p) == 10
    assert anchor_entry(p) == 100
    assert net_r(p, 30) == 1.5
    p.stop = 110
    p.entry = 108
    assert price_r(p) == 10
    assert net_r(p, 30) == 1.5
