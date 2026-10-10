"""Bounded public-trade CVD and taker aggression, not order-book event OFI.

No cross-cycle cache, extrapolation, account requests or synthetic trade prints.
"""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class FlowObservation:
    symbol: str
    end_ms: int
    latest_ms: int = 0
    trade_count: int = 0
    cvd_base: float | None = None
    base_imbalance: float | None = None
    aggression: float | None = None
    reason: str = "FLOW_ABSTAIN_MISSING"


def summarize_trades(symbol, trades, end_ms, policy):
    """CVD sums signed base quantity; aggression normalizes signed notional.

    Binance m=false denotes a buyer taker. Exactly a full page is uncertain
    coverage, so abstain rather than claiming to have measured the entire window.
    """

    def abstain(reason):
        return FlowObservation(symbol, end_ms, reason=reason)

    if not isinstance(trades, list) or not trades:
        return abstain("FLOW_ABSTAIN_MISSING")
    if len(trades) >= policy.flow_limit:
        return abstain("FLOW_ABSTAIN_TRUNCATED")
    buy = sell = buy_value = sell_value = 0.0
    previous_id = None
    previous_ms = 0
    try:
        for trade in trades:
            stamp, ident = int(trade["T"]), int(trade["a"])
            price, quantity = float(trade["p"]), float(trade["q"])
            maker = trade["m"]
            if (
                not isinstance(maker, bool)
                or not isfinite(price)
                or not isfinite(quantity)
                or min(price, quantity) <= 0
                or not end_ms - policy.flow_window_ms <= stamp <= end_ms
                or (previous_id is not None and ident != previous_id + 1)
                or stamp < previous_ms
            ):
                return abstain("FLOW_ABSTAIN_MALFORMED_OR_GAPPED")
            if maker:
                sell += quantity
                sell_value += price * quantity
            else:
                buy += quantity
                buy_value += price * quantity
            previous_id, previous_ms = ident, stamp
        total, notional = buy + sell, buy_value + sell_value
        if not isfinite(total + notional) or min(total, notional) <= 0:
            return abstain("FLOW_ABSTAIN_INVALID_TOTAL")
        if len(trades) < policy.flow_min_trades:
            return abstain("FLOW_ABSTAIN_INSUFFICIENT_PRINTS")
        return FlowObservation(
            symbol,
            end_ms,
            previous_ms,
            len(trades),
            buy - sell,
            (buy - sell) / total,
            (buy_value - sell_value) / notional,
            "FLOW_VALID",
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return abstain("FLOW_ABSTAIN_MALFORMED")


def flow_direction(observation, symbol, decision_ms, policy):
    """Missing/stale data abstains; valid neutral flow is a non-confirmation."""
    if not policy.flow_enabled:
        return 0, "FLOW_DISABLED"
    if observation is None:
        return 0, "FLOW_ABSTAIN_MISSING"
    if observation.symbol != symbol:
        return 0, "FLOW_ABSTAIN_SYMBOL_MISMATCH"
    if observation.reason != "FLOW_VALID":
        return 0, observation.reason
    if (
        not 0 <= decision_ms - observation.end_ms <= policy.flow_max_age_ms
        or not 0 <= decision_ms - observation.latest_ms <= policy.flow_max_age_ms
    ):
        return 0, "FLOW_ABSTAIN_STALE_OR_FUTURE"
    values = (observation.cvd_base, observation.base_imbalance, observation.aggression)
    if (
        any(v is None or not isfinite(v) for v in values)
        or observation.trade_count < policy.flow_min_trades
        or abs(observation.base_imbalance) > 1
        or abs(observation.aggression) > 1
    ):
        return 0, "FLOW_ABSTAIN_INVALID_METRICS"
    for sign in (1, -1):
        if (
            observation.cvd_base * sign > 0
            and observation.base_imbalance * sign >= policy.flow_min_imbalance
            and observation.aggression * sign >= policy.flow_min_imbalance
        ):
            return sign, "FLOW_BUY" if sign == 1 else "FLOW_SELL"
    return 0, "FLOW_NEUTRAL"


def collect_flow(market, symbol, now_ms, policy):
    """One bounded request per candidate; failures never invent confirmation."""
    if not policy.flow_enabled:
        return None
    from .binance import MarketError

    try:
        trades = market.get(
            "/fapi/v1/aggTrades",
            {
                "symbol": symbol,
                "startTime": now_ms - policy.flow_window_ms,
                "endTime": now_ms,
                "limit": policy.flow_limit,
            },
        )
        return summarize_trades(symbol, trades, now_ms, policy)
    except (MarketError, KeyError, TypeError, ValueError):
        return FlowObservation(symbol, now_ms, reason="FLOW_ABSTAIN_FETCH_FAILED")
