import pytest

from vortex.config import Settings
from vortex.manual_signals import make_card
from vortex.models import Signal
from vortex.operations import OperationsPolicy
from vortex.risk import Filters


def card(**kwargs):
    signal = Signal("BTCUSDT", "LONG", 0, 100, 90, 130, 7, "consensus", votes=("trend", "breakout"))
    return make_card(
        signal,
        99.99,
        100.01,
        300005,
        Settings(
            operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
        ),
        Filters(0.001, 0.001, 5, 0.01),
        **kwargs,
    )


def test_unset_amount_never_invents_bankroll_or_quantity():
    result = card()
    assert result["quantity"] is None
    assert result["margin_usdt"] is None
    assert result["exchange_orders"] == 0
    assert result["account_source"] == "operator_snapshot_not_connected"


def test_manual_snapshot_sizing_preserves_risk_and_margin_caps():
    result = card(equity=150, day_start_equity=150, committed_margin=0)
    assert 0 < result["margin_usdt"] <= 150 * 0.0625
    signal = result["signal"]
    assert result["quantity"] * abs(signal["entry"] - signal["stop"]) <= 150 * 0.1
    assert result["leverage"] == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"equity": 150},
        {"equity": 150, "day_start_equity": 150, "positions": 4},
        {"equity": 65, "day_start_equity": 150},
        {"equity": 150, "day_start_equity": 150, "committed_margin": 37.5},
        {"equity": float("nan"), "day_start_equity": 150},
    ],
)
def test_unsafe_or_incomplete_snapshot_produces_no_sized_card(kwargs):
    with pytest.raises(ValueError):
        card(**kwargs)


def test_stale_signal_is_not_presented_for_manual_execution():
    signal = Signal("BTCUSDT", "LONG", 0, 100, 90, 130, 7, "consensus")
    with pytest.raises(ValueError, match="Stale"):
        make_card(
            signal,
            99.99,
            100.01,
            400000,
            Settings(
                operations=OperationsPolicy(funding_guard=False, liquidity_guard=False, terminal_target=True)
            ),
            Filters(0.001, 0.001, 5, 0.01),
        )
