"""Migrate local configuration to the current release without touching saved positions."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from dotenv import dotenv_values


def configure(path: Path, equity: float | None = None):
    if equity is not None and (not isfinite(equity) or equity <= 0):
        raise ValueError("Virtual equity must be positive and finite")
    values = dict(dotenv_values(path)) if path.exists() else {}
    values.pop("STRICT_VOTES", None)
    values.update(
        RUN_MODE="paper",
        PHASE1_ENABLED="true",
        PHASE2_ENABLED="true",
        OPS_ENABLED="true",
        RISK_PER_TRADE="0.12",
        MAX_POSITIONS="4",
        MAX_DAILY_LOSS="0.55",
        TRAILING_ATR_MULT="0.8",
        MAX_LEVERAGE="5",
        MAX_MARGIN_FRACTION="0.25",
        TIMEFRAME="5m",
        USE_RADAR="true",
        USE_WEBSOCKET="false",
        OPS_TELEGRAM_ALERTS="false",
        DATA_DIR="data/vortex-020-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f"),
    )
    if equity is not None:
        values["STARTING_EQUITY"] = str(equity)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".vortex-env-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as out:
            for key, value in values.items():
                if value is None:
                    out.write(key + "\n")
                else:
                    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
                    out.write(key + "='" + escaped + "'\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return values["DATA_DIR"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--equity", type=float)
    args = parser.parse_args()
    folder = configure(args.env, args.equity)
    print("Current PAPER configuration saved; no engine started. New DATA_DIR:", folder)


if __name__ == "__main__":
    main()
