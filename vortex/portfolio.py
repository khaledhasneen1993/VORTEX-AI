"""Synchronized multi-symbol OHLC portfolio backtest.

Signals calculated at the close of bar N, filled at open of bar N+1.
Tie between stop and target resolves at stop. No imagined fills on missing bars.
No funding/orderbook history/liquidations; these require separate historical data.
"""
from __future__ import annotations
from bisect import bisect_right
from datetime import datetime, timezone
from .models import Candle, Signal, Position
from .exits import levels_for_bar
from .config import Settings
from .risk import Filters, RiskGate, size_trade
from .strategy import analyze


def run_portfolio(
    candles: dict[str, list[Candle]],
    higher: dict[str, list[Candle]],
    filters: dict[str, Filters],
    config: Settings,
    macro: dict[str, list[Candle]] | None = None,
    minute: dict[str, list[Candle]] | None = None,
) -> dict:
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
    wallet = config.starting_equity
    active: dict[str, Position] = {}
    pending: dict[str, Signal] = {}
    trades: list[dict] = []
    risk = RiskGate(config, wallet)
    cool: dict[str, int] = {}
    highwater = wallet
    maxdd = 0.0
    fees_total = 0.0
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
            break
        # The decision to enter is from the *previous completed* candle.
        for sym, sig in sorted(list(pending.items()), key=lambda p: -p[1].score):
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
                                       initial_qty=qty, initial_risk=gap, peak=px, step=filters[sym].step)
            del pending[sym]
        # Same staged-exit engine as paper; OHLC stop wins intrabar ties.
        for sym, p in list(active.items()):
            b = bar[sym]
            for action in levels_for_bar(p, b.low, b.high, b.open):
                px = action.price * (1 - slip if p.side == "LONG" else 1 + slip)
                proportion = action.qty / p.qty
                entry_fee = p.entry_fee * proportion
                exit_fee = px * action.qty * config.fee_rate
                fees_total += exit_fee
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
                                   "entry_ts": p.opened_ts, "exit_ts": ts,
                                   "entry": round(p.entry, 8), "exit": round(px, 8),
                                   "net_pnl": round(final_net, 8),
                                   "reason": action.reason})
                    cool[sym] = ts + config.cooldown_minutes * 60_000
                    del active[sym]
                    break
        # Use marks for continuous drawdown & daily loss without crediting fantasy fills.
        equity = wallet + sum(
            (bar[s].close - p.entry) * p.qty * (1 if p.side == "LONG" else -1)
            - bar[s].close * p.qty * config.fee_rate for s, p in active.items())
        highwater = max(highwater, equity)
        maxdd = max(maxdd, (highwater - equity) / highwater if highwater else 0)
        if not risk.can_open(equity, len(active))[0] and risk.blocked:
            break
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
            if minute is not None:
                ix = bisect_right(minute_closes[sym], bar[sym].close_ts)
                minute_window = minute[sym][max(0, ix - 90):ix]
                sig = analyze(sym, history, upper, config.min_score, macro=macro_upper,
                              minute=minute_window)
            else:
                sig = (analyze(sym, history, upper, config.min_score, macro=macro_upper)
                       if macro is not None else analyze(sym, history, upper, config.min_score))
            if sig:
                pending[sym] = sig
    pnl = [t["net_pnl"] for t in trades]
    wins = sum(x > 0 for x in pnl)
    gross_win = sum(x for x in pnl if x > 0)
    gross_loss = -sum(x for x in pnl if x < 0)
    return {
        "start_equity": config.starting_equity, "cash_wallet": round(wallet, 6),
        "open_positions": sorted(active),
        "realized_net_pnl": round(sum(pnl), 6),
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
