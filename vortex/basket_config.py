"""Opt-in five-position PAPER baskets; legacy deployment remains the default."""

import os
from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class BasketPolicy:
    enabled: bool = False
    size: int = 5
    entry_margin_fraction: float = 0.10
    profit_margin: float = 0.03
    add_after_seconds: int = 300
    add_count: int = 2
    add_fraction: float = 0.50
    max_seconds: int = 900
    margin_cap_fraction: float = 0.60
    min_entry_fill_ratio: float = 0.0  # Off until explicitly selected by the basket launcher.

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError("BASKET_ENABLED must be boolean")
        if any(not isfinite(getattr(self, f.name)) for f in fields(self) if f.name != "enabled"):
            raise ValueError("Nonfinite basket policy")
        # This feature implements the user's fixed contract, not a parameter search.
        expected = (5, 0.10, 0.03, 300, 2, 0.50, 900, 0.60)
        if (
            tuple(
                getattr(self, f.name)
                for f in fields(self)
                if f.name not in {"enabled", "min_entry_fill_ratio"}
            )
            != expected
        ):
            raise ValueError(
                "Basket contract is 5 positions, 10% margin, 3% target, one 2-position half add at 5m, 15m max"
            )
        if not 0 <= self.min_entry_fill_ratio <= 1:
            raise ValueError("BASKET_MIN_ENTRY_FILL_RATIO must be 0..1; zero disables it")

    @classmethod
    def from_env(cls):
        raw = os.getenv("BASKET_ENABLED", "false").strip().lower()
        if raw not in {"true", "false"}:
            raise ValueError("BASKET_ENABLED must be true or false")
        return cls(
            enabled=raw == "true", min_entry_fill_ratio=float(os.getenv("BASKET_MIN_ENTRY_FILL_RATIO", "0"))
        )
