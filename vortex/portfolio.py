"""Synchronized multi-symbol OHLC portfolio backtest.

Signals calculated at the close of bar N, filled at open of bar N+1.
Tie between stop and target resolves at stop. No imagined fills on missing bars.
Optional funding events use exchange rates and contemporaneous mark-price bars.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from datetime import datetime, timezone
from math import isclose, isfinite

from .config import Settings
from .exits import levels_for_bar
from .indicators import atr
from .models import Candle, FundingEvent, Position, Signal
from .operations import Protection, historical_context, require_history, slippage_bps
from .phase2 import (
    ProfitReserve,
    apply_pyramid,
    correlation_gate,
    initialize_position,
    pyramid_plan,
    stop_exposure,
)
from .reports import summary
from .risk import Filters, RiskGate, size_trade
from .strategy import analyze


def run_portfolio(
    candles: dict[str, list[Candle]],
    higher: dict[str, list[Candle]],
    filters: dict[str, Filters],
    config: Settings,
    macro: dict[str, list[Candle]] | None = None,
    minute: dict[str, list[Candle]] | None = None,
    *,
    execution_interval: str = "5m",
    diagnostics: bool = False,
    funding: dict[str, list[FundingEvent]] | None = None,
    execution_observations=None,
) -> dict:
    require_history(execution_observations, config.operations)
    protection = Protection(config.operations)
    execution_rejections = []
    if execution_interval not in {"5m", "1m"}:
        raise ValueError("Execution interval must be 5m or 1m")
    if execution_interval == "1m" and minute is None:
        raise ValueError("1m execution requires actual minute candles")
    if (
        not candles
        or set(candles) != set(higher)
        or set(candles) != set(filters)
        or (macro is not None and set(candles) != set(macro))
    ):
        raise ValueError("Each portfolio symbol requires bars, HTF and exchange filters")
    if minute is not None and set(candles) != set(minute):
        raise ValueError("1m history missing for portfolio symbols")
    if funding is not None and set(candles) != set(funding):
        raise ValueError("Funding history missing for portfolio symbols")
    minute_closes = (
        {s: [b.close_ts for b in bars] for s, bars in minute.items()} if minute is not None else {}
    )
    upper_times = {s: [x.close_ts for x in higher[s]] for s in candles}
    macro_times = {s: [x.close_ts for x in macro[s]] for s in candles} if macro is not None else {}
    symbols = sorted(candles)
    by_symbol: dict[str, dict[int, Candle]] = {}
    for sym in symbols:
        ordered = candles[sym]
        if len(ordered) < 75 or any((b.ts <= a.ts for a, b in zip(ordered, ordered[1:]))):
            raise ValueError(f"Insufficient or unordered market history: {sym}")
        by_symbol[sym] = {c.ts: c for c in ordered}
    stamps = sorted(set.intersection(*(set(x) for x in by_symbol.values())))
    if len(stamps) < 75:
        raise ValueError("Too few synchronous bars; refuse fabricated PnL")
    expected = 300000 if config.timeframe == "5m" else 900000
    if any((b - a != expected for a, b in zip(stamps, stamps[1:]))):
        raise ValueError("Historical gaps detected")
    execution = {}
    if execution_interval == "1m":
        for sym in symbols:
            if any((b.ts <= a.ts for a, b in zip(minute[sym], minute[sym][1:]))):
                raise ValueError(f"Unordered or duplicated 1m execution data: {sym}")
            observed = {c.ts: c for c in minute[sym]}
            required = range(stamps[0], stamps[-1] + expected, 60000)
            if any((t not in observed or observed[t].close_ts != t + 59999 for t in required)):
                raise ValueError(f"Missing or malformed 1m execution data: {sym}")
            for stamp in stamps:
                children = [observed[t] for t in range(stamp, stamp + expected, 60000)]
                parent = by_symbol[sym][stamp]
                actual = (
                    children[0].open,
                    max((c.high for c in children)),
                    min((c.low for c in children)),
                    children[-1].close,
                )
                if not all(
                    (
                        isclose(a, b, rel_tol=1e-09, abs_tol=1e-09)
                        for a, b in zip(actual, (parent.open, parent.high, parent.low, parent.close))
                    )
                ):
                    raise ValueError(f"1m OHLC does not reconcile with parent bar: {sym}")
            execution[sym] = observed
    funding_at: dict[str, dict[int, FundingEvent]] = {}
    if funding is not None:
        for sym in symbols:
            events = funding[sym]
            if any((b.ts <= a.ts for a, b in zip(events, events[1:]))):
                raise ValueError(f"Unordered or duplicated funding data: {sym}")
            if any(
                (
                    event.ts % 60000
                    or not isfinite(event.rate)
                    or (not -0.01 <= event.rate <= 0.01)
                    or (not isfinite(event.mark_price))
                    or (event.mark_price <= 0)
                    for event in events
                )
            ):
                raise ValueError(f"Malformed funding data: {sym}")
            funding_at[sym] = {event.ts: event for event in events}
    traces: dict[str, dict] = {}
    reserve = ProfitReserve(config)
    pyramid_events = []
    correlation_rejections = []
    wallet = config.starting_equity
    active: dict[str, Position] = {}
    pending: dict[str, Signal] = {}
    trades: list[dict] = []
    risk = RiskGate(config, wallet)
    cool: dict[str, int] = {}
    highwater = wallet
    maxdd = 0.0
    fees_total = 0.0
    funding_total = 0.0
    ending_equity = wallet
    curve: list[dict] = [{"ts": stamps[0], "equity": wallet}]
    for i, ts in enumerate(stamps):
        bar = {s: by_symbol[s][ts] for s in symbols}
        slip = config.slippage_bps / 10000
        opening_equity = wallet + sum(
            (
                (bar[s].open - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
                - bar[s].open * p.qty * config.fee_rate
                for s, p in active.items()
            )
        )
        risk.new_day(datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat(), opening_equity)
        protection.observe(ts, opening_equity)
        risk.can_open(opening_equity, len(active))
        if risk.blocked or not protection.allow(ts)[0]:
            pending.clear()
        past_histories = (
            {
                s: [
                    by_symbol[s][stamp]
                    for stamp in stamps[max(0, i - config.phase2.correlation_lookback - 1) : i]
                ]
                for s in symbols
            }
            if config.phase2.enabled
            else {}
        )
        if config.phase2.enabled and (not risk.blocked) and protection.allow(ts)[0]:
            for sym, p in active.items():
                sign = 1 if p.side == "LONG" else -1
                past_atr = atr(past_histories[sym][-50:]) if len(past_histories[sym]) >= 16 else p.atr_value
                add_slip = (
                    slippage_bps(config.slippage_bps, past_atr / p.entry, 0.0, config.operations) / 10000
                )
                price = bar[sym].open * (1 + sign * add_slip)
                candidate = Signal(sym, p.side, ts, price, p.stop, p.target, 10, "pyramid")
                corr_ok, _ = correlation_gate(candidate, active, past_histories, ts, config.phase2)
                plan = (
                    pyramid_plan(
                        p,
                        price,
                        ts,
                        replace(config, slippage_bps=add_slip * 10000),
                        filters[sym],
                        reserve.capital(wallet, opening_equity),
                        sum((x.margin for x in active.values())),
                        sum((stop_exposure(x, config) for x in active.values())),
                        past_histories[sym][-1].close,
                    )
                    if corr_ok and past_histories[sym]
                    else None
                )
                context_ok, _, capacity, _ = historical_context(
                    execution_observations, sym, ts, config.operations
                )
                if plan and context_ok and (plan[0] * price <= capacity):
                    q, m, f = plan
                    apply_pyramid(p, price, q, m, f, ts)
                    wallet -= f
                    fees_total += f
                    pyramid_events.append(dict(symbol=sym, ts=ts, qty=q, price=price, fee=f))
                    if diagnostics:
                        traces[sym]["total_fees"] += f
                        traces[sym].setdefault("pyramid_events", []).append(pyramid_events[-1])
        for sym, sig in sorted(list(pending.items()), key=lambda p: -p[1].score):
            if risk.blocked:
                break
            if sym in active:
                del pending[sym]
                continue
            context_ok, context_reason, capacity, spread = historical_context(
                execution_observations, sym, ts, config.operations
            )
            if not context_ok:
                execution_rejections.append(dict(symbol=sym, ts=ts, reason=context_reason))
                del pending[sym]
                continue
            slip = (
                slippage_bps(config.slippage_bps, sig.atr_value / sig.entry, spread, config.operations)
                / 10000
            )
            b = bar[sym]
            sign = 1 if sig.side == "LONG" else -1
            px = b.open * (1 + slip if sign == 1 else 1 - slip)
            gap = abs(sig.entry - sig.stop)
            if abs(px - sig.entry) > gap * 0.35 or gap <= 0:
                del pending[sym]
                continue
            new = replace(sig, entry=px, stop=px - sign * gap, target=px + sign * abs(sig.target - sig.entry))
            mark = wallet + sum(
                ((bar[s].open - p.entry) * p.qty * (1 if p.side == "LONG" else -1) for s, p in active.items())
            )
            allowed, _ = risk.can_open(mark, len(active))
            committed = sum((p.margin for p in active.values()))
            corr_ok, corr_reason = correlation_gate(new, active, past_histories, ts, config.phase2)
            if not corr_ok:
                correlation_rejections.append(dict(symbol=sym, ts=ts, reason=corr_reason))
            sized = (
                size_trade(
                    new,
                    reserve.capital(wallet, mark),
                    replace(config, slippage_bps=slip * 10000),
                    filters[sym],
                    committed,
                    committed_risk=sum((stop_exposure(p, config) for p in active.values())),
                )
                if allowed and corr_ok
                else None
            )
            if sized and sized[0] * px > capacity:
                execution_rejections.append(dict(symbol=sym, ts=ts, reason="depth participation limit"))
                sized = None
            if sized:
                qty, margin = sized
                fee = qty * px * config.fee_rate
                fees_total += fee
                wallet -= fee
                active[sym] = Position(
                    sym,
                    sig.side,
                    ts,
                    px,
                    new.stop,
                    new.target,
                    qty,
                    fee,
                    margin,
                    features=dict(sig.features),
                    initial_qty=qty,
                    initial_risk=gap,
                    peak=px,
                    step=filters[sym].step,
                    votes=list(sig.votes),
                    atr_value=sig.atr_value or gap / 1.5,
                    initial_stop=new.stop,
                    initial_target=new.target,
                )
                initialize_position(active[sym], sig, reserve.capital(wallet + fee, mark), config)
                if diagnostics:
                    traces[sym] = {
                        "initial_stop": new.stop,
                        "initial_target": new.target,
                        "atr_at_signal": sig.atr_value,
                        "score": sig.score,
                        "initial_qty": qty,
                        "initial_margin": margin,
                        "entry_fee": fee,
                        "total_fees": fee,
                        "partial_exits": [],
                        "funding_net": 0.0,
                        "funding_events": [],
                        "mfe_price_before_exit_bar": 0.0,
                        "mae_price_before_exit_bar": 0.0,
                        "mfe_first_ts": None,
                        "mae_first_ts": None,
                        "exit_bar_ambiguous": False,
                        "signal_features": dict(sig.features),
                    }
            del pending[sym]
        for sym, p in list(active.items()):
            b = bar[sym]
            last_bars = [by_symbol[sym][stamp] for stamp in stamps[max(0, i - 50) : i]]
            prev_atr = atr(last_bars) if len(last_bars) >= 16 else None
            execution_bars = (
                [execution[sym][t] for t in range(ts, ts + expected, 60000)]
                if execution_interval == "1m"
                else [b]
            )
            exit_slip = (
                slippage_bps(config.slippage_bps, (prev_atr or p.atr_value) / p.entry, 0.0, config.operations)
                / 10000
            )
            for execution_index, eb in enumerate(execution_bars):
                event = funding_at.get(sym, {}).get(eb.ts)
                deferred_funding = None
                if event is not None:
                    sign = 1 if p.side == "LONG" else -1
                    cash_flow = -sign * p.qty * event.mark_price * event.rate
                    if cash_flow <= 0:
                        wallet += cash_flow
                        funding_total += cash_flow
                        p.accumulated_net += cash_flow
                        p.accumulated_funding += cash_flow
                        if diagnostics:
                            traces[sym]["funding_net"] += cash_flow
                            traces[sym]["funding_events"].append(
                                {
                                    "ts": event.ts,
                                    "rate": event.rate,
                                    "mark_price": event.mark_price,
                                    "qty": p.qty,
                                    "net": cash_flow,
                                    "timing": "before_exit_adverse",
                                }
                            )
                    else:
                        deferred_funding = event
                existing_stop = p.stop
                sign = 1 if p.side == "LONG" else -1
                open_exit_reason = None
                actions = levels_for_bar(
                    p,
                    eb.low,
                    eb.high,
                    eb.open,
                    atr_value=prev_atr,
                    trailing_atr_mult=config.trailing_atr_mult,
                    policy=config.operations,
                    now_ms=eb.ts,
                )
                if diagnostics:
                    trace = traces[sym]
                    terminal = any((a.final for a in actions))
                    open_exit = open_exit_reason is not None and execution_index == 0
                    stop_touch = (
                        False
                        if open_exit
                        else eb.low <= existing_stop
                        if sign == 1
                        else eb.high >= existing_stop
                    )
                    one_r_touch = (
                        False
                        if open_exit
                        else (eb.high - p.entry if sign == 1 else p.entry - eb.low) >= p.initial_risk
                    )
                    trace["exit_bar_ambiguous"] = terminal and stop_touch and one_r_touch
                    if not terminal:
                        favorable = max(0.0, eb.high - p.entry if sign == 1 else p.entry - eb.low)
                        adverse = max(0.0, p.entry - eb.low if sign == 1 else eb.high - p.entry)
                        for name, value in (("mfe", favorable), ("mae", adverse)):
                            field = name + "_price_before_exit_bar"
                            if value > trace[field]:
                                trace[field] = value
                                trace[name + "_first_ts"] = eb.ts
                    else:
                        trace["terminal_bar"] = (
                            {"ts": eb.ts, "low": eb.open, "high": eb.open, "open_exit": True}
                            if open_exit
                            else {"ts": eb.ts, "low": eb.low, "high": eb.high}
                        )
                for action in actions:
                    px = action.price * (1 - exit_slip if p.side == "LONG" else 1 + exit_slip)
                    proportion = action.qty / p.qty
                    entry_fee = p.entry_fee * proportion
                    exit_fee = px * action.qty * config.fee_rate
                    fees_total += exit_fee
                    if diagnostics:
                        trace = traces[sym]
                        trace["total_fees"] += exit_fee
                        trace["partial_exits"].append(
                            {
                                "ts": eb.ts,
                                "qty": action.qty,
                                "price": px,
                                "reason": action.reason,
                                "final": action.final,
                                "entry_fee_allocated": entry_fee,
                                "exit_fee": exit_fee,
                                "net_pnl": (px - p.entry) * action.qty * (1 if p.side == "LONG" else -1)
                                - exit_fee
                                - entry_fee,
                            }
                        )
                    realized = (px - p.entry) * action.qty * (1 if p.side == "LONG" else -1)
                    net = realized - exit_fee - entry_fee
                    wallet += realized - exit_fee
                    reserve.record(net)
                    p.entry_fee -= entry_fee
                    p.qty = max(0.0, p.qty - action.qty)
                    p.margin *= max(0.0, 1.0 - proportion)
                    p.accumulated_net += net
                    if action.final:
                        final_net = p.accumulated_net
                        risk.closed(final_net)
                        protection.closed(final_net, eb.ts)
                        trades.append(
                            {
                                "symbol": sym,
                                "side": p.side,
                                "entry_ts": p.opened_ts,
                                "exit_ts": eb.ts,
                                "entry": round(p.entry, 8),
                                "exit": round(px, 8),
                                "net_pnl": round(final_net, 8),
                                "r_multiple": round(final_net / (p.initial_qty * p.initial_risk), 6)
                                if p.initial_qty * p.initial_risk > 0
                                else None,
                                "votes": list(p.votes),
                                "pyramid_count": p.pyramid_count,
                                "risk_fraction": p.risk_fraction,
                                "total_entry_qty": p.total_entry_qty or p.initial_qty,
                                "reason": action.reason,
                            }
                        )
                        if diagnostics:
                            trades[-1]["diagnostics"] = traces.pop(sym)
                        cool[sym] = ts + config.cooldown_minutes * 60000
                        del active[sym]
                        break
                if sym not in active:
                    break
                if deferred_funding is not None:
                    p = active[sym]
                    sign = 1 if p.side == "LONG" else -1
                    cash_flow = -sign * p.qty * deferred_funding.mark_price * deferred_funding.rate
                    wallet += cash_flow
                    reserve.record(cash_flow)
                    funding_total += cash_flow
                    p.accumulated_net += cash_flow
                    p.accumulated_funding += cash_flow
                    if diagnostics:
                        traces[sym]["funding_net"] += cash_flow
                        traces[sym]["funding_events"].append(
                            {
                                "ts": deferred_funding.ts,
                                "rate": deferred_funding.rate,
                                "mark_price": deferred_funding.mark_price,
                                "qty": p.qty,
                                "net": cash_flow,
                                "timing": "after_minute_favorable",
                            }
                        )
        equity = wallet + sum(
            (
                (bar[s].close - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
                - bar[s].close * p.qty * config.fee_rate
                for s, p in active.items()
            )
        )
        highwater = max(highwater, equity)
        ending_equity = equity
        curve.append({"ts": bar[symbols[0]].close_ts, "equity": round(equity, 6)})
        maxdd = max(maxdd, (highwater - equity) / highwater if highwater else 0)
        risk.can_open(equity, len(active))
        protection.observe(bar[symbols[0]].close_ts, equity)
        if risk.blocked or not protection.allow(bar[symbols[0]].close_ts)[0]:
            pending.clear()
            continue
        if i + 1 >= len(stamps):
            continue
        for sym in symbols:
            if sym in active or sym in pending or ts < cool.get(sym, 0):
                continue
            history = [by_symbol[sym][when] for when in stamps[max(0, i - 219) : i + 1]]
            hi_end = bisect_right(upper_times[sym], bar[sym].close_ts)
            upper = higher[sym][max(0, hi_end - 120) : hi_end]
            if macro is not None:
                m_end = bisect_right(macro_times[sym], bar[sym].close_ts)
                macro_upper = macro[sym][max(0, m_end - 250) : m_end]
            else:
                macro_upper = None
            vote_options = {}
            if config.phase1.enabled:
                vote_options["policy"] = config.phase1
            if minute is not None:
                ix = bisect_right(minute_closes[sym], bar[sym].close_ts)
                minute_window = minute[sym][max(0, ix - 90) : ix]
                sig = analyze(
                    sym,
                    history,
                    upper,
                    config.min_score,
                    macro=macro_upper,
                    minute=minute_window,
                    **vote_options,
                )
            else:
                sig = (
                    analyze(sym, history, upper, config.min_score, macro=macro_upper, **vote_options)
                    if macro is not None
                    else analyze(sym, history, upper, config.min_score, **vote_options)
                )
            if sig:
                pending[sym] = sig
    stats = summary(trades, curve)
    pnl = [t["net_pnl"] for t in trades]
    wins = sum((x > 0 for x in pnl))
    gross_win = sum((x for x in pnl if x > 0))
    gross_loss = -sum((x for x in pnl if x < 0))
    return {
        "operations_protection": protection.state(),
        "execution_rejections": execution_rejections,
        "reserved_profit": reserve.reserved,
        "pyramid_events": pyramid_events,
        "correlation_rejections": correlation_rejections,
        "phase2_enabled": config.phase2.enabled,
        "metrics": stats,
        "equity_curve": stats["equity_curve"],
        "average_r": stats["average_r"],
        "max_drawdown_pct": max(round(maxdd * 100, 3), stats["max_drawdown_pct"]),
        "start_equity": config.starting_equity,
        "cash_wallet": round(wallet, 6),
        "equity_with_unrealized": round(ending_equity, 6),
        "open_positions_unrealized_net": round(ending_equity - wallet, 6),
        "open_positions": sorted(active),
        "realized_net_pnl": round(sum(pnl), 6),
        "execution_interval": execution_interval,
        "diagnostics_enabled": diagnostics,
        "closed_trades": len(pnl),
        "win_rate": wins / len(pnl) if pnl else None,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "max_mark_to_market_drawdown_pct": round(maxdd * 100, 3),
        "total_fees": round(fees_total, 6),
        "total_funding_net": round(funding_total, 6),
        "halted": risk.blocked,
        "warnings": [
            "OHLC approximations; liquidation, historic spread and queue not replayed"
            if funding is not None
            else "OHLC approximations; funding, liquidation, historic spread and queue not replayed",
            "Historical results are NOT a forward-profit forecast",
        ],
        "trades": trades,
    }
