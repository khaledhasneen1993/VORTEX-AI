# VORTEX-AI 0.2.0

Current maintained release: aggressive Binance USDT-M **PAPER/BACKTEST** engine.
There is one strategy implementation and one current risk/operations profile.
No production trading route, wallet connection or Binance production keys are used.
Profitability is **not guaranteed or economically validated**.

## Current behavior

Radar ranks up to **24** liquid moving contracts after each completed 5-minute
candle. Trend Following and Volume Breakout are primary; Mean Reversion is limited
to range regimes. Weighted votes use completed 1H/15m/5m data, session and ATR
percentile filters, observed taker flow/CVD, and fresh paired funding/OI/price data.
Missing or future observations never count as affirmative votes.

| Setting | Current default |
|---|---:|
| Base risk parameter | 12% |
| Normal signal modeled risk | 8–10% |
| Strong signal modeled risk | 12–15% |
| Actual leverage ceiling | 5x |
| Maximum open positions | 4 |
| Aggregate margin ceiling | 25% |
| Daily loss halt | 55% |
| Trailing ATR multiplier | 0.8 |
| Price break-even | +0.8R |
| Scale-out | 30% at +1R, 30% at +1.5R, remaining trailing |

Actual size is constrained by margin, exchange minimums, modeled stop costs,
reserved profits and exposure correlation; risk budget is not margin allocation.
Pyramiding only adds to a sufficiently profitable trade with bounded risk. No
averaging down or martingale. Progressive loss cooldown and 1h/2h drawdown latches
persist across restarts. Protective exits continue when new entries are halted.

Fresh funding timing, spread and near-price depth gates protect entry/adds.
Volatility/spread/assumed-latency slippage is modeled, not measured exchange fills.
PAPER does not settle actual funding or simulate liquidation. Price break-even
can still produce a net loss after costs or a gap.

## Install and configure (Termux)

```sh
cd ~/VORTEX-20M
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e .
python -m vortex.configure --equity 20
```

Configuration updates `.env` while preserving existing secrets and unrelated
options. It selects the current financial defaults and a fresh isolated PAPER
state directory; it never starts trading, resets an old wallet, or migrates open
positions. Without `--equity`, the existing virtual starting balance is retained.
Old session artifacts are left intact. Stop an older process before starting the
new release. Never paste API tokens into chat or commit `.env`.

```sh
termux-wake-lock
python -m research.paper_hour --duration-seconds 10800 --starting-equity 20 \
  --output runs/vortex-020-3h
# Alternatively run the unbounded PAPER engine:
python -m vortex.cli paper
# Read-only dashboard in another Termux session:
python -m vortex.cli dashboard
```

The bounded runner uses a new output directory, real public market data and
virtual money only. It sends no Telegram messages and retains open positions at
its timer cutoff. An existing output is never overwritten. Avoid running duplicate
sessions. Android battery restrictions may stop a background process.

`OPS_FOCUS_SYMBOL=BTCUSDT` overrides PAPER Radar. `OPS_PROFILE=conservative`
reduces base risk/positions/day-loss caps; `aggressive` retains the table above.
Detailed Telegram notices are optional and disabled by default. Public-data manual
cards remain available as a separate command; they send no Binance orders or account
protection guarantees. See [manual review](research/MANUAL_REVIEW.md).

## Documentation and verification

- [Strategy](docs/PHASE1_STRATEGY.md): current weighted signal rules.
- [Risk](docs/PHASE2_RISK.md): budgets, reserves, correlation and pyramiding.
- [Operations](docs/OPERATIONS_PROFILE.md): exits, execution gates, monitoring,
  historical observation requirements and offline stress/version comparisons.
- [Acceptance status](docs/ACCEPTANCE_STATUS.md): maintained software vs economic validation.
- [Archived evidence](archive/README.md): inert previous measurements, not executable versions.

```sh
python -m pytest -q
python -m compileall -q vortex tests research
ruff check --select E9,F63,F7,F82 vortex tests research
```

Testnet auditing/protection utilities remain restricted to Binance TESTNET.
Automatic Testnet strategy entry is **not implemented** for this release and returns
an explicit refusal; no old strategy can be selected to bypass that limitation.
A green CI validates software checks, not a profitable strategy. Independent
three-month validation and seven-day forward PAPER acceptance are still pending.

## Measurement-first upgrade (research branch)

[Phase 0 log](docs/UPGRADE_LOG.md) records four attempted 30/90-day commands and
their HTTP 451 failures. No baseline performance was obtained; later phases are
blocked. Current entry/risk/exit rules remain unchanged. Optional
`VORTEX_SIGNAL_AUDIT=true` records evaluated canonical decisions, with unmeasured
forward outcomes explicitly null. `VORTEX_EXTENDED_HISTORY=true` enables up to
90 days; both flags default false. Large all-symbol minute datasets may exceed
Termux RAM. No new dependency is required.

To capture command attempts on a separate research checkout (not a complete
baseline pipeline; missing historical depth/funding still blocks full replay):

```sh
python -m research.phase0_attempts --reference-commit "$(git rev-parse HEAD)" \
  --output research/baselines/phase0-attempt-next --timeout-seconds 600
```

Output folders are exclusive and never overwritten. Records include command exit
codes, failure logs and source hashes. Cohort attribution is descriptive; marginal
voter contribution needs a separate paired ablation. See the log for missing work.

### Offline USD-M OHLCV archives (opt-in)

Official source/schema/checksum documentation:
https://github.com/binance/binance-public-data . No new dependencies.

Download a small verified example (UTC end date is exclusive):

```sh
python -m research.download_ohlcv --symbols BTCUSDT --intervals 1m --start 2026-10-06 --end 2026-10-09 --output data/ohlcv
```

For the frozen 90-day baseline, include warmup and all four intervals:

```sh
python -m research.download_ohlcv --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT DOGEUSDT --start 2026-07-01 --end 2026-10-09 --output data/ohlcv
VORTEX_EXTENDED_HISTORY=true vortex backtest --days 90 --symbol BTCUSDT --ohlcv-dir data/ohlcv --end-utc 2026-10-09
VORTEX_EXTENDED_HISTORY=true vortex portfolio-backtest --days 90 --ohlcv-dir data/ohlcv --end-utc 2026-10-09
```

These last two commands also require a genuine `data/ohlcv/exchange_info.json`
exchangeInfo snapshot containing the original `symbols`/`filters` structure. The
loader never guesses tick/lot/minimum-notional filters and never falls back to REST.
A current snapshot is not proof of historically applicable contract filters.
Local input requires `--days` and a fixed UTC end, and is refused for paper/testnet
workers. Alternatively set `VORTEX_LOCAL_OHLCV_DIR` and `VORTEX_LOCAL_END_UTC` in env;
both are empty/off by default. Existing 45-day default remains (90 is opt-in).

Daily CSVs and per-file manifests live under `data/ohlcv/SYMBOL/INTERVAL/`.
Downloads verify the publisher's `.CHECKSUM` before publishing; cached CSVs are
hash checked and never silently overwritten. Partial/corrupt caches fail for
inspection. Reads require complete UTC days, strict contiguous timestamps, finite
OHLCV and genuine taker-buy volumes. Download and CSV parsing stream one day at a
time; current backtest engines still materialize the requested bars in RAM.

**Scope:** this fixes archive candle access, not full Phase 0. OHLCV does not supply
historical depth/spread, as-of funding/OI or funding settlement marks. Existing
execution guards still reject absent observations; no filters are disabled to
manufacture results. Real smoke verification loaded 4,320 BTC 1m bars for Oct 6–8,
2026 (one measurement day plus two warmup days). No PnL was measured.

### Supplemental collection (not a complete replay dataset)

```sh
python -m research.download_supplemental --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT DOGEUSDT --funding-months 2026-07 2026-08 2026-09 --metrics-dates 2026-10-08 --depth-dates 2026-09-30 --fetch-filters --output data/ohlcv --evidence runs/supplemental-first.json
```

The evidence filename must be new. Archived files are cached with verified ZIP/
CSV hashes. Errors are recorded individually; a failed source never becomes a
successful dataset. `--fetch-filters` reads public exchangeInfo only, needs no
keys and refuses to overwrite an existing snapshot. A successful current snapshot
is not evidence of historical filter changes. Local reads check its manifest hash
when present. Running the same filters-only collector from Termux is possible:

```sh
python -m research.download_supplemental --fetch-filters --output data/ohlcv --evidence runs/filters-first.json
```

Observed in this run: July–September funding files downloaded for all six symbols;
October funding files were HTTP 404, exchangeInfo HTTP 451. September 30 aggregated
depth downloaded (including ±0.2% bands), but October 8 depth was HTTP 404. October 8
OI archives contain unordered raw rows; we preserve them and count that quality
issue rather than silently inventing a clean time sequence.

**No historical execution inputs are synthesized.** Final funding rates are not
pre-settlement forecasts; settlement marks are still missing. Aggregated depth has
no actual best bid/ask and is not passed as a fabricated price-level order book.
OI rows are not forward-filled past freshness bounds. Supplemental data is not yet
wired into trade replay. Phase 0 remains incomplete; no new PnL was measured.

For an accessible Termux connection, collect missing October funding plus the
exchange-published settlement mark (GET only, no credentials), using a new folder:

```sh
python -m research.download_supplemental --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT DOGEUSDT --fetch-filters --funding-rest-start 2026-10-01 --funding-rest-end 2026-10-09 --output runs/termux-inputs --evidence runs/termux-inputs-report.json
```

Raw paginated API responses are preserved with hashes; missing/invalid marks fail,
not replaced by candle prices. Finished pagination does not prove settlement
coverage, historical filter validity or pre-event forecast availability. This is
collection only, not simulation or order submission.
