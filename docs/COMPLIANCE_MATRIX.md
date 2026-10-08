# VORTEX AI — strict four-source compliance matrix

Audit target: current main plus acceptance fixes in PR #3. Compare the exact commit and GitHub Actions SHA before using.
This document distinguishes IMPLEMENTED CODE from VERIFIED LIVE PERFORMANCE. Historical UTC daily drawdown, marked open positions, signed Testnet emergency-close confirmation, REST/WS freshness checks and single-writer locks were strengthened in PR #3.
No proprietary/private bot source code has been copied into VORTEX.

## Source 1 — Neko Futures Trader

- DONE: EMA/RSI/ATR/ADX and relative-volume signal scoring, protective stop/target policy, per-trade sizing, daily risk halt.
- DONE in paper and OHLC replay: stage TP1 at 1R for 25% original size, TP2 at 1.5R for 25%, break-even stop after TP1, then trailing remaining exposure once 2R favorable reached; best-quote fill versus OHLC stop-first fill modeling.
- TESTNET staged exits now implemented under an *explicitly armed guardian* for a single commissioned position. It uses confirmed reduce-only partial fills and replacement STOP create-verify-before-cancel. NOT yet proven with real testnet credentials, order latency, outage or mark-price trigger behavior.
- Deliberately NOT inherited: disabled daily loss breaker, unverified win-rate claims, unsafe cancel-before-replace of stops.

## Source 2 — Professional Quantitative Trading Bot

- DONE: four independent voted strategies — trend following, mean reversion, volume breakout and timestamped funding + open-interest fade — requiring TWO independent agreement votes before taking a signal.
- DONE: completed 1h EMA50/EMA200 macro trend gate, 15m confirmation, market-data-only funding and OI snapshots when available; otherwise funding strategy abstains.
- DONE: shared risk gates, ledger and multi-symbol OHLC portfolio replay.
- PARTIAL: strategy performance weighting is intentionally NOT enabled without genuine out-of-sample evidence. One-minute RSI divergence and StochRSI now confirm the mean-reversion vote; historical 1m data is downloaded independently.
- LIMITATION: funding/OI strategy cannot be historically replayed by current OHLC backtester because the required historical derivative snapshots are not recorded. Therefore historical performance evaluates the first 3 strategies only; NEVER claim complete parity with live funding filtering.

## Source 3 — Binance Futures AI Bot

- DONE: ATR-based exits and an offline logistic classifier training workflow with purged time-ordered holdout validation; an unvalidated model is rejected.
- DONE: entry-time feature recording with final closed PAPER round-trip labels; partial executions are journaled separately to prevent duplicate training labels.
- NOT trained: no 250+ independent labeled trade outcomes exist as of this review. An ML feature is NOT proof that useful predictive AI is active.
- Implemented optional Claude API veto with strict JSON schema, bounded timeout, no financial/account credentials exposed in the prompt, and no risk/size/stop authority. Disabled by default; cannot be validated without the user's own API key.

## Source 4 — StrikeChart

- DONE: corrected /public/stream bookTicker route and stale quote protection.
- DONE: real aggregated trade taker-flow / top-book depth filter and dynamic liquidity + price-change radar ranking based on market data, not fabricated whale/liquidation numbers.
- PARTIAL: radar is an opt-in candidate scanner; not a copy of StrikeChart's 18 detectors; custom UI and dedicated historical order-book capture have not been ported.
- LIMITATION: dynamic radar requires REST quotes and is deliberately incompatible with the fixed-symbol WebSocket stream in current version. Historical radar rankings are NOT replayed in current portfolio backtests.

## Pre-simulation safety requirements

- RUN_MODE remains paper/backtest only. Production funds MUST NOT be wired to repo.
- TESTNET is an explicitly armed single-entry commissioning path and MUST be verified against the actual exchange before use.
- TESTNET now has a guarded, explicitly armed single-position staged TP1/TP2 and tighter stop replacement, but this order lifecycle has only MOCK validation and no TESTNET integration evidence. It is NOT yet an autonomous multi-position production engine.
- No actual market simulation, real testnet orders, server deployment or model fitting has occurred in this development review. Public REST quotes and funding/OI snapshots now require fresh exchange timestamps.
- Before simulation: verify recorded signal counts on actual historical candles, then record fee/slippage sensitivity and forward paper fills.
- Only TESTNET-issued credentials; never commit tokens to GitHub.
