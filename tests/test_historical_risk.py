"""Regression checks for the real historical risk and warmup invariants.

These are CODE tests, not proof of profitability, exchange fills or uptime.
"""
from datetime import datetime, timezone
import pytest
from vortex.backtest import run
from vortex.portfolio import run_portfolio
from vortex.risk import Filters, RiskGate
from vortex.config import Settings
from vortex.models import Candle
from vortex.binance import Market

DAY = 86_400_000
START = int(datetime(2026, 10, 8, 20, tzinfo=timezone.utc).timestamp() * 1000)
FILTERS = Filters(.001, .001, 5., .01)


def bars(n=80, start=START, step=300000):
    return [Candle(start + i*step, 100., 101., 99., 100., 100.,
                   start + (i+1)*step - 1) for i in range(n)]


def test_single_backtest_uses_each_historical_utc_date(monkeypatch):
    seen = []
    original = RiskGate.new_day

    def spy(self, date, equity):
        seen.append(date)
        return original(self, date, equity)

    monkeypatch.setattr(RiskGate, "new_day", spy)
    report = run("BTCUSDT", bars(), [], FILTERS, Settings())
    assert report["closed_trades"] == 0
    assert seen
    assert seen[0] == "2026-10-08"
    assert seen[-1] == "2026-10-09"
    assert len(set(seen)) == 2


def test_portfolio_resets_utc_risk_before_entries(monkeypatch):
    sequence = []
    original = RiskGate.new_day

    def spy(self, date, equity):
        sequence.append((date, equity))
        return original(self, date, equity)

    monkeypatch.setattr(RiskGate, "new_day", spy)
    one = bars()
    report = run_portfolio({"BTCUSDT": one, "ETHUSDT": one},
                           {"BTCUSDT": [], "ETHUSDT": []},
                           {"BTCUSDT": FILTERS, "ETHUSDT": FILTERS},
                           Settings())
    assert report["closed_trades"] == 0
    assert sequence[0][0] == "2026-10-08"
    assert sequence[-1][0] == "2026-10-09"
    assert all(value == pytest.approx(1000.) for _, value in sequence)


def test_daily_halt_never_unlatches_automatically():
    gate = RiskGate(Settings(), 1000.)
    gate.new_day("2026-10-08", 1000.)
    assert not gate.can_open(949., 0)[0]
    assert gate.blocked
    gate.new_day("2026-10-09", 949.)
    assert not gate.can_open(949., 0)[0]


def test_hourly_history_uses_full_ten_day_warmup(monkeypatch):
    market = Market()
    market._exchange = {"BTCUSDT": {}}
    sent = []

    def stub_get(endpoint, params):
        assert endpoint == "/fapi/v1/klines"
        sent.append(dict(params))
        step = 3_600_000 if params["interval"] == "1h" else 300_000
        opening = params["startTime"]
        # a small correctly-ordered historical page
        return [[opening + i*step, "100", "101", "99", "100", "100",
                 opening + (i+1)*step - 1] for i in range(100)]

    monkeypatch.setattr(market, "get", stub_get)
    moment = 200 * DAY
    market.history("BTCUSDT", "1h", 1, moment)
    market.history("BTCUSDT", "5m", 1, moment)
    assert sent[0]["startTime"] == moment - 11*DAY
    assert sent[1]["startTime"] == moment - 3*DAY


def test_no_market_api_or_pnl_needed_to_run_risk_regressions():
    cfg = Settings(mode="paper")
    assert cfg.risk_per_trade == 0.01
    assert cfg.max_daily_loss == .05
    assert cfg.max_consecutive_losses == 5
