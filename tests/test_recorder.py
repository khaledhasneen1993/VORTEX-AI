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


def test_three_hour_virtual_rotation_and_resume(tmp_path):
    # Deterministic durability test, not a claimed three-hour market run.
    clock = [1000.0]
    policy = RuntimePolicy(recorder_enabled=True, recorder_rotate_seconds=3600)
    writer = SegmentWriter(tmp_path, policy, clock=lambda: clock[0])
    for minute in range(181):
        clock[0] = 1000.0 + minute * 60
        writer.append({"kind": "market", "gaps": ["SYNTHETIC_TEST_ONLY"]})
    seq = writer.seq
    writer.finish()
    assert verify(tmp_path)["errors"] == []
    assert verify(tmp_path)["sealed"] == 4
    writer = SegmentWriter(tmp_path, policy, clock=lambda: clock[0])
    assert writer.seq == seq + 2
    writer.finish()


def test_sample_public_payloads_and_real_flow_formula(tmp_path):
    class Public:
        def metadata(self):
            return {"BTCUSDT": {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.1"}]}}

        def server_ms(self):
            return 100000

        def get(self, path, params):
            if path.endswith("aggTrades"):
                return [{"T": 99999, "a": i, "p": "100", "q": "2", "m": False} for i in range(20)]
            if path.endswith("depth"):
                return {"T": 99999, "bids": [["100", "1"]] * 20, "asks": [["101", "1"]] * 20}
            return {
                "time": 99999,
                "symbol": "BTCUSDT",
                "markPrice": "100",
                "lastFundingRate": "0.0001",
                "nextFundingTime": 200000,
                "openInterest": "1000",
                "bidPrice": "100",
                "askPrice": "101",
            }

    cfg = Settings(data_dir=tmp_path, runtime=RuntimePolicy(recorder_enabled=True))
    worker = DataRecorder(cfg, cfg.symbols)
    writer = SegmentWriter(tmp_path / "recorder", cfg.runtime)
    row = worker.sample(Public(), writer, "BTCUSDT")
    assert row["gaps"] == []
    assert len(row["data"]["depth"]["raw"]["bids"]) == 10
    assert row["data"]["flow"]["cvd_base"] == 40
    assert row["data"]["flow"]["reason"] == "FLOW_VALID"
    writer.finish()
