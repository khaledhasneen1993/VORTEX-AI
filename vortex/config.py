"""Validated settings; paper-only by default and fail closed on unsafe modes."""
from __future__ import annotations
import os
from math import isfinite
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from .phase1_config import StrategyPolicy
from .phase2 import RiskPolicy
from .operations import OperationsPolicy


@dataclass(frozen=True)
class Settings:
    operations: OperationsPolicy = field(default_factory=OperationsPolicy)
    phase1: StrategyPolicy = field(default_factory=StrategyPolicy)
    phase2: RiskPolicy = field(default_factory=RiskPolicy)
    mode: str = "paper"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
    timeframe: str = "5m"
    starting_equity: float = 1000.0
    risk_per_trade: float = 0.10
    max_daily_loss: float = 0.50
    max_positions: int = 3
    max_leverage: int = 5
    max_margin_fraction: float = 0.25
    max_spread_bps: float = 12.0
    min_score: int = 5
    strict_votes: bool = True
    min_strong_score: int = 7
    trailing_atr_mult: float = 1.0
    cooldown_minutes: int = 15
    loop_seconds: int = 20
    fee_rate: float = 0.0005
    slippage_bps: float = 3.0
    data_dir: Path = Path("data")

    def __post_init__(self) -> None:
        if self.operations.enabled and self.operations.profile == 'conservative':
            # Profile only reduces risk; explicit env settings cannot exceed these caps.
            object.__setattr__(self, 'risk_per_trade', min(self.risk_per_trade, .08))
            object.__setattr__(self, 'max_positions', min(self.max_positions, 2))
            object.__setattr__(self, 'max_daily_loss', min(self.max_daily_loss, .20))
        if self.operations.enabled and self.operations.focus_symbol:
            object.__setattr__(self, 'symbols', (self.operations.focus_symbol,))
        # Real-money execution is deliberately not shipped in version 0.1.
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
        if (not isfinite(self.starting_equity) or self.starting_equity <= 0
                or not isfinite(self.risk_per_trade)
                or not 0 < self.risk_per_trade <= (0.15 if self.phase2.enabled else 0.10)):
            raise ValueError("Equity or risk cap invalid")
        if not isfinite(self.max_daily_loss) or not 0 < self.max_daily_loss <= (0.55 if self.phase2.enabled else 0.50):
            raise ValueError("Daily loss cap invalid")
        if not 1 <= self.max_positions <= (4 if self.phase2.enabled else 3) or not 1 <= self.max_leverage <= 10:
            raise ValueError("Position/leverage limit invalid")
        if not isfinite(self.max_margin_fraction) or not 0 < self.max_margin_fraction <= 0.25:
            raise ValueError("Margin cap invalid")
        if not 0 < self.max_spread_bps <= 50:
            raise ValueError("Spread cap invalid")
        if not 3 <= self.min_score <= 10:
            raise ValueError("Score threshold invalid")
        if not isinstance(self.strict_votes, bool) or not 3 <= self.min_strong_score <= 10:
            raise ValueError("Vote policy must be boolean with strong score 3..10")
        if not isfinite(self.trailing_atr_mult) or not 0.5 <= self.trailing_atr_mult <= 3.0:
            raise ValueError("TRAILING_ATR_MULT must be between 0.5 and 3.0")
        if self.cooldown_minutes < 0 or not 5 <= self.loop_seconds <= 300:
            raise ValueError("Polling/cooldown invalid")
        if (not isfinite(self.fee_rate) or not 0 <= self.fee_rate <= 0.003
                or not isfinite(self.slippage_bps) or not 0 <= self.slippage_bps <= (100 if self.operations.enabled else 30)):
            raise ValueError("Costs invalid")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        def f(name: str, default: str) -> str:
            return os.getenv(name, default).strip()
        phase2 = RiskPolicy.from_env()
        operations = OperationsPolicy.from_env()
        strict = f("STRICT_VOTES", "true").lower()
        if strict not in {"true", "false"}:
            raise ValueError("STRICT_VOTES must be true or false")
        return cls(
            operations=operations,
            phase1=StrategyPolicy.from_env(),
            phase2=phase2,
            strict_votes=(strict == "true"),
            trailing_atr_mult=float(f("TRAILING_ATR_MULT", "0.8" if phase2.enabled else "1.0")),
            min_strong_score=int(f("MIN_STRONG_SCORE", "7")),
            mode=f("RUN_MODE", "paper"),
            symbols=tuple(s.strip().upper() for s in f("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT").split(",") if s.strip()),
            timeframe=f("TIMEFRAME", "5m"),
            starting_equity=float(f("STARTING_EQUITY", "1000")),
            risk_per_trade=float(f("RISK_PER_TRADE", "0.12" if phase2.enabled else "0.10")),
            max_daily_loss=float(f("MAX_DAILY_LOSS", "0.55" if phase2.enabled else "0.50")),
            max_positions=int(f("MAX_POSITIONS", "4" if phase2.enabled else "3")),
            max_leverage=int(f("MAX_LEVERAGE", "5")),
            max_margin_fraction=float(f("MAX_MARGIN_FRACTION", "0.25")),
            max_spread_bps=float(f("MAX_SPREAD_BPS", "12")),
            min_score=int(f("MIN_SCORE", "5")),
            cooldown_minutes=int(f("COOLDOWN_MINUTES", "15")),
            loop_seconds=int(f("LOOP_SECONDS", "20")),
            fee_rate=float(f("FEE_RATE", "0.0005")),
            slippage_bps=float(f("SLIPPAGE_BPS", "3")),
            data_dir=Path(f("DATA_DIR", "data")),
        )
