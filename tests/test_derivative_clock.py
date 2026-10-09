import logging

import pytest

from vortex.derivatives import DerivativesTracker


class Market:
    stamp = 1000000
    checked = 1000500
    interest = 1000

    def get(self, path, params):
        common = {"symbol": params["symbol"], "time": self.stamp}
        if path.endswith("premiumIndex"):
            return dict(common, lastFundingRate="-0.002")
        return dict(common, openInterest=str(self.interest))

    def server_ms(self):
        return self.checked


def test_delayed_symbol_uses_post_response_exchange_clock(caplog):
    market = Market()
    tracker = DerivativesTracker()
    with caplog.at_level(logging.DEBUG, logger="vortex.votes"):
        assert tracker.sample(market, "BTCUSDT", market.stamp - 30000) is None
    assert "first_open_interest_observation" in caplog.text
    assert tracker.last["BTCUSDT"] == (market.stamp, 1000)
    market.stamp += 300000
    market.checked = market.stamp + 500
    market.interest = 1010
    result = tracker.sample(market, "BTCUSDT", market.stamp - 30000)
    assert result is not None
    assert result.valid(tracker.checked_ms)
    assert result.oi_change_pct == pytest.approx(1.0)


@pytest.mark.parametrize(
    "age,reason", [(15001, "stale_funding_timestamp"), (-1001, "future_funding_timestamp")]
)
def test_invalid_exchange_age_still_abstains(age, reason, caplog):
    market = Market()
    market.checked = market.stamp + age
    tracker = DerivativesTracker()
    with caplog.at_level(logging.DEBUG, logger="vortex.votes"):
        assert tracker.sample(market, "BTCUSDT", market.stamp) is None
    assert reason in caplog.text
    assert not tracker.last


def test_duplicate_interest_remains_rejected(caplog):
    market = Market()
    tracker = DerivativesTracker()
    tracker.sample(market, "BTCUSDT", market.stamp)
    with caplog.at_level(logging.DEBUG, logger="vortex.votes"):
        assert tracker.sample(market, "BTCUSDT", market.stamp) is None
    assert "duplicate_or_out_of_order_open_interest" in caplog.text
