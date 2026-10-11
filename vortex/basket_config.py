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
    hold_until_target: bool = False
    loss_starting_equity_fraction: float = 0.0

    def __post_init__(self):
        if not isinstance(self.enabled, bool) or not isinstance(self.hold_until_target, bool):
            raise ValueError("BASKET_ENABLED must be boolean")
        if any(not isfinite(getattr(self, f.name)) for f in fields(self) if f.name != "enabled"):
            raise ValueError("Nonfinite basket policy")
        # This feature implements the user's fixed contract, not a parameter search.
        expected = (5, 0.10, 0.03, 300, 2, 0.50, 900, 0.60)
        if (
            tuple(
                getattr(self, f.name)
                for f in fields(self)
                if f.name
                not in {
                    "enabled",
                    "min_entry_fill_ratio",
                    "hold_until_target",
                    "loss_starting_equity_fraction",
                }
            )
            != expected
        ):
            raise ValueError(
                "Basket contract is 5 positions, 10% margin, 3% target, one 2-position half add at 5m, 15m max"
            )
        if not 0 <= self.min_entry_fill_ratio <= 1:
            raise ValueError("BASKET_MIN_ENTRY_FILL_RATIO must be 0..1; zero disables it")
        if not 0 <= self.loss_starting_equity_fraction <= 0.25:
            raise ValueError("BASKET_LOSS_STARTING_EQUITY_FRACTION must be 0..0.25; zero disables it")
        if self.hold_until_target and self.loss_starting_equity_fraction <= 0:
            raise ValueError("Holding without a deadline requires a basket loss threshold")

    @classmethod
    def from_env(cls):
        raw = os.getenv("BASKET_ENABLED", "false").strip().lower()
        if raw not in {"true", "false"}:
            raise ValueError("BASKET_ENABLED must be true or false")
        hold = os.getenv("BASKET_HOLD_UNTIL_TARGET", "false").strip().lower()
        if hold not in {"true", "false"}:
            raise ValueError("BASKET_HOLD_UNTIL_TARGET must be true or false")
        return cls(
            enabled=raw == "true",
            min_entry_fill_ratio=float(os.getenv("BASKET_MIN_ENTRY_FILL_RATIO", "0")),
            hold_until_target=hold == "true",
            loss_starting_equity_fraction=float(os.getenv("BASKET_LOSS_STARTING_EQUITY_FRACTION", "0")),
        )
