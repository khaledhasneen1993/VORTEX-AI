"""Offline ML policy tests: untrained/failed models MUST abstain."""
import json
import pytest
from vortex.ml import FEATURES, evaluate, load_model, train, train_jsonl
from vortex.config import Settings


def record(i, outcome):
    return {
        "entry_ts": i * 300000,
        "exit_ts": i * 300000 + 60000,
        "y": outcome,
        "features": {
            "volume_ratio": 1.6,
            "rsi7": 55.0,
            "adx14": 26.0,
            "atr_pct": .003,
            "return3": .002,
            "is_long": 1.0,
        },
    }


def test_untrained_learner_cannot_authorize_trades():
    assert evaluate({}, {f: 0 for f in FEATURES}) is None
    assert evaluate({"validated": False, "features": list(FEATURES)},
                    {f: 0 for f in FEATURES}) is None


def test_train_rejects_fake_or_insufficient_records():
    with pytest.raises(ValueError):
        train([record(i, i % 2) for i in range(249)])
    records = [record(i, i % 2) for i in range(260)]
    records[7]["exit_ts"] = records[7]["entry_ts"] - 1
    with pytest.raises(ValueError):
        train(records)


def test_training_on_no_signal_does_not_invent_edge(tmp_path):
    records = [record(i, i % 2) for i in range(300)]
    source = tmp_path / "labeled.jsonl"
    source.write_text("\n".join(json.dumps(x) for x in records), encoding="utf-8")
    output = tmp_path / "model.json"
    m = train_jsonl(source, output)
    assert m["holdout_rows"] == 60
    assert m["train_rows"] == 240
    assert not m["validated"]
    assert m["holdout_brier"] >= m["baseline_brier"] - .005
    with pytest.raises(ValueError):
        load_model(output)


def test_testnet_requires_two_explicit_permissions(monkeypatch):
    from vortex.testnet_runner import once
    from vortex.testnet_guard import ProtectionError
    cfg = Settings()
    monkeypatch.delenv("VORTEX_TESTNET_ARM", raising=False)
    with pytest.raises(PermissionError):
        once(cfg, "BTCUSDT", acknowledge=False)
    with pytest.raises(PermissionError):
        once(cfg, "BTCUSDT", acknowledge=True)
