# Phase 1 strategy specification — 2026-10-09

Status: implemented, unit/integration tested; economic edge UNVALIDATED.
Parent: 7744b016393785f7866c8a6cd87fa37b6bb92ea2, research/hourly-development.
Main is preserved. No production signed endpoint or real-money route added.
Phase2 subsequently authorized/implemented; see PHASE2_RISK.md. Phases3/4 await approval.

## Enable / reproduce

`PHASE1_ENABLED=true` selects the new engine in PAPER, historical backtests,
manual cards and the existing explicitly armed TESTNET commissioning runner.
Settings constructed in code and environments without this flag retain legacy
behavior, preserving frozen research. The supplied `.env.example` enables
Phase 1 for NEW installations; existing `.env` files are not overwritten.
Use `TIMEFRAME=5m`; 15m and 1h are mandatory confirmation histories.
Keep Radar enabled and fixed-universe WebSocket disabled for the 24-symbol run.
Already running processes keep their loaded policy until restarted; do not
change an active experiment's configuration or overwrite its artifacts.

For a new isolated $20 virtual portfolio lasting three hours, after updating
and enabling Phase 1 in .env:

```sh
python -m research.paper_hour --duration-seconds 10800 --starting-equity 20 --diagnostics --output runs/phase1-paper-$(date +%Y%m%d-%H%M%S)
```

This wrapper forces PAPER and disables Telegram in its child environment. It
leaves open positions open at the end. This is not continuation of a previous
portfolio and submits no Binance orders. Phone background execution requires
its existing Termux wake-lock/battery configuration; this command alone cannot
prevent Android process termination.

## Entry logic (ordered, fail closed)

1. Require contiguous completed finite valid OHLCV histories: >=115 5m bars
   with the default ATR window, >=70 15m, >=210 hourly. Enforce interval lengths,
   no future bars, 90-second signal freshness, and frame-relative recency.
2. UTC session membership; defaults Asia [00,08), London [07,16), New York
   [13,22). Overlaps are allowed; 22–24 UTC is excluded. These are configurable
   UTC windows, not automatic DST-adjusted exchange session calendars and not
   direct measurements of liquidity. Disable/filter/customize based on tests.
3. ATR/price .0008–.045. Current Wilder ATR must rank >=40th percentile against
   the preceding 100 completed ATR values (current excluded from reference).
4. 1h EMA50/200, 15m EMA9/21 + MACD histogram, and 5m EMA9/21 must agree.
5. CVD over ten completed 5m candles uses Binance kline field [9] (taker-buy
   BASE volume). Delta = 2*taker_buy_volume - total_volume; summed delta divided
   by summed volume must be >=.05 in the proposed direction. This is rolling
   normalized CVD, not an order-book imbalance or liquidation heatmap. Missing
   taker data rejects when the filter is enabled; never infer it from OHLC sign.
6. Weighted votes below. Spread, quantity/min-notional, position, margin,
   cooldown and daily breaker gates still run after strategy acceptance.

| Strategy | Vote condition | Base weight | Trending boost |
|---|---|---:|---:|
| Trend | ADX15 >=25 and agreed MTF direction | 2 | +1 |
| Volume breakout | prior 20-bar high/low close breakout, volume >=2x, ADX5 >=18 | 2 | +1 |
| Mean reversion | both ADX5/15 <20; existing Bollinger/VWAP/RSI + completed 1m reversal | 1 | 0 |
| Funding fade | extreme funding, meaningful rising OI and aligned paired price change | 1 | 0 |

Normal: >=2 agreeing votes, weight >=4, weighted majority agrees with MTF,
and at least one primary (Trend/Breakout). Equal totals reject.
Strong: may use ONE primary vote of weight >=3, but ADX15 >=30, volume >=3x,
directional body >=.6 ATR, full MTF and all enabled global filters are still
required. Any opposing weighted vote rejects this exceptional path. Existing
MIN_SCORE remains required; legacy STRICT_VOTES/MIN_STRONG_SCORE govern only
legacy mode. Strong eligibility is recorded separately from acceptance.
A range reversion is auxiliary and cannot open a position alone.

Funding: |latest observed funding| >=.0015, OI rise >=.25%, paired mark price
change >=.10% in the fade direction over 60 seconds–30 minutes; both observations
must be fresh, derivative age <=15 seconds. Negative funding LONG requires
rising price; positive funding SHORT requires falling price. This is a
contrarian confirmation heuristic, not proof of liquidations or causal edge.
First sample, missing price, invalid time interval and weak change abstain.
Historical paths without actual derivative snapshots abstain on funding; they
must not be compared as equivalent to a fully instrumented live PAPER run.

## Configuration

Every field of `StrategyPolicy` maps to `PHASE1_<UPPERCASE_FIELD>` in .env;
all names/defaults are enumerated in `.env.example`. Weights, ADX levels,
lookbacks, session start/end hours, CVD/ATR/funding thresholds and strong
eligibility are adjustable. Boolean values must be true/false; nonfinite and
invalid ranges reject startup. Numeric price/OI thresholds ending `_PCT` use
percentage points; ATR_PCT limits are fractions; FUNDING_EXTREME is a raw rate.
Disabling CVD/ATR/session filters removes those protections and changes the
experiment. Configuration is captured by PAPER summary.asdict including the
nested Phase1 policy. Signal journals preserve policy features even when ML
feature snapshots are added. Debug VOTE/REJECT and PHASE1_VOTES explain decisions.

## Validation and limits

197 local pytest tests passed, fatal-code lint passed. Tests cover actual taker
parsing, missing/invalid flow, past-only ATR ranking, UTC overlaps/overnight,
fresh paired OI/price, weak/opposite funding, normal/strong weighted ties and
primary requirements, LONG/SHORT symmetry, MTF/gaps/future/staleness rejection,
range-only auxiliary reversion, filter switches and environment validation.
No authenticated Testnet order was sent during implementation. No new market
backtest/forward performance result is claimed. Historical source endpoint
availability and complete taker/OI coverage must be checked before measurement.

P1 is ONE preregistered policy configuration, zero performance trials so far.
Development: January–March 2026 (already exposed in prior research); September
and the supplied October observations also remain exposed. Proposed locked
validation: April–June 2026, July secondary, per the existing research ledger;
do not inspect/relabel a previously seen interval as unseen. Before executing
new research, verify these periods' exposure and retain source hashes and
configuration. Retire any period used to tune policy. Keep original acceptance:
>=3 validation months, >=100 trades, net positive, PF>=1.2, maxDD<=20%, positive
net with doubled fees/slippage, then >=7 days forward PAPER. Unit tests and
increased signal count do not meet this economic gate.

Aggression: the strong single-vote path can admit false positives; high ATR and
volume can select exhausted moves; CVD aggregation hides intrabar sequencing.
Additional filters can reduce opportunity and overfit. Financial caps remain
10% modeled stop budget, 5x effective leverage, 3 positions, 25% margin, 50%
daily breaker, no loss-streak halt. Stops, 3R objective, partial exits and
trailing policy remain unchanged. Profitability is not guaranteed.

## File map and remaining stages

| Stage | Files (created or modified) | Status |
|---|---|---|
| 1 | new vortex/phase1_config.py, vortex/phase1_strategy.py, tests/test_phase1.py, docs/PHASE1_STRATEGY.md; modified vortex/config.py, models.py, strategies.py, strategy.py, derivatives.py, cli.py, manual_signals.py, testnet_runner.py, backtest.py, portfolio.py, .env.example, README.md, docs/ACCEPTANCE_STATUS.md, research/EXPERIMENTS.md | Implemented on research branch |
| 2 | implemented vortex/phase2.py and tests/test_phase2.py; config/risk/paper/portfolio/backtest/exits/CLI/state and documentation integration | Implemented; see PHASE2_RISK.md |
| 3 | planned backtest.py, portfolio.py, stream.py, radar.py, journal/state modules; research walk-forward/Monte-Carlo/OOS tools and tests; env/README/acceptance | Not started; approval required |
| 4 | planned derivatives.py, microstructure.py, risk policy and veto adapters/tests; optional external heatmap only with verifiable data; env/README/acceptance | Not started; approval required |

Later file names are a planning map, not a claim of delivered implementations.
The complete Phase 1 source is in the research branch/PR, not pseudocode.

Official market schema checked 2026-10-09:
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
