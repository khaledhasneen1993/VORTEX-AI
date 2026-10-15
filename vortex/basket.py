"""Atomic virtual baskets. No exchange writes, prices or returns are fabricated."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, replace
from math import isfinite, ceil
from uuid import uuid4

from .models import Signal
from .operations import depth_capacity, funding_gate, slippage_bps
from .phase2 import apply_pyramid, correlation_gate, stop_exposure
from .risk import Filters, effective_leverage, floor_step, size_trade

log = logging.getLogger("vortex")


@dataclass(frozen=True)
class Candidate:
    signal: Signal
    filters: Filters
    close_ms: int
    funding: object = None
    depth: object = None


def strength(candidate):
    """Score, strong label, directional vote weight, ADX; symbol breaks ties."""
    s = candidate.signal
    f = s.features
    return (
        -s.score,
        -f.get("strong_signal", 0),
        -f.get("weighted_long" if s.side == "LONG" else "weighted_short", 0),
        -f.get("adx_5m", 0),
        s.symbol,
    )


def fresh(candidate, now, max_age_ms=90000):
    return candidate.close_ms == candidate.signal.ts + 299999 and 0 <= now - candidate.close_ms <= min(
        90000, max_age_ms
    )


def fixed_margin_size(
    signal, capital, cfg, filters, margin_used, risk_used, budget,
    margin_capital=None, *, adaptive=False,
):
    """Exact requested margin or, for opted-in initial entries, risk-sized margin.

    Basket's explicit 10% allocation replaces the legacy 6.25% entry ceiling,
    while portfolio/per-signal stop risk and total capital caps still apply.
    """
    if not cfg.basket.enabled or not isfinite(budget) or budget <= 0:
        return None
    requested = floor_step(budget * effective_leverage(cfg) / signal.entry, filters.step)
    scoped = replace(cfg, phase2=replace(cfg.phase2, entry_margin_fraction=0.25))
    sized = size_trade(
        signal,
        capital,
        scoped,
        filters,
        margin_used,
        budget,
        committed_risk=risk_used,
        margin_capital=margin_capital,
    )
    if adaptive:
        # size_trade floors lots and checks minimums, cash and existing stop-risk
        # budgets. The requested margin is a ceiling, never a required minimum.
        return sized
    if sized is None or requested <= 0 or sized[0] + filters.step * 1e-8 < requested:
        return None
    return requested, requested * signal.entry / effective_leverage(cfg)


def validate_state(broker):
    if not broker.cfg.basket.enabled:
        return
    group = broker.basket
    if group is None:
        if broker.positions:
            raise ValueError("Basket positions without a group: refuse recovery")
        return
    if (
        group.get("phase") not in {"ACTIVE", "CLOSING", "CLOSED"}
        or not broker.cfg.basket.min_size <= len(group.get("symbols", [])) <= broker.cfg.basket.size
        or len(set(group["symbols"])) != len(group["symbols"])
        or group.get("deadline_ms") != group.get("opened_ms", 0) + 900000
        or not isfinite(group.get("total_margin", 0))
        or group["total_margin"] <= 0
        or not isfinite(group.get("realized_net", 0))
        or set(group.get("initial_margins", {})) != set(group["symbols"])
        or any(not isfinite(v) or v <= 0 for v in group.get("initial_margins", {}).values())
        or not isinstance(group.get("add_decided"), bool)
    ):
        raise ValueError("Invalid saved basket")
    if broker.cfg.basket.smart_adds:
        rounds = group.get("smart_add_rounds", 0)
        prices = group.get("smart_last_add_prices", {})
        if (
            type(rounds) is not int
            or not 0 <= rounds <= broker.cfg.basket.smart_add_max_rounds
            or (
                rounds > 0
                and (
                    type(group.get("smart_last_decision_ms")) is not int
                    or group["smart_last_decision_ms"]
                    < group["opened_ms"] + broker.cfg.basket.add_after_seconds * 1000
                )
            )
            or not isinstance(prices, dict)
            or not set(prices) <= set(group["symbols"])
            or any(not isfinite(v) or v <= 0 for v in prices.values())
        ):
            raise ValueError("Invalid saved smart basket rounds")
    held = set(broker.positions)
    if not held <= set(group["symbols"]):
        raise ValueError("Orphan position outside saved basket")
    if group["phase"] == "ACTIVE" and held != set(group["symbols"]):
        raise ValueError("Active basket must contain all selected positions")
    if group["phase"] == "CLOSED" and held:
        raise ValueError("Closed basket has live positions")
    if group["phase"] == "CLOSING" and (not held or not group.get("close_reason")):
        raise ValueError("Invalid pending basket liquidation")


def projected_net(broker, quotes):
    """Same executable sides, costs and slippage as PaperBroker.mark()."""
    validate_state(broker)
    if not broker.basket:
        return None
    value = broker.basket["realized_net"]
    for symbol, p in broker.positions.items():
        if symbol not in quotes:
            return None
        bid, ask = quotes[symbol]
        if not all(isfinite(x) for x in (bid, ask)) or not 0 < bid <= ask:
            raise ValueError("Invalid basket quote")
        sign = 1 if p.side == "LONG" else -1
        slip = (
            slippage_bps(
                broker.cfg.slippage_bps,
                p.atr_value / p.entry,
                (ask - bid) / ((ask + bid) / 2) * 10000,
                broker.cfg.operations,
            )
            / 10000
        )
        price = (bid if sign == 1 else ask) * (1 - sign * slip)
        value += sign * (price - p.entry) * p.qty - p.entry_fee - price * p.qty * broker.cfg.fee_rate
    return value


def target_net(broker, now):
    group = broker.basket
    if not group:
        return None
    if broker.cfg.basket.fixed_net_target > 0:
        return broker.cfg.basket.fixed_net_target
    seconds = broker.cfg.basket.any_profit_after_seconds
    if seconds > 0 and now >= group["opened_ms"] + seconds * 1000:
        return 0.0  # Strictly greater than zero, not break-even.
    return group["total_margin"] * broker.cfg.basket.profit_margin


def exit_reason(broker, quotes, now, floor_halted=False):
    validate_state(broker)
    for symbol in broker.positions:
        if symbol in quotes:
            bid, ask = quotes[symbol]
            if not all(isfinite(x) for x in (bid, ask)) or not 0 < bid <= ask:
                raise ValueError("Invalid basket quote")
    group = broker.basket
    if not group or group["phase"] == "CLOSED":
        return None
    if group["phase"] == "CLOSING":
        return group["close_reason"]
    reason = None
    if floor_halted:
        reason = "account_equity_floor"
    elif not broker.cfg.basket.hold_until_target and now >= group["deadline_ms"]:
        reason = "basket_max_duration"
    elif any(
        (quotes[s][0 if p.side == "LONG" else 1] - p.stop) * (1 if p.side == "LONG" else -1) <= 0
        for s, p in broker.positions.items()
        if s in quotes
    ):
        reason = "basket_member_price_stop"
    else:
        net = projected_net(broker, quotes)
        loss_fraction = broker.cfg.basket.loss_starting_equity_fraction
        if net is not None and loss_fraction > 0 and net <= -broker.cfg.starting_equity * loss_fraction:
            reason = "basket_starting_equity_loss_stop"
        elif broker.cfg.basket.fixed_net_target > 0:
            if net is not None and net >= broker.cfg.basket.fixed_net_target:
                reason = "basket_fixed_net_target"
        elif (
            net is not None
            and net > 0
            and broker.cfg.basket.any_profit_after_seconds > 0
            and now >= group["opened_ms"] + broker.cfg.basket.any_profit_after_seconds * 1000
        ):
            reason = "basket_any_net_profit_after_timeout"
        elif net is not None and net >= group["total_margin"] * broker.cfg.basket.profit_margin:
            reason = "basket_net_margin_target"
    if reason:
        # Latch BEFORE any leg exits; a restart cannot switch back to entry mode.
        group.update(phase="CLOSING", close_reason=reason, close_requested_ms=now)
        broker.save()
        log.info("BASKET_CLOSE code=%s basket=%s", reason.upper(), group["id"])
    return reason


def record_exit(broker, event, now):
    group = broker.basket
    group["realized_net"] += event["gross_pnl"] - event["allocated_entry_fee"] - event["exit_fee"]
    if broker.positions:
        return None
    group.update(phase="CLOSED", closed_ms=now)
    net = group["realized_net"]
    broker.reserve.record(net)
    broker.gate.closed(net)
    broker.protection.closed(net, now)
    return dict(
        kind="basket",
        event_id=group["id"] + ":closed",
        source="paper",
        action="closed",
        ts=now,
        **copy.deepcopy(group),
    )


def _shadow(broker):
    staged = copy.deepcopy(broker)
    events = []
    staged.save = lambda: None
    staged._write_journal = lambda event: events.append(event)
    staged._basket_staging = True
    return staged, events


def _commit(broker, staged, events):
    # One atomic durable snapshot for all entries/adds. Journal replay is idempotent.
    for attr in (
        "wallet",
        "positions",
        "last_trade_ts",
        "last_signal",
        "gate",
        "protection",
        "reserve",
        "basket",
    ):
        setattr(broker, attr, getattr(staged, attr))
    broker.pending_journal = {"kind": "batch", "events": events}
    broker.save()
    broker._finish_pending()


def open_group(broker, candidates, quotes, now, histories):
    broker._finish_pending()
    validate_state(broker)
    if not broker.cfg.basket.enabled or broker.positions:
        return False, "basket already active / disabled"
    staged, events = _shadow(broker)
    equity = broker.equity(quotes)
    budget = equity * broker.cfg.basket.entry_margin_fraction
    chosen = []
    for c in sorted(candidates, key=strength):
        s = c.signal
        if not fresh(c, now, broker.cfg.phase1.max_signal_age_ms) or s.symbol not in quotes:
            log.info("ENTRY_SKIP %s reason=basket_stale_signal_or_missing_quote", s.symbol)
            continue
        bid, ask = quotes[s.symbol]
        ok, reason = staged.open(
            s,
            bid,
            ask,
            c.filters,
            quotes,
            now,
            histories,
            funding=c.funding,
            depth=c.depth,
            margin_budget=budget,
        )
        log.info(
            "BASKET_CANDIDATE %s score=%s eligible=%s code=%s reason=%s",
            s.symbol,
            s.score,
            ok,
            "BASKET_CANDIDATE_ALLOWED" if ok else "BASKET_CANDIDATE_REJECTED",
            reason,
        )
        if ok:
            chosen.append(s.symbol)
        if len(chosen) == broker.cfg.basket.size:
            break
    if len(chosen) < broker.cfg.basket.min_size:
        log.info("ENTRY_SKIP BASKET reason=basket_needs_minimum_eligible count=%d minimum=%d",
                 len(chosen), broker.cfg.basket.min_size)
        return False, f"basket needs {broker.cfg.basket.min_size} eligible: no undersized group opened"
    margins = {s: staged.positions[s].margin for s in chosen}
    staged.basket = dict(
        id=f"basket:{now}:{uuid4().hex}",
        phase="ACTIVE",
        opened_ms=now,
        deadline_ms=now + broker.cfg.basket.max_seconds * 1000,
        initial_account_equity=equity,
        initial_margins=margins,
        total_margin=sum(margins.values()),
        symbols=chosen,
        realized_net=0.0,
        add_decided=False,
    )
    for event in events:
        event["basket_id"] = staged.basket["id"]
        event["requested_margin"] = budget
        event["allocation_ratio"] = event["position"]["margin"] / budget
        event["entry_sizing"] = (
            "risk_adaptive" if broker.cfg.basket.adaptive_entry_size else "fixed_margin"
        )
    events.append(
        dict(
            kind="basket",
            event_id=staged.basket["id"] + ":opened",
            action="opened",
            ts=now,
            source="paper",
            **copy.deepcopy(staged.basket),
        )
    )
    _commit(broker, staged, events)
    for symbol in chosen:
        log.info("SIGNAL %s accepted=True: basket=%s", symbol, broker.basket["id"])
    return True, "basket opened: " + ",".join(chosen)


def _add_position(broker, c, quotes, now, histories, margin_budget=None):
    p = broker.positions[c.signal.symbol]
    bid, ask = quotes[p.symbol]
    cfg = broker.cfg
    if not 0 < bid <= ask:
        return None, "invalid_quote"
    spread = (ask - bid) / ((ask + bid) / 2) * 10000
    if spread > cfg.max_spread_bps:
        return None, "excessive_spread"
    equity = broker.equity(quotes)
    broker.protection.observe(now, equity)
    if not broker.protection.allow(now)[0] or not broker.gate.can_open(equity, 0)[0]:
        return None, "risk_halt_or_cooldown"
    allowed, reason = funding_gate(c.funding, now, cfg.operations)
    if not allowed:
        return None, reason
    capacity, reason = depth_capacity(c.depth, bid, ask, now, cfg.operations)
    if capacity <= 0:
        return None, reason
    allowed, reason = correlation_gate(c.signal, broker.positions, histories, now, cfg.phase2)
    if not allowed:
        return None, reason
    slip = slippage_bps(cfg.slippage_bps, p.atr_value / p.entry, spread, cfg.operations)
    price = ask * (1 + slip / 10000) if p.side == "LONG" else bid * (1 - slip / 10000)
    sign = 1 if p.side == "LONG" else -1
    if sign * (price - p.stop) <= 0:
        return None, "original_stop_breached"
    if margin_budget is not None and not smart_add_eligible(broker, p, bid, ask)[0]:
        return None, "smart_add_not_losing_or_no_new_adverse_move"
    if abs(price - c.signal.entry) > abs(c.signal.entry - c.signal.stop) * 0.35:
        return None, "price_ran_from_fresh_signal"
    capital = broker.reserve.capital(broker.wallet, equity)
    signal = replace(c.signal, entry=price, stop=p.stop)
    sized = fixed_margin_size(
        signal,
        capital,
        replace(cfg, slippage_bps=slip),
        c.filters,
        sum(x.margin for x in broker.positions.values()),
        sum(stop_exposure(x, cfg) for x in broker.positions.values()),
        (
            broker.basket["initial_margins"][p.symbol] * cfg.basket.add_fraction
            if margin_budget is None
            else margin_budget
        ),
        margin_capital=broker.basket["initial_account_equity"],
    )
    if sized is None:
        return None, "add_min_notional_or_risk_capacity"
    qty, margin = sized
    if qty * price > capacity:
        return None, "depth_participation"
    fee = qty * price * cfg.fee_rate
    trial = copy.deepcopy(p)
    apply_pyramid(trial, price, qty, margin, fee, now)
    if stop_exposure(trial, cfg) > p.trade_risk_cap + 1e-9:
        return None, "original_trade_risk_cap"
    apply_pyramid(p, price, qty, margin, fee, now)
    p.average_count += 1
    broker.wallet -= fee
    broker.basket["total_margin"] += margin
    return dict(
        kind="pyramid",
        event_id=f"{p.symbol}:{p.opened_ts}:add:{p.pyramid_count}",
        basket_id=broker.basket["id"],
        add_type="basket_half_margin" if margin_budget is None else "basket_smart_loss_add",
        symbol=p.symbol,
        ts=now,
        source="paper",
        qty=qty,
        price=price,
        margin=margin,
        fee=fee,
        stop=p.stop,
        anchor_entry=p.anchor_entry,
        weighted_entry=p.entry,
        pyramid_count=p.pyramid_count,
        average_count=p.average_count,
    ), "ok"


def add_group(broker, candidates, quotes, now, histories):
    broker._finish_pending()
    validate_state(broker)
    if broker.cfg.basket.smart_adds:
        return smart_add_group(broker, candidates, quotes, now, histories)
    g = broker.basket
    if (
        not g
        or g["phase"] != "ACTIVE"
        or g["add_decided"]
        or now < g["opened_ms"] + broker.cfg.basket.add_after_seconds * 1000
        or (not broker.cfg.basket.hold_until_target and now >= g["deadline_ms"])
    ):
        return False, "add not due"
    net = projected_net(broker, quotes)
    if net is None:
        return False, "missing quote: add deferred"
    loss_fraction = broker.cfg.basket.loss_starting_equity_fraction
    if loss_fraction > 0 and net <= -broker.cfg.starting_equity * loss_fraction:
        return False, "basket loss threshold: add blocked"
    if broker._account_floor(quotes):
        return False, "account equity floor: add blocked"
    eligible = sorted(
        (
            c
            for c in candidates
            if fresh(c, now, broker.cfg.phase1.max_signal_age_ms)
            and c.signal.symbol in broker.positions
            and c.signal.side == broker.positions[c.signal.symbol].side
        ),
        key=strength,
    )
    # Persist one decision before staging; restart cannot retry or add a third leg.
    g.update(
        add_decided=True,
        add_decided_ms=now,
        add_net_before=net,
        add_result="decision_committed",
        add_due_ms=g["opened_ms"] + broker.cfg.basket.add_after_seconds * 1000,
        add_delay_ms=now - g["opened_ms"] - broker.cfg.basket.add_after_seconds * 1000,
    )
    broker.save()
    reason = "basket_not_losing" if net >= 0 else "fewer_than_two_aligned_fresh_signals"
    success = False
    if net < 0 and len({c.signal.symbol for c in eligible}) >= 2:
        selected = []
        for c in eligible:
            if c.signal.symbol not in [x.signal.symbol for x in selected]:
                selected.append(c)
            if len(selected) == 2:
                break
        staged, events = _shadow(broker)
        for c in selected:
            event, reason = _add_position(staged, c, quotes, now, histories)
            if event is None:
                break
            events.append(event)
        success = len(events) == 2
        if success:
            staged.basket["added_symbols"] = [c.signal.symbol for c in selected]
            staged.basket["add_result"] = "added"
            events.append(
                dict(
                    kind="basket",
                    event_id=g["id"] + ":add",
                    source="paper",
                    action="added",
                    ts=now,
                    symbols=staged.basket["added_symbols"],
                    total_margin=staged.basket["total_margin"],
                )
            )
            _commit(broker, staged, events)
            for event in events[:2]:
                log.info("PYRAMID: %s", event)
    if not success:
        broker.basket["add_result"] = reason
        broker.pending_journal = dict(
            kind="basket",
            event_id=g["id"] + ":add",
            action="add_skipped",
            ts=now,
            source="paper",
            reason=reason,
        )
        broker.save()
        broker._finish_pending()
        log.info("ENTRY_SKIP BASKET reason=basket_add_skipped detail=%s", reason)
    return success, "added strongest two once" if success else reason


def next_add_due(broker):
    g, policy = broker.basket, broker.cfg.basket
    if not g or g["phase"] != "ACTIVE":
        return None
    if not policy.smart_adds:
        return None if g["add_decided"] else g["opened_ms"] + policy.add_after_seconds * 1000
    rounds = g.get("smart_add_rounds", 0)
    if rounds >= policy.smart_add_max_rounds:
        return None
    return (
        g["opened_ms"] + policy.add_after_seconds * 1000
        if rounds == 0
        else g["smart_last_decision_ms"] + policy.smart_add_interval_seconds * 1000
    )


def smart_add_eligible(broker, p, bid, ask):
    sign = 1 if p.side == "LONG" else -1
    if not all(isfinite(x) for x in (bid, ask)) or not 0 < bid <= ask:
        return False, 0.0
    raw = bid if sign == 1 else ask
    # A price winner is untouched even if tiny gains do not yet cover costs.
    if sign * (raw - p.entry) >= 0 or p.atr_value <= 0:
        return False, 0.0
    spread = (ask - bid) / ((ask + bid) / 2) * 10000
    slip = slippage_bps(broker.cfg.slippage_bps, p.atr_value / p.entry, spread, broker.cfg.operations)
    price = (ask if sign == 1 else bid) * (1 + sign * slip / 10000)
    reference = broker.basket.get("smart_last_add_prices", {}).get(p.symbol, p.entry)
    distance = p.atr_value * broker.cfg.basket.smart_add_step_atr
    return sign * (price - reference) <= -distance and sign * (price - p.entry) < 0, price


def smart_add_group(broker, candidates, quotes, now, histories):
    g, policy = broker.basket, broker.cfg.basket
    due = next_add_due(broker)
    if due is None or now < due:
        return False, "smart add not due"
    reason = exit_reason(broker, quotes, now, broker._account_floor(quotes))
    if reason:
        return False, "basket closing: add blocked"
    net = projected_net(broker, quotes)
    if net is None:
        return False, "missing quote: add deferred"
    # Persist a round before attempting writes. A crash may skip, never repeat it.
    round_number = g.get("smart_add_rounds", 0) + 1
    g.update(
        smart_add_rounds=round_number,
        smart_last_decision_ms=now,
        add_decided=True,
        add_decided_ms=now,
        add_due_ms=due,
        add_delay_ms=now - due,
        add_net_before=net,
        add_result="decision_committed",
    )
    broker.save()
    staged, events = _shadow(broker)
    available = max(
        0.0,
        min(
            staged.reserve.capital(staged.wallet, staged.equity(quotes)),
            g["initial_account_equity"] * staged.cfg.max_margin_fraction,
        )
        - sum(p.margin for p in staged.positions.values()),
    )
    eligible, skipped, seen = [], {}, set()
    for c in sorted(candidates, key=strength):
        symbol = c.signal.symbol
        if symbol in seen:
            continue
        seen.add(symbol)
        if not fresh(c, now, broker.cfg.phase1.max_signal_age_ms) or symbol not in staged.positions:
            skipped[symbol] = "stale_or_not_held"
            continue
        p = staged.positions[symbol]
        if c.signal.side != p.side or symbol not in quotes:
            skipped[symbol] = "signal_opposed_or_missing_quote"
            continue
        allowed, price = smart_add_eligible(staged, p, *quotes[symbol])
        if not allowed:
            skipped[symbol] = "not_losing_or_no_new_adverse_move"
            continue
        # Reserve real exchange minimum lots; never round above allocated capital.
        f = c.filters
        qty = ceil(max(f.min_qty, f.min_notional / price) / f.step) * f.step
        minimum = qty * price / effective_leverage(staged.cfg)
        cap = g["initial_margins"][symbol]  # Fixed initial amount; no doubling.
        if minimum > cap or sum(x[1] for x in eligible) + minimum > available:
            skipped[symbol] = "smart_add_minimum_exceeds_available_margin"
            continue
        eligible.append((c, minimum, cap))
    # Equal share of remaining capital above each minimum; prioritize strength
    # only if all eligible minimum orders cannot fit. Risk guards may still refuse.
    remaining = available
    for index, (c, minimum, cap) in enumerate(eligible):
        reserve = sum(x[1] for x in eligible[index + 1 :])
        excess = max(0.0, remaining - minimum - reserve)
        budget = min(cap, minimum + excess / (len(eligible) - index))
        event, detail = _add_position(staged, c, quotes, now, histories, margin_budget=budget)
        if event is None:
            skipped[c.signal.symbol] = detail
            continue
        events.append(event)
        remaining -= event["margin"]
        staged.basket.setdefault("smart_last_add_prices", {})[c.signal.symbol] = event["price"]
    result = "added" if events else "no_eligible_loss_add_within_caps"
    staged.basket.update(add_result=result, added_symbols=[e["symbol"] for e in events])
    decision = dict(
        kind="basket",
        event_id=g["id"] + f":smart_add:{round_number}",
        source="paper",
        action="added" if events else "add_skipped",
        ts=now,
        round=round_number,
        symbols=[e["symbol"] for e in events],
        skipped=skipped,
        reason=result,
        total_margin=staged.basket["total_margin"],
    )
    events.append(decision)
    _commit(broker, staged, events)
    for event in events[:-1]:
        log.info("PYRAMID: %s", event)
    log.info("BASKET_SMART_ADD round=%d symbols=%s skipped=%s", round_number, decision["symbols"], skipped)
    return bool(events[:-1]), result
