"""Public-data signal cards for manual review; no account API or execution."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import logging
from math import isfinite
from pathlib import Path
import time

from .binance import Market, MarketError
from .config import Settings
from .derivatives import DerivativesTracker
from .models import Signal
from .radar import discover
from .risk import Filters, size_trade
from .strategy import analyze


def make_card(signal: Signal, bid: float, ask: float, now_ms: int,
              cfg: Settings, filters: Filters, *, equity: float | None = None,
              committed_margin: float = 0, positions: int = 0,
              day_start_equity: float | None = None) -> dict:
    """Sizing uses an operator-supplied snapshot; cards never reserve margin."""
    values = [bid, ask, committed_margin]
    if equity is not None:
        values.append(equity)
    if day_start_equity is not None:
        values.append(day_start_equity)
    if not all(isfinite(x) for x in values) or committed_margin < 0 or positions < 0:
        raise ValueError('Invalid manual account snapshot')
    if not 0 < bid <= ask:
        raise ValueError('Invalid public quote')
    if signal.side not in {'LONG', 'SHORT'}:
        raise ValueError('Invalid signal side')
    if (ask - bid) / ((bid + ask) / 2) * 10000 > cfg.max_spread_bps:
        raise ValueError('Spread exceeds configured limit')
    if not 0 <= now_ms - (signal.ts + (300000 if cfg.timeframe == '5m' else 900000) - 1) <= 90000:
        raise ValueError('Stale or future signal')
    sign = 1 if signal.side == 'LONG' else -1
    gap = abs(signal.entry - signal.stop)
    entry = ask if sign == 1 else bid
    entry *= 1 + sign * cfg.slippage_bps / 10000
    if gap <= 0 or abs(entry - signal.entry) > gap * .35:
        raise ValueError('Price moved too far from signal')
    adjusted = replace(signal, entry=entry, stop=entry - sign * gap,
                       target=entry + sign * abs(signal.target - signal.entry))
    card = {'mode': 'MANUAL_REVIEW', 'exchange_orders': 0,
            'created_ms': now_ms, 'expires_ms': signal.ts +
            (300000 if cfg.timeframe == '5m' else 900000) - 1 + 90000,
            'signal': asdict(adjusted), 'leverage': min(cfg.max_leverage, 5),
            'quantity': None, 'margin_usdt': None,
            'price_tick': filters.tick, 'prices_are_indicative': True,
            'account_source': 'operator_snapshot_not_connected',
            'sizing_status': 'amount_not_set',
            'instruction': 'Review current price, account positions and margin, then enter manually in Binance. This card sends no orders.'}
    if equity is not None:
        if equity <= 0 or day_start_equity is None or day_start_equity <= 0:
            raise ValueError('Sizing requires positive equity and day-start equity')
        if positions >= cfg.max_positions or equity <= day_start_equity * (1 - cfg.max_daily_loss):
            raise ValueError('Manual snapshot exceeds position/daily-loss limits')
        sized = size_trade(adjusted, equity, cfg, filters, committed_margin)
        if sized is None:
            raise ValueError('Exchange minimum or risk/margin cap prevents sizing')
        card.update(quantity=sized[0], margin_usdt=sized[1],
                    sizing_status='illustrative_recheck_snapshot_before_manual_execution')
    return card


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration-seconds', type=int, choices=[1200, 3600, 10800], default=10800)
    parser.add_argument('--equity', type=float, default=None)
    parser.add_argument('--day-start-equity', type=float, default=None)
    parser.add_argument('--committed-margin', type=float, default=0)
    parser.add_argument('--positions', type=int, default=0)
    args = parser.parse_args(argv)
    if args.equity is not None and args.day_start_equity is None:
        parser.error('--equity requires --day-start-equity')
    if (not isfinite(args.committed_margin) or args.committed_margin < 0 or args.positions < 0
            or any(x is not None and (not isfinite(x) or x <= 0)
                   for x in [args.equity, args.day_start_equity])):
        parser.error('Account snapshot values must be finite and valid')
    cfg = Settings.from_env()
    args.output.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(args.output / 'session.log')])
    logging.getLogger('vortex.votes').setLevel(logging.DEBUG)
    log = logging.getLogger('vortex.manual')
    market, tracker = Market(), DerivativesTracker()
    last_bucket = -1
    step = 300000 if cfg.timeframe == '5m' else 900000
    began = time.monotonic()
    log.info('MANUAL_REVIEW_STARTED: public data only; no keys, account connection or orders')
    with (args.output / 'cards.jsonl').open('x', encoding='utf-8') as out:
        while time.monotonic() - began < args.duration_seconds:
            try:
                now = market.server_ms()
                if now // step != last_bucket and now % step >= 5000:
                    for candidate in discover(market, limit=12):
                        if time.monotonic() - began >= args.duration_seconds:
                            break
                        symbol = candidate.symbol
                        bars = [market.candles(symbol, tf, count, now) for tf, count in
                                [(cfg.timeframe, 220), ('15m', 120), ('1h', 260), ('1m', 120)]]
                        try:
                            derivative = tracker.sample(market, symbol, now)
                        except (MarketError, KeyError, ValueError) as exc:
                            log.warning('Derivative unavailable %s: %s', symbol, exc)
                            derivative = None
                        decision = tracker.checked_ms or market.server_ms()
                        signal = analyze(symbol, bars[0], bars[1], cfg.min_score,
                                         macro=bars[2], minute=bars[3], derivatives=derivative,
                                         decision_ms=decision, strict_votes=cfg.strict_votes,
                                         min_strong_score=cfg.min_strong_score)
                        if signal:
                            quoted_at = market.server_ms()
                            quotes = market.quotes(now_ms=quoted_at)
                            reviewed_at = market.server_ms()
                            if symbol not in quotes:
                                log.info('CARD_SKIP %s missing fresh quote', symbol)
                                continue
                            try:
                                card = make_card(signal, *quotes[symbol], reviewed_at,
                                                 cfg, market.symbol_filters(symbol),
                                                 equity=args.equity, committed_margin=args.committed_margin,
                                                 positions=args.positions, day_start_equity=args.day_start_equity)
                            except ValueError as exc:
                                log.info('CARD_SKIP %s: %s', symbol, exc)
                                continue
                            out.write(json.dumps(card, ensure_ascii=False) + '\n')
                            out.flush()
                            log.info('MANUAL_CARD %s', json.dumps(card, ensure_ascii=False))
                    last_bucket = now // step
            except (MarketError, ValueError, KeyError, OSError) as exc:
                log.error('Manual scan failed closed: %s', exc)
            remaining = args.duration_seconds - (time.monotonic() - began)
            if remaining > 0:
                time.sleep(min(cfg.loop_seconds, remaining))
    log.info('MANUAL_REVIEW_ENDED: no exchange orders submitted')


if __name__ == '__main__':
    main()
