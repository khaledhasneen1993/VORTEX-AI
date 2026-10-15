"""Migrate local configuration to the current release without touching saved positions."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import datetime, timezone
from dataclasses import fields
from math import isfinite
from pathlib import Path

from dotenv import dotenv_values

from .approved import canonical_environment


def configure(path: Path, equity: float | None = None, basket: bool = True):
    if equity is not None and (not isfinite(equity) or equity <= 0):
        raise ValueError("Virtual equity must be positive and finite")
    from .config import Settings

    values = canonical_environment(dotenv_values(path) if path.exists() else {}, fields(Settings))
    values["DATA_DIR"] = "data/vortex-approved-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    if equity is not None:
        values["STARTING_EQUITY"] = str(equity)
    if basket:
        values.update(
            BASKET_ENABLED="true",
            MAX_MARGIN_FRACTION="0.60",
            BASKET_MIN_ENTRY_FILL_RATIO="0.90",
            BASKET_HOLD_UNTIL_TARGET="true",
            BASKET_LOSS_STARTING_EQUITY_FRACTION="0.10",
            BASKET_ANY_PROFIT_AFTER_SECONDS="0",
            BASKET_FIXED_NET_TARGET="0.20",
            BASKET_RESCAN_AFTER_CLOSE="true",
            BASKET_SMART_ADDS="true",
        )
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
    parser.add_argument("--basket", action="store_true", default=True, help="Compatibility option; baskets are always enabled")
    args = parser.parse_args()
    folder = configure(args.env, args.equity, args.basket)
    print("Current PAPER configuration saved; no engine started. New DATA_DIR:", folder)


if __name__ == "__main__":
    main()
