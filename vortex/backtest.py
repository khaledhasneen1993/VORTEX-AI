"""Conservative OHLC-only one-symbol backtest.

Signal after close of bar i; entry at OPEN of i+1, never same bar.
Stops win an intrabar tie. Both entry/exit include adverse slippage and fees.
No funding, bid/ask history, liquidation or order queue; results NOT forecasts.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from datetime import datetime, timezone

from .config import Settings
from .exits import levels_for_bar
from .indicators import atr
from .r_units import net_r, signal_r
from .models import Candle, Position
from .operations import Protection, historical_context, require_history, slippage_bps
from .phase2 import ProfitReserve, apply_pyramid, initialize_position, pyramid_plan, stop_exposure
from .reports import summary
from .risk import Filters, RiskGate, size_trade
from .strategy import analyze


def run(
    symbol: str,
    small: list[Candle],
    higher: list[Candle],
    filt: Filters,
    cfg: Settings,
    macro: list[Candle] | None = None,
    minute: list[Candle] | None = None,
    *,
    execution_observations=None,
) -> dict:
    require_history(execution_observations, cfg.operations)
    protection = Protection(cfg.operations)
    rejection_events = []
    reserve = ProfitReserve(cfg)
    pyramid_events = []
    wallet = cfg.starting_equity
    peak, max_dd = (wallet, 0.0)
    wins = losses = 0
    trades: list[dict] = []
    curve: list[dict] = [{"ts": small[0].ts if small else 0, "equity": wallet}]
    gate = RiskGate(cfg, wallet)
    position: Position | None = None
    cooldown = 0
    upper_closes = [x.close_ts for x in higher]
    macro_closes = [x.close_ts for x in macro] if macro is not None else []
    minute_closes = [x.close_ts for x in minute] if minute is not None else []
    for i in range(65, len(small)):
        candle = small[i]
        beginning_equity = wallet
        if position:
            sign = 1 if position.side == "LONG" else -1
            beginning_equity += sign * (candle.open - position.entry) * position.qty
            beginning_equity -= candle.open * position.qty * cfg.fee_rate
        gate.new_day(
            datetime.fromtimestamp(candle.ts / 1000, timezone.utc).date().isoformat(), beginning_equity
        )
        protection.observe(candle.ts, beginning_equity)
        exited = False
        if position:
            p = position
            recent = small[max(0, i - 50) : i]
            observed_atr = atr(recent) if len(recent) >= 16 else None
            if cfg.phase2.enabled and (not gate.blocked) and protection.allow(candle.ts)[0]:
                gate.can_open(beginning_equity, 0)
                if not gate.blocked:
                    add_slip = (
                        slippage_bps(
                            cfg.slippage_bps, (observed_atr or p.atr_value) / p.entry, 0.0, cfg.operations
                        )
                        / 10000
                    )
                    add_price = candle.open * (1 + add_slip if p.side == "LONG" else 1 - add_slip)
                    context_ok, _, capacity, _ = historical_context(
                        execution_observations, symbol, candle.ts, cfg.operations
                    )
                    plan = pyramid_plan(
                        p,
                        add_price,
                        candle.ts,
                        replace(cfg, slippage_bps=add_slip * 10000),
                        filt,
                        reserve.capital(wallet, beginning_equity),
                        p.margin,
                        stop_exposure(p, cfg),
                        small[i - 1].close,
                    )
                    if plan and context_ok and (plan[0] * add_price <= capacity):
                        q, m, f = plan
                        apply_pyramid(p, add_price, q, m, f, candle.ts)
                        wallet -= f
                        pyramid_events.append(dict(ts=candle.ts, qty=q, price=add_price, fee=f))
            actions = levels_for_bar(
                p,
                candle.low,
                candle.high,
                candle.open,
                atr_value=observed_atr,
                trailing_atr_mult=cfg.trailing_atr_mult,
                policy=cfg.operations,
                now_ms=candle.ts,
            )
            for action in actions:
                slip = (
                    slippage_bps(
                        cfg.slippage_bps, (observed_atr or p.atr_value) / p.entry, 0.0, cfg.operations
                    )
                    / 10000
                )
                px = action.price * (1 - slip if p.side == "LONG" else 1 + slip)
                sign = 1 if p.side == "LONG" else -1
                entry_fee_portion = p.entry_fee * (action.qty / p.qty)
                exit_fee = px * action.qty * cfg.fee_rate
                net = sign * (px - p.entry) * action.qty - entry_fee_portion - exit_fee
                wallet += sign * (px - p.entry) * action.qty - exit_fee
                reserve.record(net)
                p.margin *= max(0.0, 1 - action.qty / p.qty)
                p.entry_fee -= entry_fee_portion
                p.qty = max(0.0, p.qty - action.qty)
                p.accumulated_net += net
                if action.final:
                    final_net = p.accumulated_net
                    gate.closed(final_net)
                    protection.closed(final_net, candle.ts)
                    wins += int(final_net >= 0)
                    losses += int(final_net < 0)
                    trades.append(
                        {
                            "open_ts": p.opened_ts,
                            "close_ts": candle.ts,
                            "symbol": symbol,
                            "side": p.side,
                            "entry": p.entry,
                            "exit": px,
                            "qty": p.total_entry_qty or p.initial_qty,
                            "pyramid_count": p.pyramid_count,
                            "risk_fraction": p.risk_fraction,
                            "net_pnl": round(final_net, 6),
                            "r_multiple": net_r(p, final_net),
                            "votes": list(p.votes),
                            "reason": action.reason,
                            "wallet": round(wallet, 6),
                        }
                    )
                    position = None
                    exited = True
                    cooldown = candle.ts + cfg.cooldown_minutes * 60000
                    break
        equity = wallet
        if position:
            sign = 1 if position.side == "LONG" else -1
            equity += sign * (candle.close - position.entry) * position.qty
            equity -= candle.close * position.qty * cfg.fee_rate
        curve.append({"ts": candle.close_ts, "equity": round(equity, 6)})
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
        allowed, _ = gate.can_open(equity, 1 if position else 0)
        protection.observe(candle.close_ts, equity)
        if gate.blocked or not protection.allow(candle.close_ts)[0]:
            if position is None:
                break
            continue
        if position or exited or candle.ts <= cooldown or (i == len(small) - 1):
            continue
        h_end = bisect_right(upper_closes, candle.close_ts)
        upper = higher[max(0, h_end - 120) : h_end]
        if macro is not None:
            m_end = bisect_right(macro_closes, candle.close_ts)
            macro_upper = macro[max(0, m_end - 250) : m_end]
        else:
            macro_upper = None
        minute_window = (
            minute[
                max(0, bisect_right(minute_closes, candle.close_ts) - 90) : bisect_right(
                    minute_closes, candle.close_ts
                )
            ]
            if minute is not None
            else None
        )
        vote_options = {}
        if cfg.phase1.enabled:
            vote_options["policy"] = cfg.phase1
        if minute is not None:
            signal = analyze(
                symbol,
                small[max(0, i - 219) : i + 1],
                upper,
                cfg.min_score,
                macro=macro_upper,
                minute=minute_window,
                **vote_options,
            )
        else:
            signal = (
                analyze(
                    symbol,
                    small[max(0, i - 219) : i + 1],
                    upper,
                    cfg.min_score,
                    macro=macro_upper,
                    **vote_options,
                )
                if macro is not None
                else analyze(symbol, small[max(0, i - 219) : i + 1], upper, cfg.min_score, **vote_options)
            )
        if signal is None:
            continue
        future = small[i + 1]
        context_ok, context_reason, capacity, spread = historical_context(
            execution_observations, symbol, future.ts, cfg.operations
        )
        if not context_ok:
            rejection_events.append(dict(symbol=symbol, ts=future.ts, reason=context_reason))
            continue
        modeled_slip = slippage_bps(cfg.slippage_bps, signal.atr_value / signal.entry, spread, cfg.operations)
        slip = modeled_slip / 10000
        entry = future.open * (1 + slip if signal.side == "LONG" else 1 - slip)
        gap, target_gap = (signal_r(signal), abs(signal.target - signal.entry))
        if gap <= 0 or abs(entry - signal.entry) > gap * 0.35:
            continue
        sign = 1 if signal.side == "LONG" else -1
        adjusted = replace(signal, entry=entry, stop=entry - sign * gap, target=entry + sign * target_gap)
        if not allowed:
            continue
        sized = size_trade(
            adjusted, reserve.capital(wallet, equity), replace(cfg, slippage_bps=modeled_slip), filt
        )
        if sized is None:
            continue
        qty, margin = sized
        if qty * entry > capacity:
            rejection_events.append(dict(symbol=symbol, ts=future.ts, reason="depth participation limit"))
            continue
        fee = qty * entry * cfg.fee_rate
        wallet -= fee
        position = Position(
            symbol,
            signal.side,
            future.ts,
            entry,
            adjusted.stop,
            adjusted.target,
            qty,
            fee,
            margin,
            features=dict(signal.features),
            initial_qty=qty,
            initial_risk=gap,
            peak=entry,
            step=filt.step,
            votes=list(signal.votes),
            atr_value=signal.atr_value or gap / 1.5,
            initial_stop=adjusted.stop,
            initial_target=adjusted.target,
        )
        initialize_position(position, signal, reserve.capital(wallet + fee, equity), cfg)
    unrealized = 0.0
    if position and small:
        close = small[-1].close
        sign = 1 if position.side == "LONG" else -1
        unrealized = sign * (close - position.entry) * position.qty
        unrealized -= close * position.qty * cfg.fee_rate
    stats = summary(trades, curve)
    return {
        "operations_protection": protection.state(),
        "execution_rejections": rejection_events,
        "reserved_profit": reserve.reserved,
        "pyramid_events": pyramid_events,
        "phase2_enabled": cfg.phase2.enabled,
        "metrics": stats,
        "equity_curve": stats["equity_curve"],
        "profit_factor": stats["profit_factor"],
        "average_r": stats["average_r"],
        "max_drawdown_pct": round(max_dd * 100, 3),
        "symbol": symbol,
        "start_equity": cfg.starting_equity,
        "wallet": round(wallet, 4),
        "equity_with_unrealized": round(wallet + unrealized, 4),
        "closed_trades": wins + losses,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100 * wins / (wins + losses), 2) if wins + losses else 0.0,
        "max_mark_to_market_drawdown_pct": round(100 * max_dd, 2),
        "open_position": bool(position),
        "halted": gate.blocked,
        "warnings": [
            "OHLC conservative intrabar tie handling; funding and liquidation not simulated",
            "Single historical sample; profits cannot be assumed to persist",
        ],
        "trades": trades,
    }
