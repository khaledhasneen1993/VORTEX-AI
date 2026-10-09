"""Reproducible public-data calendar replay. Never signs or places orders."""
from __future__ import annotations
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import gzip
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
from zipfile import ZipFile

from vortex.config import Settings
from vortex.models import Candle
from vortex.portfolio import run_portfolio
import vortex.portfolio as portfolio
from vortex.research_policy import (filter_signal, confirmed_breakout,
                                    trend_pullback, range_reversion,
                                    compression_expansion, compression_retest,
                                    time_series_momentum)
from vortex.risk import Filters


def parse_months(value: str) -> list[str]:
    """Parse a chronological, gap-free calendar range for one continuous replay."""
    months = value.split(',')
    if not months or any(len(month) != 7 or month[4] != '-' for month in months):
        raise ValueError('Months must be comma-separated YYYY-MM values')
    indices = []
    for month in months:
        year, number = map(int, month.split('-'))
        if number not in range(1, 13):
            raise ValueError('Month number must be 01..12')
        indices.append(year * 12 + number - 1)
    if len(set(months)) != len(months) or any(b != a + 1 for a, b in zip(indices, indices[1:])):
        raise ValueError('Replay months must be unique, chronological and consecutive')
    return months


def public_bytes(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                data = response.read()
                return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def monthly(cache, symbol, interval, month):
    name = f"{symbol}-{interval}-{month}.zip"
    url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{name}"
    path = cache / name
    if not path.exists():
        data = public_bytes(url)
        tmp = path.with_suffix('.part')
        tmp.write_bytes(data)
        tmp.replace(path)
    data = path.read_bytes()
    with ZipFile(BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError(f"Unexpected archive: {name}")
        rows = list(csv.reader(StringIO(archive.read(names[0]).decode())))
    if rows and rows[0][0] == 'open_time':
        rows = rows[1:]
    bars = [Candle.from_binance(row) for row in rows]
    step = {'1m':60000, '5m':300000, '15m':900000, '1h':3600000}[interval]
    year, m = map(int, month.split('-'))
    start = int(datetime(year, m, 1, tzinfo=timezone.utc).timestamp() * 1000)
    count = calendar.monthrange(year, m)[1] * 86400000 // step
    if len(bars) != count or any(c.ts != start + i * step or c.close_ts != c.ts + step - 1
                                 for i, c in enumerate(bars)):
        raise ValueError(f"Incomplete or malformed calendar data: {name}")
    if any(not (c.low <= c.open <= c.high and c.low <= c.close <= c.high) for c in bars):
        raise ValueError(f"OHLC inconsistent: {name}")
    return bars, {'url':url, 'sha256_zip':sha256(data).hexdigest(), 'rows':len(bars)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--month', required=True,
                        help='One YYYY-MM month or a consecutive comma-separated range')
    parser.add_argument('--decision-interval', choices=['5m','15m'], default='5m')
    parser.add_argument('--execution', choices=['5m','1m'], default='5m')
    parser.add_argument('--entry-policy', choices=['baseline','extension-cap','confirmed-breakout','cost-floor','invert-direction','trend-pullback','range-reversion','range-reversion-ablation','compression-expansion','compression-expansion-cost','compression-retest','time-series-momentum'], default='baseline')
    parser.add_argument('--exit-policy', choices=['baseline','fixed-1r','fixed-3r','breakout-invalidation','pair-horizon'], default='baseline')
    parser.add_argument('--portfolio-policy', choices=['baseline','relative-strength-pair','relative-strength-reversal'], default='baseline')
    parser.add_argument('--cost-multiplier', type=float, default=1)
    parser.add_argument('--cache', type=Path, default=Path('data/research-cache'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Never overwrite a saved experiment')
    if not 0 < args.cost_multiplier <= 5:
        raise ValueError('Cost multiplier must be in (0,5]')
    source_hashes = {str(p):sha256(p.read_bytes()).hexdigest()
                     for p in sorted([*Path('vortex').glob('*.py'), Path(__file__).relative_to(Path.cwd())])}
    cfg = replace(Settings(), timeframe=args.decision_interval)
    cfg = replace(cfg, fee_rate=cfg.fee_rate * args.cost_multiplier,
                  slippage_bps=cfg.slippage_bps * args.cost_multiplier)
    args.cache.mkdir(parents=True, exist_ok=True)
    months = parse_months(args.month)
    year,m = map(int,months[0].split('-'))
    previous = f'{year-1}-12' if m == 1 else f'{year}-{m-1:02}'
    specs = [(sym, interval, mon) for sym in cfg.symbols for interval in ['5m','15m','1h','1m']
             for mon in (months if interval == '5m' else [previous,*months])]
    def read(spec):
        return spec, monthly(args.cache,*spec)
    with ThreadPoolExecutor(max_workers=4) as pool:
        loaded = dict(pool.map(read,specs))
    filter_source = 'https://www.binance.com/fapi/v1/exchangeInfo'
    snapshot = args.cache / 'exchangeInfo.json'
    if not snapshot.exists():
        raw = public_bytes(filter_source)
        decoded = json.loads(raw)
        if not isinstance(decoded.get('symbols'), list) or 'serverTime' not in decoded:
            raise ValueError('Refuse non-exchangeInfo response')
        with snapshot.open('xb') as target:
            target.write(raw)
    exchange_raw = snapshot.read_bytes()
    exchange = json.loads(exchange_raw)
    info = {x['symbol']:x for x in exchange['symbols']}
    filters = {sym:Filters.from_exchange(info[sym]) for sym in cfg.symbols}
    def history(interval):
        return {sym:sum((loaded[(sym,interval,mon)][0] for mon in
                       (months if interval == '5m' else [previous,*months])), []) for sym in cfg.symbols}
    original_analyze = portfolio.analyze
    def research_analyze(*pos, **kw):
        if args.entry_policy == 'time-series-momentum':
            return time_series_momentum(*pos, **kw)
        if args.entry_policy == 'compression-retest':
            return compression_retest(*pos, **kw)
        if args.entry_policy == 'compression-expansion-cost':
            return filter_signal(compression_expansion(*pos, **kw), 'cost-floor')
        if args.entry_policy == 'compression-expansion':
            return compression_expansion(*pos, **kw)
        if args.entry_policy == 'range-reversion-ablation':
            return range_reversion(*pos, require_minute_confirmation=False, **kw)
        if args.entry_policy == 'range-reversion':
            return range_reversion(*pos, **kw)
        if args.entry_policy == 'trend-pullback':
            return trend_pullback(*pos, **kw)
        if args.entry_policy == 'confirmed-breakout':
            return confirmed_breakout(original_analyze, *pos, **kw)
        return filter_signal(original_analyze(*pos, **kw), args.entry_policy)
    portfolio.analyze = research_analyze
    print('Data validated; replay starts', flush=True)
    decision = {sym:sum((loaded[(sym,args.decision_interval,month)][0]
                         for month in months), []) for sym in cfg.symbols}
    higher_interval = '15m' if args.decision_interval == '5m' else '1h'
    report = run_portfolio(decision,history(higher_interval),filters,cfg,macro=history('1h'),
                           minute=history('1m'),execution_interval=args.execution,diagnostics=True,
                           exit_policy=args.exit_policy,portfolio_policy=args.portfolio_policy)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    dirty = subprocess.check_output(['git','status','--porcelain'],text=True).strip()
    config = asdict(cfg); config['data_dir'] = str(config['data_dir'])
    output = {'month':months[0] if len(months) == 1 else None, 'months':months,
              'continuous_across_months':len(months) > 1,
              'base_commit':commit,'working_tree_dirty':bool(dirty),
              'source_hashes':source_hashes,
              'decision_interval':args.decision_interval,
              'execution_interval':args.execution, 'entry_policy':args.entry_policy,
              'exit_policy':args.exit_policy, 'portfolio_policy':args.portfolio_policy,
              'cost_multiplier':args.cost_multiplier,
              'filter_source':filter_source,'filter_sha256':sha256(exchange_raw).hexdigest(),
              'filter_server_time':exchange['serverTime'],
              'config':config,'filters':{s:asdict(f) for s,f in filters.items()},
              'sources':[{'symbol':s,'interval':i,'month':m,**v[1]} for (s,i,m),v in loaded.items()],
              'limitations':['Current exchange filters, not historical filters',
              'OHLC intrabar ties remain stop-first, including 1m',
              'No historical funding, liquidation or order-book replay',
              'MFE/MAE excludes terminal bar and is a pre-exit lower bound; within-minute sequence unknown',
              'Risk gate and equity drawdown sampled at 5m boundaries; 1m changes exit execution only'],
              'report':report}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as target:
        json.dump(output,target,indent=2)
    print(json.dumps({k:report[k] for k in ['closed_trades','realized_net_pnl','profit_factor',
          'max_drawdown_pct','total_fees','equity_with_unrealized','open_positions']}),flush=True)

if __name__ == '__main__':
    main()
