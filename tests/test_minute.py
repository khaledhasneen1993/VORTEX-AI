import pytest
from vortex.operations import OperationsPolicy
from vortex.models import Candle
from vortex.reversal import confirm as reversal_confirm, stoch_rsi


def test_minute_signal_never_looks_ahead():
    data = []
    for i in range(100):
        p = 100 + 0.01 * i
        data.append(Candle(i * 60000, p, p + 0.1, p - 0.1, p, 100, (i + 1) * 60000 - 1))
    assert reversal_confirm(data, 1, data[50].close_ts) is False
    assert reversal_confirm(data, -1, data[-1].close_ts) is False
    with pytest.raises(ValueError):
        reversal_confirm(data, 0, data[-1].close_ts)
    assert 0 <= stoch_rsi([b.close for b in data]) <= 100


def test_minute_history_signal_requires_completed_bars(monkeypatch):
    import vortex.backtest as module
    from vortex.backtest import run
    from vortex.config import Settings
    from vortex.risk import Filters

    main = [Candle(i * 300000, 100, 101, 99, 100, 100, (i + 1) * 300000 - 1) for i in range(80)]
    minute = [Candle(i * 60000, 100, 101, 99, 100, 100, (i + 1) * 60000 - 1) for i in range(400)]
    seen = []

    def dummy(symbol, bars, upper, score, **kwargs):
        decision = bars[-1].close_ts
        sample = kwargs["minute"]
        assert all((x.close_ts <= decision for x in sample))
        seen.append(len(sample))
        return None

    monkeypatch.setattr(module, "analyze", dummy)
    run(
        "BTCUSDT",
        main,
        [],
        Filters(0.001, 0.001, 5, 0.1),
        Settings(
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
        ),
        minute=minute,
    )
    assert seen and all((x <= 90 for x in seen))
