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


def test_resilient_missing_critical_quote_uses_fresh_depth(monkeypatch):
    api = Market(resilient=True)
    now = 1900000000000
    calls = []

    def get(endpoint, params=None):
        calls.append((endpoint, params))
        if endpoint.endswith('/time'):
            return {'serverTime': now}
        if endpoint.endswith('/bookTicker'):
            return [{'symbol': 'BTCUSDT', 'bidPrice': '100', 'askPrice': '101', 'time': now - 5000}]
        assert params == {'symbol': 'BTCUSDT', 'limit': 5}
        return {'T': now - 100, 'bids': [['102', '1']], 'asks': [['103', '1']]}

    monkeypatch.setattr(api, 'get', get)
    assert api.quotes(now_ms=now, required_symbols=['BTCUSDT', 'BTCUSDT']) == {'BTCUSDT': (102, 103)}
    assert sum(p == '/fapi/v1/depth' for p, _ in calls) == 1


def test_depth_fallback_rejects_stale_future_empty_and_crossed(monkeypatch):
    api = Market(resilient=True)
    now = 1900000000000
    for book in [
        {'T': now - 5000, 'bids': [['100', '1']], 'asks': [['101', '1']]},
        {'T': now + 5000, 'bids': [['100', '1']], 'asks': [['101', '1']]},
        {'T': now, 'bids': [], 'asks': []},
        {'T': now, 'bids': [['102', '1']], 'asks': [['101', '1']]},
        {'T': now, 'bids': [['100', '0']], 'asks': [['101', '1']]},
        {'bids': [['100', '1']], 'asks': [['101', '1']]},
    ]:
        monkeypatch.setattr(api, 'get', lambda p, params=None: (
            {'serverTime': now} if p.endswith('/time') else [] if p.endswith('/bookTicker') else book
        ))
        assert api.quotes(now_ms=now, required_symbols=['BTCUSDT']) == {}


def test_recovery_never_keeps_quotes_aged_during_later_requests(monkeypatch):
    api = Market(resilient=True)
    now = 1900000000000
    clock = [now]

    def get(p, params=None):
        if p.endswith('/time'):
            return {'serverTime': clock[0]}
        if p.endswith('/bookTicker'):
            return [{'symbol': 'BTCUSDT', 'bidPrice': '100', 'askPrice': '101', 'time': now}]
        clock[0] += 5000
        return {'T': clock[0], 'bids': [['50', '1']], 'asks': [['51', '1']]}

    monkeypatch.setattr(api, 'get', get)
    assert api.quotes(now_ms=now, required_symbols=['ETHUSDT']) == {'ETHUSDT': (50, 51)}


def test_recovery_stays_off_by_default(monkeypatch):
    api = Market()
    monkeypatch.setattr(api, 'get', lambda p, params=None: [])
    assert api.quotes(now_ms=1900000000000, required_symbols=['BTCUSDT']) == {}


def test_bulk_failure_can_recover_only_fresh_critical_depth(monkeypatch):
    from vortex.binance import MarketError
    api = Market(resilient=True)
    now = 1900000000000

    def get(p, params=None):
        if p.endswith('/time'):
            return {'serverTime': now}
        if p.endswith('/bookTicker'):
            raise MarketError('unavailable')
        return {'T': now, 'bids': [['100', '1']], 'asks': [['101', '1']]}

    monkeypatch.setattr(api, 'get', get)
    assert api.quotes(now_ms=now, required_symbols=['BTCUSDT']) == {'BTCUSDT': (100, 101)}
