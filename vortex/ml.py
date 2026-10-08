"""Strict opt-in offline ML filter, trained only on genuine time-ordered labeled fills.

Model *abstains* unless it improves held-out Brier score over a constant baseline.
No model is shipped or trained on invented market outcomes. It cannot choose
leverage, margin, protective prices or override RiskGate.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from .models import Candle, Signal
from .indicators import adx, atr, rsi

FEATURES = ("volume_ratio", "rsi7", "adx14", "atr_pct", "return3", "is_long")


def feature_snapshot(bars: list[Candle], signal: Signal) -> dict[str, float]:
    if len(bars) < 65 or bars[-1].ts != signal.ts:
        raise ValueError("Feature snapshot requires exact completed signal candle")
    p = [b.close for b in bars]
    mean_vol = sum(c.volume for c in bars[-21:-1]) / 20
    if mean_vol <= 0:
        raise ValueError("Insufficient volume")
    return dict(zip(FEATURES, (
        bars[-1].volume / mean_vol, rsi(p, 7), adx(bars),
        atr(bars) / p[-1], p[-1] / p[-4] - 1, 1.0 if signal.side == "LONG" else 0.0)))


def sigmoid(x: float) -> float:
    x = max(-30.0, min(30.0, x))
    return 1 / (1 + math.exp(-x))


def evaluate(model: dict, features: dict[str, float]) -> float | None:
    if not model.get("validated") or tuple(model.get("features", ())) != FEATURES:
        return None
    values = [float(features[x]) for x in FEATURES]
    if not all(math.isfinite(x) for x in values):
        return None
    means, scales = model["mean"], model["scale"]
    zs = [(v - m) / s for v, m, s in zip(values, means, scales)]
    return sigmoid(model["bias"] + sum(w * z for w, z in zip(model["weights"], zs)))


def load_model(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "vortex-logistic-v1" or not data.get("validated"):
        raise ValueError("No validated forward-safe ML filter exists")
    return data


def train(records: list[dict]) -> dict:
    """Chronological train -> purge overlapping labels -> holdout evaluation.

    Records must contain timestamp of signal, independent close/label timestamp,
    binary y (net profitable trade) and all entry-time features.
    """
    if len(records) < 250:
        raise ValueError("At least 250 genuine closed labeled trades needed")
    ordered = sorted(records, key=lambda r: r["entry_ts"])
    if any(int(r["exit_ts"]) < int(r["entry_ts"]) for r in ordered):
        raise ValueError("Exit before entry: invalid label")
    n = len(ordered)
    split = int(n * .8)
    boundary = int(ordered[split]["entry_ts"])
    first = [r for r in ordered[:split] if int(r["exit_ts"]) < boundary]
    holdout = ordered[split:]
    if len(first) < 150 or len(holdout) < 50:
        raise ValueError("Insufficient purged train/holdout samples")
    def xrow(r):
        x = [float(r["features"][f]) for f in FEATURES]
        if not all(math.isfinite(v) for v in x):
            raise ValueError("Nonfinite historical feature")
        if r["y"] not in (0, 1):
            raise ValueError("Binary labels only")
        return x, int(r["y"])
    train_xy, test_xy = list(map(xrow, first)), list(map(xrow, holdout))
    means = [sum(x[j] for x, _ in train_xy) / len(train_xy) for j in range(len(FEATURES))]
    scales = [max(1e-6, math.sqrt(sum((x[j]-means[j]) ** 2 for x, _ in train_xy) /
                                  len(train_xy))) for j in range(len(FEATURES))]
    weights = [0.0] * len(FEATURES)
    base_rate = sum(y for _, y in train_xy) / len(train_xy)
    base_rate = max(1e-4, min(1 - 1e-4, base_rate))
    bias = math.log(base_rate / (1 - base_rate))
    # Full-batch ridge logistic gradient descent, deterministic and bounded.
    for _ in range(300):
        gw, gb = [0.] * len(FEATURES), 0.
        for x, y in train_xy:
            norm = [max(-8, min(8, (v-m)/s)) for v, m, s in zip(x, means, scales)]
            error = sigmoid(bias + sum(w * z for w, z in zip(weights, norm))) - y
            gb += error
            for j in range(len(FEATURES)):
                gw[j] += error * norm[j]
        for j in range(len(FEATURES)):
            weights[j] -= .08 * (gw[j] / len(train_xy) + .05 * weights[j])
        bias -= .08 * gb / len(train_xy)
    brier_model, brier_base = 0., 0.
    for x, y in test_xy:
        zs = [max(-8, min(8, (v-m)/s)) for v, m, s in zip(x, means, scales)]
        p = sigmoid(bias + sum(w * z for w, z in zip(weights, zs)))
        brier_model += (p - y) ** 2
        brier_base += (base_rate - y) ** 2
    brier_model /= len(test_xy)
    brier_base /= len(test_xy)
    # A failed model is recorded but must never be used as entry permission.
    validated = brier_model < brier_base - .005
    return {"format": "vortex-logistic-v1", "features": list(FEATURES),
            "mean": means, "scale": scales, "weights": weights, "bias": bias,
            "validated": validated, "train_rows": len(first),
            "holdout_rows": len(holdout), "purged_rows": split - len(first),
            "holdout_brier": round(brier_model, 7),
            "baseline_brier": round(brier_base, 7),
            "warning": "Historical holdout ≠ future return. Never grant ML risk authority."}


def train_jsonl(data_path: Path, model_path: Path) -> dict:
    records = [json.loads(s) for s in data_path.read_text(encoding="utf-8").splitlines() if s]
    model = train(records)
    # A result is saved for evaluation even when FAILED; loader refuses unvalidated.
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return model
