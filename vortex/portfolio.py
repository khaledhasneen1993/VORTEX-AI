"""Synchronized multi-symbol OHLC portfolio backtest.

Signals calculated at the close of bar N, filled at open of bar N+1.
Tie between stop and target resolves at stop. No imagined fills on missing bars.
No funding/orderbook history/liquidations; these require separate historical data.
"""
from __future__ import annotations
from bisect import bisect_right
from math import isclose
from datetime import datetime, timezone
from .models import Candle, Signal, Position
from .exits import levels_for_bar
from .indicators import atr
from .reports import summary
from .config import Settings
from .risk import Filters, RiskGate, size_trade
from .strategy import analyze
from .research_policy import fixed_r_levels


def run_portfolio(
    candles: dict[str, list[Candle]],
    higher: dict[str, list[Candle]],
    filters: dict[str, Filters],
    config: Settings,
    macro: dict[str, list[Candle]] | None = None,
    minute: dict[str, list[Candle]] | None = None,
    *, execution_interval: str = "5m", diagnostics: bool = False,
    exit_policy: str = "baseline",
) -> dict:
    if execution_interval not in {"5m", "1m"}:
        raise ValueError("Execution interval must be 5m or 1m")
    if execution_interval == "1m" and minute is None:
        raise ValueError("1m execution requires actual minute candles")
    if exit_policy not in {"baseline", "fixed-1r", "fixed-3r"}:
        raise ValueError("Unknown exit policy")
    if not candles or set(candles) != set(higher) or set(candles) != set(filters) or (macro is not None and set(candles) != set(macro)):
        raise ValueError("Each portfolio symbol requires bars, HTF and exchange filters")
    if minute is not None and set(candles) != set(minute):
        raise ValueError("1m history missing for portfolio symbols")
    minute_closes = {s: [b.close_ts for b in bars] for s, bars in minute.items()} if minute is not None else {}
    upper_times = {s: [x.close_ts for x in higher[s]] for s in candles}
    macro_times = ({s: [x.close_ts for x in macro[s]] for s in candles}
                   if macro is not None else {})
    symbols = sorted(candles)
    by_symbol: dict[str, dict[int, Candle]] = {}
    for sym in symbols:
        ordered = candles[sym]
        if len(ordered) < 75 or any(b.ts <= a.ts for a, b in zip(ordered, ordered[1:])):
            raise ValueError(f"Insufficient or unordered market history: {sym}")
        by_symbol[sym] = {c.ts: c for c in ordered}
    # Only timestamps common to ALL symbols; reject missing synchronized bars.
    stamps = sorted(set.intersection(*(set(x) for x in by_symbol.values())))
    if len(stamps) < 75:
        raise ValueError("Too few synchronous bars; refuse fabricated PnL")
    expected = 300_000 if config.timeframe == "5m" else 900_000
    if any(b - a != expected for a, b in zip(stamps, stamps[1:])):
        raise ValueError("Historical gaps detected")
    execution = {}
    if execution_interval == "1m":
        for sym in symbols:
            if any(b.ts <= a.ts for a,b in zip(minute[sym],minute[sym][1:])):
                raise ValueError(f"Unordered or duplicated 1m execution data: {sym}")
            observed = {c.ts: c for c in minute[sym]}
            required = range(stamps[0], stamps[-1] + expected, 60_000)
            if any(t not in observed or observed[t].close_ts != t + 59_999 for t in required):
                raise ValueError(f"Missing or malformed 1m execution data: {sym}")
            for stamp in stamps:
                children = [observed[t] for t in range(stamp,stamp+expected,60_000)]
                parent = by_symbol[sym][stamp]
                actual = (children[0].open,max(c.high for c in children),
                          min(c.low for c in children),children[-1].close)
                if not all(isclose(a,b,rel_tol=1e-9,abs_tol=1e-9) for a,b in
                           zip(actual,(parent.open,parent.high,parent.low,parent.close))):
                    raise ValueError(f"1m OHLC does not reconcile with parent bar: {sym}")
            execution[sym] = observed
    traces: dict[str, dict] = {}
    wallet = config.starting_equity
    active: dict[str, Position] = {}
    pending: dict[str, Signal] = {}
    trades: list[dict] = []
    risk = RiskGate(config, wallet)
    cool: dict[str, int] = {}
    highwater = wallet
    maxdd = 0.0
    fees_total = 0.0
    ending_equity = wallet
    curve: list[dict] = [{"ts": stamps[0], "equity": wallet}]
    for i, ts in enumerate(stamps):
        bar = {s: by_symbol[s][ts] for s in symbols}
        slip = config.slippage_bps / 10_000
        # UTC risk reset occurs BEFORE next-bar entries. Previous-day losses
        # cannot be mistaken for current-day drawdowns.
        opening_equity = wallet + sum(
            (bar[s].open - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
            - bar[s].open * p.qty * config.fee_rate for s, p in active.items())
        risk.new_day(datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat(),
                     opening_equity)
        risk.can_open(opening_equity, len(active))
        if risk.blocked:
            pending.clear()  # keep managing open stops, but prohibit new entries
        # The decision to enter is from the *previous completed* candle.
        for sym, sig in sorted(list(pending.items()), key=lambda p: -p[1].score):
            if risk.blocked:
                break
            if sym in active:
                del pending[sym]
                continue
            b = bar[sym]
            sign = 1 if sig.side == "LONG" else -1
            px = b.open * (1 + slip if sign == 1 else 1 - slip)
            gap = abs(sig.entry - sig.stop)
            if abs(px - sig.entry) > gap * .35 or gap <= 0:
                del pending[sym]
                continue
            new = Signal(sym, sig.side, sig.ts, px,
                         px - sign * gap, px + sign * abs(sig.target - sig.entry),
                         sig.score, sig.reason)
            mark = wallet + sum(
                (bar[s].open - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
                for s, p in active.items())
            allowed, _ = risk.can_open(mark, len(active))
            committed = sum(p.margin for p in active.values())
            sized = size_trade(new, mark, config, filters[sym], committed) if allowed else None
            if sized:
                qty, margin = sized
                fee = qty * px * config.fee_rate
                fees_total += fee
                wallet -= fee
                active[sym] = Position(sym, sig.side, ts, px, new.stop, new.target, qty, fee, margin,
                                       initial_qty=qty, initial_risk=gap, peak=px,
                                       step=filters[sym].step, votes=list(sig.votes),
                                       atr_value=sig.atr_value or gap / 1.5,
                                       initial_stop=new.stop, initial_target=new.target)
                if diagnostics:
                    traces[sym] = {
                        "initial_stop": new.stop, "initial_target": new.target,
                        "atr_at_signal": sig.atr_value, "score": sig.score,
                        "initial_qty": qty, "initial_margin": margin,
                        "entry_fee": fee, "total_fees": fee, "partial_exits": [],
                        "mfe_price_before_exit_bar": 0.0, "mae_price_before_exit_bar": 0.0,
                        "mfe_first_ts": None, "mae_first_ts": None,
                        "exit_bar_ambiguous": False, "signal_features": dict(sig.features),
                    }
            del pending[sym]
        # Same staged-exit engine as paper; OHLC stop wins intrabar ties.
        for sym, p in list(active.items()):
            b = bar[sym]
            last_bars = [by_symbol[sym][stamp] for stamp in stamps[max(0, i-50):i]]
            prev_atr = atr(last_bars) if len(last_bars) >= 16 else None
            execution_bars = ([execution[sym][t] for t in range(ts, ts + expected, 60_000)]
                              if execution_interval == "1m" else [b])
            for eb in execution_bars:
                existing_stop = p.stop
                sign = 1 if p.side == "LONG" else -1
                fixed_target_r = {"fixed-1r": 1.0, "fixed-3r": 3.0}.get(exit_policy)
                actions = (fixed_r_levels(p, eb.low, eb.high, eb.open, fixed_target_r)
                           if fixed_target_r is not None else
                           levels_for_bar(p, eb.low, eb.high, eb.open,
                                          atr_value=prev_atr,
                                          trailing_atr_mult=config.trailing_atr_mult))
                if diagnostics:
                    trace = traces[sym]
                    terminal = any(a.final for a in actions)
                    stop_touch = eb.low <= existing_stop if sign == 1 else eb.high >= existing_stop
                    one_r_touch = (eb.high - p.entry if sign == 1 else p.entry - eb.low) >= p.initial_risk
                    trace["exit_bar_ambiguous"] = terminal and stop_touch and one_r_touch
                    # Terminal-bar extremes may happen AFTER exit; never credit them as actual MFE/MAE.
                    # These fields are lower bounds from completed pre-terminal bars, not tick paths.
                    if not terminal:
                        favorable = max(0., eb.high - p.entry if sign == 1 else p.entry - eb.low)
                        adverse = max(0., p.entry - eb.low if sign == 1 else eb.high - p.entry)
                        for name, value in (("mfe", favorable), ("mae", adverse)):
                            field = name + "_price_before_exit_bar"
                            if value > trace[field]:
                                trace[field] = value
                                trace[name + "_first_ts"] = eb.ts
                    else:
                        trace["terminal_bar"] = {"ts": eb.ts, "low": eb.low, "high": eb.high}
                for action in actions:
                    px = action.price * (1 - slip if p.side == "LONG" else 1 + slip)
                    proportion = action.qty / p.qty
                    entry_fee = p.entry_fee * proportion
                    exit_fee = px * action.qty * config.fee_rate
                    fees_total += exit_fee
                    if diagnostics:
                        trace = traces[sym]
                        trace["total_fees"] += exit_fee
                        trace["partial_exits"].append({"ts": eb.ts, "qty": action.qty,
                            "price": px, "reason": action.reason, "final": action.final,
                            "entry_fee_allocated": entry_fee, "exit_fee": exit_fee, "net_pnl": (px - p.entry) * action.qty * (1 if p.side == "LONG" else -1) - exit_fee - entry_fee})
                    realized = (px - p.entry) * action.qty * (1 if p.side == "LONG" else -1)
                    net = realized - exit_fee - entry_fee
                    wallet += realized - exit_fee
                    p.entry_fee -= entry_fee
                    p.qty = max(0., p.qty - action.qty)
                    p.margin *= max(0., 1. - proportion)
                    p.accumulated_net += net
                    if action.final:
                        final_net = p.accumulated_net
                        risk.closed(final_net)
                        trades.append({"symbol": sym, "side": p.side,
                                       "entry_ts": p.opened_ts, "exit_ts": eb.ts,
                                       "entry": round(p.entry, 8), "exit": round(px, 8),
                                       "net_pnl": round(final_net, 8),
                                       "r_multiple": round(final_net / (p.initial_qty * p.initial_risk), 6)
                                                     if p.initial_qty * p.initial_risk > 0 else None,
                                       "votes": list(p.votes),
                                       "reason": action.reason})
                        if diagnostics:
                            trades[-1]["diagnostics"] = traces.pop(sym)
                        cool[sym] = ts + config.cooldown_minutes * 60_000
                        del active[sym]
                        break
                if sym not in active:
                    break
        # Use marks for continuous drawdown & daily loss without crediting fantasy fills.
        equity = wallet + sum(
            (bar[s].close - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
            - bar[s].close * p.qty * config.fee_rate for s, p in active.items())
        highwater = max(highwater, equity)
        ending_equity = equity
        curve.append({"ts": bar[symbols[0]].close_ts, "equity": round(equity, 6)})
        maxdd = max(maxdd, (highwater - equity) / highwater if highwater else 0)
        risk.can_open(equity, len(active))
        if risk.blocked:
            pending.clear()
            continue  # continue monitoring stops, never open new positions
        # After bar close, queue signals for next bar only; forbid final-bar entries.
        if i + 1 >= len(stamps):
            continue
        for sym in symbols:
            if sym in active or sym in pending or ts < cool.get(sym, 0):
                continue
            history = [by_symbol[sym][when] for when in stamps[max(0, i-219):i+1]]
            hi_end = bisect_right(upper_times[sym], bar[sym].close_ts)
            upper = higher[sym][max(0, hi_end-120):hi_end]
            if macro is not None:
                m_end = bisect_right(macro_times[sym], bar[sym].close_ts)
                macro_upper = macro[sym][max(0, m_end-250):m_end]
            else:
                macro_upper = None
            vote_options = ({"strict_votes": config.strict_votes,
                             "min_strong_score": config.min_strong_score}
                            if not config.strict_votes else {})
            if minute is not None:
                ix = bisect_right(minute_closes[sym], bar[sym].close_ts)
                minute_window = minute[sym][max(0, ix - 90):ix]
                sig = analyze(sym, history, upper, config.min_score, macro=macro_upper,
                              minute=minute_window, **vote_options)
            else:
                sig = (analyze(sym, history, upper, config.min_score, macro=macro_upper, **vote_options)
                       if macro is not None else analyze(sym, history, upper, config.min_score, **vote_options))
            if sig:
                pending[sym] = sig
    stats = summary(trades, curve)
    pnl = [t["net_pnl"] for t in trades]
    wins = sum(x > 0 for x in pnl)
    gross_win = sum(x for x in pnl if x > 0)
    gross_loss = -sum(x for x in pnl if x < 0)
    return {
        "metrics": stats, "equity_curve": stats["equity_curve"],
        "average_r": stats["average_r"],
        "max_drawdown_pct": max(round(maxdd * 100, 3), stats["max_drawdown_pct"]),
        "start_equity": config.starting_equity, "cash_wallet": round(wallet, 6),
        "equity_with_unrealized": round(ending_equity, 6),
        "open_positions_unrealized_net": round(ending_equity-wallet, 6),
        "open_positions": sorted(active),
        "realized_net_pnl": round(sum(pnl), 6),
        "execution_interval": execution_interval, "exit_policy": exit_policy,
        "diagnostics_enabled": diagnostics,
        "closed_trades": len(pnl),
        "win_rate": (wins / len(pnl) if pnl else None),
        "profit_factor": (gross_win / gross_loss if gross_loss else None),
        "max_mark_to_market_drawdown_pct": round(maxdd * 100, 3),
        "total_fees": round(fees_total, 6),
        "halted": risk.blocked,
        "warnings": ["OHLC approximations; funding, liquidation, historic spread and queue not replayed",
                     "Historical results are NOT a forward-profit forecast"],
        "trades": trades,
    }
