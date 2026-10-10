"""Independent, bounded public-data recorder. No authenticated endpoints or execution.

One gzip member per JSON line. Never append to a previous run's segment: seal
its complete prefix (retain a torn suffix), hash all bytes and open a new segment.
Unknown recorder writes halt this worker, never the PAPER execution ledger.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid
import zlib
from dataclasses import asdict, replace
from pathlib import Path

from .binance import Market
from .locks import ProcessLock
from .orderflow import summarize_trades

log = logging.getLogger("vortex.recorder")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for block in iter(lambda: fp.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def scan_segment(path):
    """Bounded member parser; returns only fully CRC-checked JSON records."""
    last_seq = count = valid_bytes = last_recorded_ms = 0
    decoder = zlib.decompressobj(31)
    record = bytearray()
    consumed = 0
    try:
        with path.open("rb") as fp:
            pending = b""
            while True:
                block = pending or fp.read(65536)
                pending = b""
                if not block:
                    break
                output = decoder.decompress(block, 1024 * 1024 + 1 - len(record))
                record.extend(output)
                if len(record) > 1024 * 1024 or decoder.unconsumed_tail:
                    raise ValueError("oversized recorder member")
                consumed += len(block) - len(decoder.unused_data)
                if decoder.eof:
                    row = json.loads(record)
                    if int(row["seq"]) <= last_seq:
                        raise ValueError("non-monotone sequence")
                    last_seq = int(row["seq"])
                    last_recorded_ms = int(row["recorded_ms"])
                    count += 1
                    valid_bytes = consumed
                    pending = decoder.unused_data
                    decoder = zlib.decompressobj(31)
                    record.clear()
    except (ValueError, KeyError, zlib.error):
        pass
    return {
        "last_seq": last_seq,
        "records": count,
        "valid_bytes": valid_bytes,
        "complete": valid_bytes == path.stat().st_size,
        "last_recorded_ms": last_recorded_ms,
    }


class SegmentWriter:
    def __init__(self, folder, policy, clock=time.time):
        self.folder = Path(folder)
        self.policy = policy
        self.clock = clock
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = ProcessLock(self.folder / "recorder.lock").acquire()
        self.fp = None
        self.seq = 0
        previous_ms = 0
        self.manifest = self.folder / "manifest.jsonl"
        try:
            known = {}
            if self.manifest.exists():
                with self.manifest.open("rb") as fp:
                    for line in fp:
                        try:
                            item = json.loads(line)
                            known[item["segment"]] = item
                        except (ValueError, KeyError):
                            continue  # Retained torn manifest line; segments recover below.
                with self.manifest.open("rb") as fp:
                    fp.seek(0, 2)
                    if fp.tell():
                        fp.seek(-1, 2)
                        torn = fp.read(1) != b"\n"
                    else:
                        torn = False
                if torn:
                    self._manifest_append({"event": "MANIFEST_TORN_TAIL"}, prefix=b"\n")
            for path in sorted(self.folder.glob("*.jsonl.gz")):
                checksum = digest(path)
                if path.name in known:
                    item = known[path.name]
                    if item["sha256"] != checksum:
                        raise ValueError("Recorder sealed segment SHA256 mismatch")
                else:
                    item = self._seal(path, recovered=True)
                self.seq = max(self.seq, item["last_seq"])
                previous_ms = max(previous_ms, item.get("last_recorded_ms", 0))
            missing = set(known) - {p.name for p in self.folder.glob("*.jsonl.gz")}
            if missing:
                raise ValueError("Recorder manifest references missing segments")
            self._new_segment()
            if previous_ms:
                self.append(
                    {
                        "kind": "gap",
                        "code": "RESTART_GAP",
                        "previous_recorded_ms": previous_ms,
                        "elapsed_ms": max(0, int(self.clock() * 1000) - previous_ms),
                    }
                )
            self.append({"kind": "resume", "coverage": "sampled_not_continuous", "policy": asdict(policy)})
        except Exception:
            self.close()
            raise

    def _manifest_append(self, row, prefix=b""):
        with self.manifest.open("ab") as fp:
            fp.write(prefix + json.dumps(row, allow_nan=False).encode() + b"\n")
            fp.flush()
            os.fsync(fp.fileno())

    def _seal(self, path, recovered=False):
        row = {"segment": path.name, "sha256": digest(path), **scan_segment(path), "recovered": recovered}
        self._manifest_append(row)
        return row

    def _new_segment(self):
        self.started = self.clock()
        self.path = self.folder / f"{int(self.started * 1000):013d}-{uuid.uuid4().hex}.jsonl.gz"
        self.fp = self.path.open("xb")
        # Persist the directory entry before records can be acknowledged.
        fd = os.open(self.folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def append(self, row):
        if self.fp is None:
            raise OSError("Recorder writer stopped")
        if (
            self.fp.tell() >= self.policy.recorder_rotate_bytes
            or self.clock() - self.started >= self.policy.recorder_rotate_seconds
        ):
            self.fp.close()
            self.fp = None
            self._seal(self.path)
            self._new_segment()
        self.seq += 1
        row = {**row, "seq": self.seq, "recorded_ms": int(self.clock() * 1000)}
        encoded = json.dumps(row, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > 1024 * 1024:
            raise ValueError("Recorder record too large")
        self.fp.write(gzip.compress(encoded, mtime=0))
        self.fp.flush()
        os.fsync(self.fp.fileno())

    def close(self):
        if self.fp is not None:
            self.fp.close()
            self.fp = None
        self.lock.release()

    def finish(self):
        if self.fp is not None:
            self.fp.close()
            self.fp = None
            try:
                self._seal(self.path)
            finally:
                self.lock.release()
        else:
            self.lock.release()


class DataRecorder:
    def __init__(self, cfg, symbols, market_factory=Market):
        self.cfg = cfg
        self.policy = cfg.runtime
        self.factory = market_factory
        self.symbols = tuple(dict.fromkeys(symbols))
        self.guard = threading.Lock()
        self.stop_event = threading.Event()
        self.decisions = queue.Queue(maxsize=self.policy.recorder_queue_size)
        self.thread = None
        self.owns_writer = False
        self.state = {
            "status": "DISABLED",
            "dropped_decisions": 0,
            "last_sample_ms": None,
            "expected_interval_seconds": self.policy.recorder_interval_seconds,
        }

    def update_symbols(self, symbols):
        # Radar<=30 plus up to four existing positions; never an unbounded cache.
        symbols = tuple(dict.fromkeys(symbols))
        if len(symbols) > 34 or any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
            return
        with self.guard:
            self.symbols = symbols

    def enqueue_decision(self, row):
        if not self.policy.recorder_decisions:
            return
        try:
            self.decisions.put_nowait(dict(row))
        except queue.Full:
            self.state["dropped_decisions"] += 1

    def status(self):
        return {**self.state, "queued_decisions": self.decisions.qsize()}

    def _status(self, **fields):
        self.state.update(fields)
        if not self.owns_writer:
            return
        try:
            folder = self.cfg.data_dir / "recorder"
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / "health.tmp"
            tmp.write_text(json.dumps({**self.status(), "updated_ms": int(time.time() * 1000)}))
            tmp.replace(folder / "health.json")
        except OSError:
            pass

    def start(self):
        if not self.policy.recorder_enabled or (self.thread and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._run, name="vortex-recorder", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)  # Public requests may still be in timeout/backoff.

    def _drain_decisions(self, writer):
        # Bound each drain; sampling cannot monopolize the writer for a whole
        # universe and producers cannot starve market collection indefinitely.
        count = 0
        for _ in range(self.policy.recorder_queue_size):
            try:
                decision = self.decisions.get_nowait()
            except queue.Empty:
                break
            writer.append({"kind": "decision", "decision": decision})
            count += 1
        dropped = self.state["dropped_decisions"]
        previous = getattr(self, "_reported_drops", 0)
        if dropped > previous:
            writer.append({"kind": "gap", "code": "DECISION_QUEUE_OVERFLOW", "dropped": dropped - previous})
            self._reported_drops = dropped
        return count

    def sample(self, market, writer, symbol):
        row = {"kind": "market", "symbol": symbol, "data": {}, "gaps": []}
        try:
            row["filters"] = market.metadata()[symbol]["filters"]
        except Exception:
            row["gaps"].append("FILTERS_UNAVAILABLE")
        endpoints = [
            ("book", "/fapi/v1/ticker/bookTicker", {}),
            ("depth", "/fapi/v1/depth", {"limit": 20}),
            ("funding_mark", "/fapi/v1/premiumIndex", {}),
            ("open_interest", "/fapi/v1/openInterest", {}),
        ]
        for key, endpoint, params in endpoints:
            self._drain_decisions(writer)
            if self.stop_event.is_set():
                return
            try:
                raw = market.get(endpoint, {"symbol": symbol, **params})
                checked = market.server_ms()
                stamp = int(raw.get("time", raw.get("T", 0)))
                available = (
                    -1000 <= checked - stamp <= (15000 if key in {"funding_mark", "open_interest"} else 4000)
                )
                if key == "depth":
                    raw = {
                        **raw,
                        "bids": raw["bids"][: self.policy.recorder_depth_levels],
                        "asks": raw["asks"][: self.policy.recorder_depth_levels],
                    }
                row["data"][key] = {"raw": raw, "checked_ms": checked, "fresh": available}
                if not available:
                    row["gaps"].append(key.upper() + "_STALE_OR_UNTIMESTAMPED")
            except Exception:
                row["gaps"].append(key.upper() + "_UNAVAILABLE")
        self._drain_decisions(writer)
        if self.policy.recorder_flow and not self.stop_event.is_set():
            try:
                end = market.server_ms()
                raw = market.get(
                    "/fapi/v1/aggTrades",
                    {"symbol": symbol, "startTime": end - 15000, "endTime": end, "limit": 1000},
                )
                flow = summarize_trades(
                    symbol, raw, end, replace(self.cfg.phase1, flow_window_ms=15000, flow_limit=1000)
                )
                checked = market.server_ms()
                fresh = (
                    0 <= checked - flow.end_ms <= self.cfg.phase1.flow_max_age_ms
                    and 0 <= checked - flow.latest_ms <= self.cfg.phase1.flow_max_age_ms
                )
                row["data"]["flow"] = {**asdict(flow), "checked_ms": checked, "fresh": fresh}
                if flow.reason != "FLOW_VALID":
                    row["gaps"].append(flow.reason)
                elif not fresh:
                    row["gaps"].append("FLOW_STALE_OR_FUTURE")
            except Exception:
                row["gaps"].append("FLOW_UNAVAILABLE")
        else:
            row["gaps"].append("FLOW_DISABLED")
        writer.append(row)
        return row

    def _run(self):
        writer = None
        market = None
        try:
            writer = SegmentWriter(self.cfg.data_dir / "recorder", self.policy)
            self.owns_writer = True
            market = self.factory()  # Independent session: recording never waits in PAPER thread.
            self._status(status="RUNNING")
            next_sample = 0.0
            previous_start = None
            while not self.stop_event.is_set():
                drained = self._drain_decisions(writer)
                if time.monotonic() < next_sample:
                    if not drained:
                        self.stop_event.wait(min(0.2, max(0, next_sample - time.monotonic())))
                    continue
                start = time.monotonic()
                if (
                    previous_start is not None
                    and start - previous_start > self.policy.recorder_interval_seconds * 1.5
                ):
                    writer.append(
                        {"kind": "gap", "code": "SAMPLING_OVERRUN", "elapsed_seconds": start - previous_start}
                    )
                previous_start = start
                with self.guard:
                    symbols = self.symbols
                writer.append(
                    {
                        "kind": "universe",
                        "symbols": symbols,
                        "dropped_decisions": self.state["dropped_decisions"],
                    }
                )
                gaps = []
                for symbol in symbols:
                    if self.stop_event.is_set():
                        break
                    self._drain_decisions(writer)
                    row = self.sample(market, writer, symbol)
                    self._drain_decisions(writer)
                    if row:
                        gaps.extend(f"{symbol}:{code}" for code in row["gaps"])
                        self._status(
                            last_sample_ms=int(time.time() * 1000), gaps=gaps, active_symbols=len(symbols)
                        )
                next_sample = start + self.policy.recorder_interval_seconds
            # PAPER removes its logging handler before stop, so this final drain
            # has a finite producer-free queue. Never retry uncertain writes.
            self._drain_decisions(writer)
            writer.finish()
            writer = None
            self._status(status="STOPPED")
        except Exception as exc:
            self._status(status="FAILED", error=type(exc).__name__)
            log.error("RECORDER_FAILED type=%s; PAPER continues", type(exc).__name__)
        finally:
            if writer:
                writer.close()  # Unknown writes are recovered only on the next startup.
            if market is not None and hasattr(market, "http"):
                market.http.close()


def verify(folder):
    """Read-only SHA validation; an active unsealed segment is explicitly pending."""
    folder = Path(folder)
    errors = []
    sealed = set()
    if (folder / "manifest.jsonl").exists():
        for line in (folder / "manifest.jsonl").open():
            try:
                row = json.loads(line)
                if "segment" not in row:
                    errors.append(row.get("event", "MANIFEST_EVENT"))
                    continue
                path = folder / row["segment"]
                sealed.add(path.name)
                if not path.exists() or digest(path) != row["sha256"]:
                    errors.append(path.name + ":SHA_MISMATCH_OR_MISSING")
                elif not row["complete"]:
                    errors.append(path.name + ":TORN_SUFFIX_RETAINED")
            except (ValueError, KeyError):
                errors.append("MANIFEST_INVALID_LINE")
    return {
        "sealed": len(sealed),
        "pending": sorted(p.name for p in folder.glob("*.jsonl.gz") if p.name not in sealed),
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Read-only recorder integrity check")
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    result = verify(args.folder)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["errors"] else 0)
