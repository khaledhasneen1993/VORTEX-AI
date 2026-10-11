"""Entry-time features for PAPER decision records; no model or prediction."""

from .indicators import adx, atr, rsi
from .models import Candle, Signal

FEATURES = ("volume_ratio", "rsi7", "adx14", "atr_pct", "return3", "is_long")


def feature_snapshot(bars: list[Candle], signal: Signal) -> dict[str, float]:
    if len(bars) < 65 or bars[-1].ts != signal.ts:
        raise ValueError("Feature snapshot requires exact completed signal candle")
    p = [b.close for b in bars]
    mean_vol = sum(c.volume for c in bars[-21:-1]) / 20
    if mean_vol <= 0:
        raise ValueError("Insufficient volume")
    return dict(
        zip(
            FEATURES,
            (
                bars[-1].volume / mean_vol,
                rsi(p, 7),
                adx(bars),
                atr(bars) / p[-1],
                p[-1] / p[-4] - 1,
                1.0 if signal.side == "LONG" else 0.0,
            ),
        )
    )

