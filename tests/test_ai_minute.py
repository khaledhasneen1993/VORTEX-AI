"""Mocked deterministic AI/minute-signal policy regression tests."""
import json
import pytest
from vortex.models import Candle, Signal
from vortex.claude_review import confirm, ReviewUnavailable
from vortex.reversal import stoch_rsi, confirm as reversal_confirm


class MockResponse:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass
    def json(self):
        return {"content": [{"type": "text", "text": self.text}]}


class Session:
    def __init__(self, content):
        self.content = content
        self.posts = []
    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return MockResponse(self.content)


S = Signal("BTCUSDT", "LONG", 1, 100, 98, 106, 7, "two independent strategies")


def test_claude_may_only_confirm_bounded_signal():
    session = Session(json.dumps({"approved": True, "confidence": 0.8,
                                  "rationale": "Confirmed"}))
    approved, confidence, _ = confirm(S, session=session, api_key="TEST-ONLY",
                                      model="claude-test-mock")
    assert approved and confidence == .8
    assert session.posts[0][0] == "https://api.anthropic.com/v1/messages"
    assert session.posts[0][1]["headers"]["x-api-key"] == "TEST-ONLY"
    payload = session.posts[0][1]["json"]
    assert "max_tokens" in payload
    assert "api_key" not in str(payload).lower()
    assert "leverage" not in str(payload["messages"]).lower()


def test_claude_fails_closed_on_missing_api_key_or_malformed_result():
    with pytest.raises(ReviewUnavailable):
        confirm(S, api_key="")
    for answer in ['{"approved": "yes", "confidence": 1, "rationale": "X"}',
                   '{"approved": true, "confidence": 10, "rationale": "X"}',
                   'YES']:
        with pytest.raises(ReviewUnavailable):
            confirm(S, session=Session(answer), api_key="MOCK", model="claude-test")
    assert confirm(S, session=Session(json.dumps(
        {"approved": False, "confidence": .9, "rationale": "X"})),
        api_key="MOCK", model="claude-test")[0] is False


def test_minute_signal_never_looks_ahead():
    data = []
    for i in range(100):
        p = 100 + .01 * i
        data.append(Candle(i * 60_000, p, p+.1, p-.1, p, 100,
                           (i+1)*60_000 - 1))
    assert reversal_confirm(data, 1, data[50].close_ts) is False
    assert reversal_confirm(data, -1, data[-1].close_ts) is False
    with pytest.raises(ValueError):
        reversal_confirm(data, 0, data[-1].close_ts)
    assert 0 <= stoch_rsi([b.close for b in data]) <= 100


def test_minute_history_signal_requires_completed_bars(monkeypatch):
    from vortex.backtest import run
    import vortex.backtest as module
    from vortex.config import Settings
    from vortex.risk import Filters
    main = [Candle(i*300_000, 100, 101, 99, 100, 100, (i+1)*300_000-1)
            for i in range(80)]
    minute = [Candle(i*60_000, 100, 101, 99, 100, 100, (i+1)*60_000-1)
              for i in range(400)]
    seen = []
    def dummy(symbol, bars, upper, score, **kwargs):
        decision = bars[-1].close_ts
        sample = kwargs["minute"]
        assert all(x.close_ts <= decision for x in sample)
        seen.append(len(sample))
        return None
    monkeypatch.setattr(module, "analyze", dummy)
    run("BTCUSDT", main, [], Filters(.001, .001, 5, .1),
        Settings(), minute=minute)
    assert seen and all(x <= 90 for x in seen)
