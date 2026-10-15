"""913: independent, fee-aware PAPER positions; no exchange writes or adds."""

import logging
from dataclasses import replace
from math import isfinite, isclose

from .basket import fresh
from .basket_live import BasketLoop
from .exits import ExitStep
from .operations import slippage_bps
from .risk import floor_step, size_trade

log = logging.getLogger("vortex")


def entry_size(signal, capital, equity, cfg, filters, margin_used, risk_used, raw_exit):
    budget = equity * 0.10
    scoped = replace(cfg, phase2=replace(cfg.phase2, entry_margin_fraction=0.25))
    sized = size_trade(signal, capital, scoped, filters, margin_used, budget,
                       committed_risk=risk_used)
    if sized is None:
        return None
    sign = 1 if signal.side == "LONG" else -1
    # Also reserve immediate spread/entry costs: the last small allocation must
    # not put used margin above 60% of capital just after its own fill.
    loss = signal.entry * cfg.fee_rate + max(
        0.0, sign * (signal.entry - raw_exit) + raw_exit * cfg.fee_rate,
    )
    cap = max(0.0, capital * cfg.max_margin_fraction - margin_used)
    qty = floor_step(min(sized[0], cap / (signal.entry / 10 + cfg.max_margin_fraction * loss)), filters.step)
    if qty < filters.min_qty or qty * signal.entry < filters.min_notional:
        return None
    return qty, qty * signal.entry / 10


def raw_exit_price(entry, sign, fee, slip, margin_return):
    """Executable bid/ask yielding net return on margin at the fixed 10x.

    Entry is already the slipped fill. Include its fee and modeled exit costs.
    913 never changes quantity or margin through additions.
    """
    fill = (sign * entry + entry * fee + margin_return * entry / 10) / (sign - fee)
    return fill / (1 - sign * slip)


def exit_step(position, bid, ask, cfg, floor_halted=False):
    if not all(isfinite(x) for x in (bid, ask)) or not 0 < bid <= ask:
        raise ValueError("Invalid 913 quote")
    p = position
    sign = 1 if p.side == "LONG" else -1
    raw = bid if sign == 1 else ask
    slip = slippage_bps(
        cfg.slippage_bps, p.atr_value / p.entry,
        (ask - bid) / ((ask + bid) / 2) * 10000, cfg.operations,
    ) / 10000
    fill = raw * (1 - sign * slip)
    net = sign * (fill - p.entry) * p.qty - p.entry_fee - fill * p.qty * cfg.fee_rate
    target, stop = p.margin * 0.01, -p.margin * 0.05
    reason = None
    if floor_halted:
        reason = "account_equity_floor"
    elif net <= stop or isclose(net, stop, abs_tol=1e-10):
        reason = "913_net_margin_stop"
    elif net >= target or isclose(net, target, abs_tol=1e-10):
        reason = "913_net_margin_target"
    return ExitStep(p.qty, raw, reason, True) if reason else None


class IndividualLoop(BasketLoop):
    """Reuse bounded scans, guards and exit polling; never stage a basket."""

    def cycle(self):
        self.degraded = False
        before = len(self.broker.positions)
        now, quotes = self._mark()
        if len(self.broker.positions) < before:
            self.reselect_due = True
        bucket = now // 300000
        if (len(self.broker.positions) < self.cfg.max_positions and (
            self.reselect_due
            or (self.last_scan != bucket and 5000 <= now % 300000 <= 65000)
        )):
            self.reselect_due = False
            self.last_scan = bucket
            symbols = self.symbols
            if self.use_radar:
                from .radar import discover

                self.symbols = symbols = [c.symbol for c in discover(
                    self.market, limit=self.cfg.radar_limit, fast_ranking=self.cfg.radar_fast_ranking,
                )]
                log.info("RADAR ranked liquid movers: %s", symbols)
            keep = set(symbols) | set(self.broker.positions)
            self.histories = {s: bars for s, bars in self.histories.items() if s in keep}
            self.health.row["symbols"] = {
                s: row for s, row in self.health.row["symbols"].items() if s in keep
            }
            ready = self._scan([s for s in symbols if s not in self.broker.positions], now)
            guarded = self._guards(ready)
            required = tuple(dict.fromkeys([*self.broker.positions, *(c.signal.symbol for c in guarded)]))
            now, quotes = self._quotes(required)
            for event in self.broker.mark(quotes, now):
                log.info("CLOSED: %s", event)
            # A missing held quote freezes all new entries; fresh legs may exit.
            self.broker.equity(quotes)
            for c in guarded:
                if len(self.broker.positions) >= self.cfg.max_positions:
                    break
                if not fresh(c, now, self.cfg.phase1.max_signal_age_ms) or c.signal.symbol not in quotes:
                    log.info("ENTRY_SKIP %s reason=913_stale_signal_or_missing_quote", c.signal.symbol)
                    continue
                ok, reason = self.broker.open(
                    c.signal, *quotes[c.signal.symbol], c.filters, quotes, now,
                    self.histories, funding=c.funding, depth=c.depth,
                )
                log.info("SIGNAL %s score=%s accepted=%s: %s strategy=913",
                         c.signal.symbol, c.signal.score, ok, reason)
        self._report(now, quotes)
