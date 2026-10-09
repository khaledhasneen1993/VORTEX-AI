"""Public market freshness must be enforced in BOTH REST and WS paths."""

from vortex.binance import Market


def test_rest_book_ticker_rejects_old_time_and_future_quotes(monkeypatch):
    api = Market()
    now = 1900000000000
    result = [
        {"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.1", "time": now - 500},
        {"symbol": "ETHUSDT", "bidPrice": "50", "askPrice": "50.1", "time": now - 5000},
        {"symbol": "SOLUSDT", "bidPrice": "10", "askPrice": "10.1", "time": now + 5000},
        {"symbol": "BNBUSDT", "bidPrice": "50", "askPrice": "49", "time": now},
        {"symbol": "XRPUSDT", "bidPrice": "2", "askPrice": "2.01"},
    ]
    monkeypatch.setattr(api, "get", lambda endpoint, params=None: result)
    assert api.quotes(now_ms=now) == {"BTCUSDT": (100.0, 100.1)}


def test_rest_fails_closed_without_market_quote(monkeypatch):
    api = Market()
    now = 1900000000000
    monkeypatch.setattr(
        api,
        "get",
        lambda endpoint, params=None: {
            "symbol": "BTCUSDT",
            "bidPrice": "100",
            "askPrice": "100.1",
            "time": now - 10000,
        },
    )
    assert api.quotes(now_ms=now) == {}
