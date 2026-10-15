"""Two-to-five-position PAPER contract; fixture defaults retain old saved-policy schemas."""

import os
from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class BasketPolicy:
    enabled: bool = False
    size: int = 5
    min_size: int = 5
    entry_margin_fraction: float = 0.10
    profit_margin: float = 0.03
    fixed_net_target: float = 0.0
    rescan_after_close: bool = False
    add_after_seconds: int = 300
    add_count: int = 2
    add_fraction: float = 0.50
    max_seconds: int = 900
    margin_cap_fraction: float = 0.60
    min_entry_fill_ratio: float = 0.0  # Off until explicitly selected by the basket launcher.
    hold_until_target: bool = False
    loss_starting_equity_fraction: float = 0.0
    any_profit_after_seconds: int = 0
    smart_adds: bool = False
    smart_add_interval_seconds: int = 300
    smart_add_max_rounds: int = 3
    smart_add_step_atr: float = 0.5

    def __post_init__(self):
        if (
            not isinstance(self.enabled, bool)
            or not isinstance(self.hold_until_target, bool)
            or not isinstance(self.rescan_after_close, bool)
            or not isinstance(self.smart_adds, bool)
        ):
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
                    "min_size",
                    "fixed_net_target",
                    "rescan_after_close",
                    "min_entry_fill_ratio",
                    "hold_until_target",
                    "loss_starting_equity_fraction",
                    "any_profit_after_seconds",
                    "smart_adds",
                    "smart_add_interval_seconds",
                    "smart_add_max_rounds",
                    "smart_add_step_atr",
                }
            )
            != expected
        ):
            raise ValueError(
                "Basket contract is 5 positions, 10% margin, 3% target, one 2-position half add at 5m, 15m max"
            )
        if type(self.min_size) is not int or not 2 <= self.min_size <= self.size:
            raise ValueError("BASKET_MIN_SIZE must be an integer between 2 and 5")
        if not 0 <= self.fixed_net_target <= 10:
            raise ValueError("BASKET_FIXED_NET_TARGET must be 0..10 USDT; zero retains historical target")
        if not 0 <= self.min_entry_fill_ratio <= 1:
            raise ValueError("BASKET_MIN_ENTRY_FILL_RATIO must be 0..1; zero disables it")
        if not 0 <= self.loss_starting_equity_fraction <= 0.25:
            raise ValueError("BASKET_LOSS_STARTING_EQUITY_FRACTION must be 0..0.25; zero disables it")
        if self.hold_until_target and self.loss_starting_equity_fraction <= 0:
            raise ValueError("Holding without a deadline requires a basket loss threshold")

        if not 0 <= self.any_profit_after_seconds <= 86400:
            raise ValueError("BASKET_ANY_PROFIT_AFTER_SECONDS must be 0..86400")
        if not 300 <= self.smart_add_interval_seconds <= 3600 or not 1 <= self.smart_add_max_rounds <= 10:
            raise ValueError("Smart add interval must be 300..3600 seconds, rounds 1..10")
        if not 0.1 <= self.smart_add_step_atr <= 5:
            raise ValueError("BASKET_SMART_ADD_STEP_ATR must be 0.1..5")

    @classmethod
    def from_env(cls):
        from .approved import APPROVED_ENV

        def setting(key, fallback):
            return os.getenv(key, APPROVED_ENV.get(key, fallback))

        raw = setting("BASKET_ENABLED", "false").strip().lower()
        if raw not in {"true", "false"}:
            raise ValueError("BASKET_ENABLED must be true or false")
        hold = setting("BASKET_HOLD_UNTIL_TARGET", "false").strip().lower()
        if hold not in {"true", "false"}:
            raise ValueError("BASKET_HOLD_UNTIL_TARGET must be true or false")
        smart = setting("BASKET_SMART_ADDS", "false").strip().lower()
        if smart not in {"true", "false"}:
            raise ValueError("BASKET_SMART_ADDS must be true or false")
        rescan = setting("BASKET_RESCAN_AFTER_CLOSE", "false").strip().lower()
        if rescan not in {"true", "false"}:
            raise ValueError("BASKET_RESCAN_AFTER_CLOSE must be true or false")
        return cls(
            enabled=raw == "true",
            min_size=int(setting("BASKET_MIN_SIZE", "5")),
            fixed_net_target=float(setting("BASKET_FIXED_NET_TARGET", "0")),
            rescan_after_close=rescan == "true",
            min_entry_fill_ratio=float(setting("BASKET_MIN_ENTRY_FILL_RATIO", "0")),
            hold_until_target=hold == "true",
            any_profit_after_seconds=int(setting("BASKET_ANY_PROFIT_AFTER_SECONDS", "0")),
            smart_adds=smart == "true",
            smart_add_interval_seconds=int(setting("BASKET_SMART_ADD_INTERVAL_SECONDS", "300")),
            smart_add_max_rounds=int(setting("BASKET_SMART_ADD_MAX_ROUNDS", "3")),
            smart_add_step_atr=float(setting("BASKET_SMART_ADD_STEP_ATR", "0.5")),
            loss_starting_equity_fraction=float(setting("BASKET_LOSS_STARTING_EQUITY_FRACTION", "0")),
        )
