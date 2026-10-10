"""Opt-in infrastructure settings; never alter financial policy."""

import os
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class RuntimePolicy:
    recorder_enabled: bool = False
    recorder_decisions: bool = False
    recorder_interval_seconds: int = 60
    recorder_rotate_bytes: int = 8 * 1024 * 1024
    recorder_rotate_seconds: int = 3600
    recorder_depth_levels: int = 10
    recorder_queue_size: int = 64
    recorder_flow: bool = True
    health_enabled: bool = False
    live_resilience: bool = False
    ws_silence_seconds: int = 30
    paper_fast_scan: bool = False
    paper_scan_workers: int = 4

    def __post_init__(self):
        bounds = {
            "recorder_interval_seconds": (15, 3600),
            "recorder_rotate_bytes": (65536, 64 * 1024 * 1024),
            "recorder_rotate_seconds": (60, 86400),
            "recorder_depth_levels": (5, 20),
            "recorder_queue_size": (1, 1024),
            "ws_silence_seconds": (10, 300),
            "paper_scan_workers": (1, 4),
        }
        for name, (lo, hi) in bounds.items():
            if not lo <= getattr(self, name) <= hi:
                raise ValueError(f"{name} outside {lo}..{hi}")
        if self.recorder_decisions and not self.recorder_enabled:
            raise ValueError("RECORDER_DECISIONS requires RECORDER_ENABLED")

    @classmethod
    def from_env(cls):
        defaults = cls()
        values = {}
        for field in fields(cls):
            value = os.getenv(field.name.upper(), str(getattr(defaults, field.name))).strip()
            if isinstance(getattr(defaults, field.name), bool):
                if value.lower() not in {"true", "false"}:
                    raise ValueError(field.name.upper() + " must be true or false")
                values[field.name] = value.lower() == "true"
            else:
                values[field.name] = int(value)
        return cls(**values)
