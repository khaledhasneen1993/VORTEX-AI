import gzip
import json
from dataclasses import replace

import pytest

from vortex.locks import AlreadyRunning
from vortex.recorder import SegmentWriter, scan_segment, verify, DataRecorder
from vortex.runtime_config import RuntimePolicy
from vortex.config import Settings


def test_rotation_resume_torn_tail_and_hash(tmp_path):
    clock = [1000.0]
    policy = RuntimePolicy(recorder_enabled=True, recorder_rotate_seconds=60)
    writer = SegmentWriter(tmp_path, policy, clock=lambda: clock[0])
    with pytest.raises(AlreadyRunning):
        SegmentWriter(tmp_path, policy)
    writer.append({"kind": "market"})
    first = writer.path
    clock[0] += 61
    writer.append({"kind": "market"})
    damaged = writer.path
    writer.close()  # Simulated crash: segment has no seal.
    with damaged.open("ab") as fp:
        fp.write(gzip.compress(b'{"seq":99999}\n')[:12])
    size = damaged.stat().st_size
    writer = SegmentWriter(tmp_path, policy, clock=lambda: clock[0])
    assert writer.seq >= 5  # Resume + explicit gap; torn record never advances seq.
    writer.finish()
    assert damaged.stat().st_size == size  # Never truncate forensic evidence.
    assert scan_segment(first)["complete"]
    result = verify(tmp_path)
    assert result["pending"] == []
    assert any("TORN_SUFFIX" in error for error in result["errors"])
    with first.open("ab") as fp:
        fp.write(b"tamper")
    with pytest.raises(ValueError, match="SHA256"):
        SegmentWriter(tmp_path, policy)


def test_recorder_failure_isolated_and_bounded_decisions(tmp_path):
    cfg = Settings(
        data_dir=tmp_path,
        runtime=RuntimePolicy(recorder_enabled=True, recorder_decisions=True, recorder_queue_size=1),
    )
    worker = DataRecorder(cfg, cfg.symbols, market_factory=lambda: (_ for _ in ()).throw(OSError()))
    worker.enqueue_decision({"code": "A"})
    worker.enqueue_decision({"code": "B"})
    assert worker.status()["dropped_decisions"] == 1
    worker._run()
    assert worker.status()["status"] == "FAILED"
    assert json.loads((tmp_path / "recorder/health.json").read_text())["status"] == "FAILED"


def test_sample_records_missing_not_fabricated(tmp_path):
    class Missing:
        def metadata(self):
            raise OSError()

        def get(self, *args):
            raise OSError()

        def server_ms(self):
            return 1000

    cfg = Settings(data_dir=tmp_path, runtime=RuntimePolicy(recorder_enabled=True))
    writer = SegmentWriter(tmp_path / "recorder", cfg.runtime)
    worker = DataRecorder(cfg, cfg.symbols)
    row = worker.sample(Missing(), writer, "BTCUSDT")
    assert not row["data"]
    assert len(row["gaps"]) == 6
    writer.finish()
    assert verify(tmp_path / "recorder")["errors"] == []
    assert not replace(cfg.runtime, recorder_enabled=False).recorder_enabled
