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


def test_one_bulk_refresh_recovers_early_held_quote_without_restamping(monkeypatch):
    api = Market(resilient=True)
    clock = [1900000000000]
    initial = clock[0]
    bulk_calls = [0]
    def get(path, params=None):
        if path.endswith('/time'):
            return {'serverTime': clock[0]}
        if path.endswith('/bookTicker'):
            bulk_calls[0] += 1
            return [{'symbol': 'BTCUSDT', 'bidPrice': '100', 'askPrice': '101',
                     'time': initial if bulk_calls[0] == 1 else clock[0]}]
        clock[0] += 5000
        return {'T': clock[0], 'bids': [['50', '1']], 'asks': [['51', '1']]}
    monkeypatch.setattr(api, 'get', get)
    assert api.quotes(now_ms=initial, required_symbols=['BTCUSDT', 'ETHUSDT']) == {
        'BTCUSDT': (100, 101), 'ETHUSDT': (50, 51)}
    assert bulk_calls[0] == 2
    assert api.quotes_checked_ms == clock[0]


def test_nonbasket_mark_uses_completed_quote_clock(tmp_path, monkeypatch):
    from vortex import cli
    from vortex.config import Settings
    from vortex.paper import PaperBroker
    from vortex.paper_experiment import PaperExperiment
    from vortex.runtime_config import RuntimePolicy

    cfg = Settings(data_dir=tmp_path, experiment=PaperExperiment(enabled=True),
                   runtime=RuntimePolicy(live_resilience=True))
    monkeypatch.setattr(cli.Settings, 'from_env', lambda: cfg)
    monkeypatch.setenv('USE_RADAR', 'false')
    class SlowPublic:
        def __init__(self, **kwargs):
            pass
        def metadata(self):
            return {s: {} for s in cfg.symbols}
        def server_ms(self):
            return 300000
        def quotes(self, **kwargs):
            self.quotes_checked_ms = 302000
            return {}
    monkeypatch.setattr(cli, 'Market', SlowPublic)
    calls = []
    original = PaperBroker.mark
    def mark(self, quotes, now, *args):
        calls.append(now)
        return original(self, quotes, now, *args)
    monkeypatch.setattr(PaperBroker, 'mark', mark)
    monkeypatch.setattr(cli, 'refresh_open_position_atr',
                        lambda *args: (_ for _ in ()).throw(AssertionError('No ATR I/O after fresh quotes')))
    assert cli.main(['paper', '--once']) == 0
    assert calls == [302000]


def test_explicit_fifteen_critical_quotes_keep_default_bound_and_freshness(monkeypatch):
    import pytest
    now = 1900000000000
    names = [f"S{i}USDT" for i in range(15)]
    rows = [{"symbol": s, "bidPrice": "10", "askPrice": "10.01", "time": now} for s in names]
    rows[-1]["time"] = now - 5000
    def get(path, params=None):
        if path.endswith('/time'):
            return {'serverTime': now}
        if path.endswith('/bookTicker'):
            return rows
        return {'T': now - 5000, 'bids': [['10', '1']], 'asks': [['10.01', '1']]}
    default = Market(resilient=True)
    monkeypatch.setattr(default, 'get', get)
    with pytest.raises(ValueError, match='At most 6'):
        default.quotes(now_ms=now, required_symbols=names)
    expanded = Market(resilient=True, critical_symbol_limit=15)
    monkeypatch.setattr(expanded, 'get', get)
    quotes = expanded.quotes(now_ms=now, required_symbols=names)
    assert set(quotes) == set(names[:-1])  # Enlarged count never accepts stale data.
    with pytest.raises(ValueError, match='At most 15'):
        expanded.quotes(now_ms=now, required_symbols=[*names, 'OVERUSDT'])
    for limit in (0, True, 16, 30):
        with pytest.raises(ValueError):
            Market(critical_symbol_limit=limit)


def test_fifteen_critical_recovery_stays_six_depths_and_one_bulk_refresh(monkeypatch):
    api = Market(resilient=True, critical_symbol_limit=15)
    now = 1900000000000
    names = [f"S{i}USDT" for i in range(15)]
    calls = []
    def get(path, params=None):
        calls.append(path)
        if path.endswith('/time'):
            return {'serverTime': now}
        if path.endswith('/bookTicker'):
            return []
        return {'T': now, 'bids': [['10', '1']], 'asks': [['10.01', '1']]}
    monkeypatch.setattr(api, 'get', get)
    result = api.quotes(now_ms=now, required_symbols=names)
    assert set(result) == set(names[:6])
    assert calls.count('/fapi/v1/depth') == 6
    assert calls.count('/fapi/v1/ticker/bookTicker') == 2
    assert api.quotes_checked_ms == now
