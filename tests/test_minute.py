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
