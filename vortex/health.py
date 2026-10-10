"""Opt-in progress/coverage snapshots. Missing readings are never healthy zeros."""

import json
import logging
import time

log = logging.getLogger("vortex.health")


class LiveHealth:
    def __init__(self, cfg):
        self.enabled = cfg.runtime.health_enabled
        self.path = cfg.data_dir / "health.json"
        self.row = {
            "mode": "PAPER",
            "status": "STARTING",
            "symbols": {},
            "started_ms": int(time.time() * 1000),
        }
        self.last_write = 0.0

    def update(self, force=False, **fields):
        if not self.enabled:
            return
        self.row.update(fields)
        self.row["progress_ms"] = int(time.time() * 1000)
        if not force and time.monotonic() - self.last_write < 1:
            return
        try:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.row, allow_nan=False))
            temp.replace(self.path)
            self.last_write = time.monotonic()
        except (OSError, ValueError):
            log.warning("HEALTH_WRITE_FAILED")

    def observe(self, symbol, now, funding, flow, strategy):
        if not self.enabled:
            return
        funding_code = "FUNDING_MISSING"
        if funding:
            funding_code = "FUNDING_FRESH" if 0 <= now - funding[0] <= 15000 else "FUNDING_STALE"
        from .orderflow import flow_direction

        _, flow_code = flow_direction(flow, symbol, now, strategy)
        self.row["symbols"][symbol] = {"checked_ms": now, "funding": funding_code, "flow": flow_code}
        log.info("DATA_HEALTH %s funding=%s flow=%s", symbol, funding_code, flow_code)
        self.update(stage="strategy", force=True)


def read_health(folder, max_age_ms=30000, now_ms=None):
    now = int(time.time() * 1000) if now_ms is None else now_ms
    result = {}
    for name in ("health", "recorder/health"):
        path = folder / (name + ".json")
        try:
            row = json.loads(path.read_text())
            stamp = row.get("progress_ms", row.get("updated_ms", 0))
            row["age_ms"] = now - stamp
            if not 0 <= now - stamp <= max_age_ms:
                row["status"] = "STALE_OR_STOPPED"
            if name == "recorder/health" and row.get("last_sample_ms") is not None:
                row["sample_age_ms"] = now - row["last_sample_ms"]
            # Derivative/flow labels describe their timestamp, never perpetual freshness.
            for observation in row.get("symbols", {}).values():
                observation["age_ms"] = now - observation["checked_ms"]
            result[name] = row
        except (OSError, ValueError, KeyError):
            result[name] = {"status": "UNAVAILABLE_OR_DISABLED"}
    return result
