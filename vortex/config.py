"""Validated settings; paper-only by default and fail closed on unsafe modes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path

from dotenv import load_dotenv

from .operations import OperationsPolicy
from .phase1_config import StrategyPolicy
from .phase2 import RiskPolicy
from .runtime_config import RuntimePolicy


@dataclass(frozen=True)
class Settings:
    runtime: RuntimePolicy = field(default_factory=RuntimePolicy)
    operations: OperationsPolicy = field(default_factory=OperationsPolicy)
    phase1: StrategyPolicy = field(default_factory=StrategyPolicy)
    phase2: RiskPolicy = field(default_factory=RiskPolicy)
    mode: str = "paper"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
    timeframe: str = "5m"
    starting_equity: float = 1000.0
    risk_per_trade: float = 0.12
    max_daily_loss: float = 0.55
    max_positions: int = 4
    max_leverage: int = 5
    max_margin_fraction: float = 0.25
    max_spread_bps: float = 12.0
    min_score: int = 5
    min_strong_score: int = 7
    trailing_atr_mult: float = 0.8
    cooldown_minutes: int = 15
    loop_seconds: int = 20
    radar_limit: int = 24
    radar_fast_ranking: bool = False
    fee_rate: float = 0.0005
    slippage_bps: float = 3.0
    data_dir: Path = Path("data")

    def __post_init__(self) -> None:
        if self.operations.enabled and self.operations.profile == "conservative":
            # Profile only reduces risk; explicit env settings cannot exceed these caps.
            object.__setattr__(self, "risk_per_trade", min(self.risk_per_trade, 0.08))
            object.__setattr__(self, "max_positions", min(self.max_positions, 2))
            object.__setattr__(self, "max_daily_loss", min(self.max_daily_loss, 0.20))
        if self.operations.enabled and self.operations.focus_symbol:
            object.__setattr__(self, "symbols", (self.operations.focus_symbol,))
        # Production execution is not included in this release.
        if self.mode not in {"paper", "backtest"}:
            raise ValueError("RUN_MODE must be paper or backtest; live orders are disabled")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Symbols must be unique and nonempty")
        if any(not x.isalnum() or not x.endswith("USDT") for x in self.symbols):
            raise ValueError("USD-M USDT symbols only")
        if (self.phase1.enabled or self.phase2.enabled) and self.timeframe != "5m":
            raise ValueError("Phase 1/2 require TIMEFRAME=5m with 15m and 1h confirmation")
        if self.timeframe not in {"5m", "15m"}:
            raise ValueError("Supported timeframe: 5m, 15m")
        if (
            not isfinite(self.starting_equity)
            or self.starting_equity <= 0
            or not isfinite(self.risk_per_trade)
            or not 0 < self.risk_per_trade <= (0.15 if self.phase2.enabled else 0.10)
        ):
            raise ValueError("Equity or risk cap invalid")
        if not isfinite(self.max_daily_loss) or not 0 < self.max_daily_loss <= (
            0.55 if self.phase2.enabled else 0.50
        ):
            raise ValueError("Daily loss cap invalid")
        if (
            not 1 <= self.max_positions <= (4 if self.phase2.enabled else 3)
            or not 1 <= self.max_leverage <= 10
        ):
            raise ValueError("Position/leverage limit invalid")
        if not isfinite(self.max_margin_fraction) or not 0 < self.max_margin_fraction <= 0.25:
            raise ValueError("Margin cap invalid")
        if not 0 < self.max_spread_bps <= 50:
            raise ValueError("Spread cap invalid")
        if not 3 <= self.min_score <= 10:
            raise ValueError("Score threshold invalid")
        if not 3 <= self.min_strong_score <= 10:
            raise ValueError("Vote policy must be boolean with strong score 3..10")
        if not isfinite(self.trailing_atr_mult) or not 0.5 <= self.trailing_atr_mult <= 3.0:
            raise ValueError("TRAILING_ATR_MULT must be between 0.5 and 3.0")
        if self.cooldown_minutes < 0 or not 5 <= self.loop_seconds <= 300:
            raise ValueError("Polling/cooldown invalid")
        if not 1 <= self.radar_limit <= 30 or not isinstance(self.radar_fast_ranking, bool):
            raise ValueError("Radar limit must be 1..30 with a boolean fast-ranking flag")
        if (
            not isfinite(self.fee_rate)
            or not 0 <= self.fee_rate <= 0.003
            or not isfinite(self.slippage_bps)
            or not 0 <= self.slippage_bps <= (100 if self.operations.enabled else 30)
        ):
            raise ValueError("Costs invalid")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        def f(name: str, default: str) -> str:
            return os.getenv(name, default).strip()

        def boolean(name: str, default: str) -> bool:
            value = f(name, default).lower()
            if value not in {"true", "false"}:
                raise ValueError(name + " must be true or false")
            return value == "true"

        operations = OperationsPolicy.from_env()
        aggressive = operations.profile == "aggressive"
        phase1 = StrategyPolicy.from_env(
            StrategyPolicy(strict_votes=False, allow_single_strong_vote=True, min_strong_score=6)
            if aggressive
            else StrategyPolicy()
        )
        phase2 = RiskPolicy.from_env(
            RiskPolicy(aggressive_strong_risk=True, strong_max=0.18) if aggressive else RiskPolicy()
        )
        if not all((phase1.enabled, phase2.enabled, operations.enabled)):
            raise ValueError(
                "Only the current strategy/risk/operations release is supported; remove disabled PHASE1_ENABLED/PHASE2_ENABLED/OPS_ENABLED settings"
            )
        return cls(
            runtime=RuntimePolicy.from_env(),
            operations=operations,
            phase1=phase1,
            phase2=phase2,
            trailing_atr_mult=float(f("TRAILING_ATR_MULT", "0.8")),
            min_strong_score=phase1.min_strong_score,
            mode=f("RUN_MODE", "paper"),
            symbols=tuple(
                s.strip().upper()
                for s in f("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT").split(",")
                if s.strip()
            ),
            timeframe=f("TIMEFRAME", "5m"),
            starting_equity=float(f("STARTING_EQUITY", "1000")),
            risk_per_trade=float(f("RISK_PER_TRADE", "0.12")),
            max_daily_loss=float(f("MAX_DAILY_LOSS", "0.55")),
            max_positions=int(f("MAX_POSITIONS", "4")),
            max_leverage=int(f("MAX_LEVERAGE", "5")),
            max_margin_fraction=float(f("MAX_MARGIN_FRACTION", "0.25")),
            max_spread_bps=float(f("MAX_SPREAD_BPS", "12")),
            min_score=int(f("MIN_SCORE", "5")),
            cooldown_minutes=int(f("COOLDOWN_MINUTES", "15")),
            loop_seconds=int(f("LOOP_SECONDS", "10" if aggressive else "20")),
            radar_limit=int(f("RADAR_LIMIT", "30" if aggressive else "24")),
            radar_fast_ranking=boolean("RADAR_FAST_RANKING", "true" if aggressive else "false"),
            fee_rate=float(f("FEE_RATE", "0.0005")),
            slippage_bps=float(f("SLIPPAGE_BPS", "3")),
            data_dir=Path(f("DATA_DIR", "data")),
        )
