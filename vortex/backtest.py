"""Conservative OHLC-only one-symbol backtest.

Signal after close of bar i; entry at OPEN of i+1, never same bar.
Stops win an intrabar tie. Both entry/exit include adverse slippage and fees.
No funding, bid/ask history, liquidation or order queue; results NOT forecasts.
"""
from __future__ import annotations
from .config import Settings
from .models import Candle, Signal
from .risk import Filters, RiskGate, size_trade
from .strategy import analyze


def run(symbol: str, small: list[Candle], higher: list[Candle],
        filt: Filters, cfg: Settings, macro: list[Candle] | None = None) -> dict:
    wallet = cfg.starting_equity
    peak, max_dd = wallet, 0.0
    wins = losses = 0
    trades: list[dict] = []
    gate = RiskGate(cfg, wallet)
    position: dict | None = None
    cooldown = 0
    for i in range(65, len(small)):
        candle = small[i]
        exited = False
        if position:
            p = position
            stop_hit = candle.low <= p["stop"] if p["side"] == "LONG" else candle.high >= p["stop"]
            tp_hit = candle.high >= p["target"] if p["side"] == "LONG" else candle.low <= p["target"]
            if stop_hit or tp_hit:
                raw = p["stop"] if stop_hit else p["target"]
                if stop_hit:
                    raw = min(raw, candle.open) if p["side"] == "LONG" else max(raw, candle.open)
                slip = cfg.slippage_bps / 10000
                px = raw * (1 - slip if p["side"] == "LONG" else 1 + slip)
                sign = 1 if p["side"] == "LONG" else -1
                fee = px * p["qty"] * cfg.fee_rate
                net = sign * (px - p["entry"]) * p["qty"] - p["entry_fee"] - fee
                wallet += sign * (px - p["entry"]) * p["qty"] - fee
                gate.closed(net)
                wins += int(net >= 0)
                losses += int(net < 0)
                trades.append({"open_ts": p["open_ts"], "close_ts": candle.ts, "symbol": symbol,
                               "side": p["side"], "entry": p["entry"], "exit": px,
                               "qty": p["qty"], "net_pnl": round(net, 6),
                               "reason": "stop" if stop_hit else "target",
                               "wallet": round(wallet, 6)})
                position = None
                exited = True
                cooldown = candle.ts + cfg.cooldown_minutes * 60000
        peak = max(peak, wallet)
        max_dd = max(max_dd, (peak - wallet) / peak if peak else 0)
        if gate.blocked or wallet <= gate.day_start_equity * (1 - cfg.max_daily_loss):
            break
        if position or exited or candle.ts <= cooldown or i == len(small) - 1:
            continue
        upper = [h for h in higher if h.close_ts <= candle.close_ts][-120:]
        macro_upper = ([m for m in macro if m.close_ts <= candle.close_ts][-120:]
                       if macro is not None else None)
        signal = (analyze(symbol, small[max(0, i - 219):i + 1], upper, cfg.min_score,
                          macro=macro_upper) if macro is not None else
                  analyze(symbol, small[max(0, i - 219):i + 1], upper, cfg.min_score))
        if signal is None:
            continue
        future = small[i + 1]
        slip = cfg.slippage_bps / 10000
        entry = future.open * (1 + slip if signal.side == "LONG" else 1 - slip)
        gap, target_gap = abs(signal.entry - signal.stop), abs(signal.target - signal.entry)
        if gap <= 0 or abs(entry - signal.entry) > gap * 0.35:
            continue
        sign = 1 if signal.side == "LONG" else -1
        adjusted = Signal(symbol, signal.side, signal.ts, entry,
                          entry - sign * gap, entry + sign * target_gap,
                          signal.score, signal.reason)
        sized = size_trade(adjusted, wallet, cfg, filt)
        if sized is None:
            continue
        qty, margin = sized
        fee = qty * entry * cfg.fee_rate
        wallet -= fee
        position = {"open_ts": future.ts, "side": signal.side, "entry": entry,
                    "stop": adjusted.stop, "target": adjusted.target,
                    "qty": qty, "entry_fee": fee, "margin": margin}
    unrealized = 0.0
    if position and small:
        close = small[-1].close
        sign = 1 if position["side"] == "LONG" else -1
        unrealized = sign * (close - position["entry"]) * position["qty"]
        unrealized -= close * position["qty"] * cfg.fee_rate
    return {"symbol": symbol, "start_equity": cfg.starting_equity,
            "wallet": round(wallet, 4), "equity_with_unrealized": round(wallet + unrealized, 4),
            "closed_trades": wins + losses, "wins": wins, "losses": losses,
            "win_rate_pct": round(100 * wins / (wins + losses), 2) if wins + losses else 0.0,
            "max_closed_equity_drawdown_pct": round(100 * max_dd, 2),
            "open_position": bool(position), "halted": gate.blocked,
            "warnings": ["OHLC conservative intrabar tie handling; funding and liquidation not simulated",
                         "Single historical sample; profits cannot be assumed to persist"],
            "trades": trades}
