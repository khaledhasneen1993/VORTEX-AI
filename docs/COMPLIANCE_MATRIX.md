# VORTEX AI — strict four-source compliance matrix

Audit target: PR #2 branch feat/vortex-pre-simulation-hardening (not main).
This document distinguishes IMPLEMENTED CODE from VERIFIED LIVE PERFORMANCE.
No proprietary/private bot source code has been copied into VORTEX.

## Source 1 — Neko Futures Trader

- DONE: EMA/RSI/ATR/ADX and relative-volume signal scoring, protective stop/target policy, per-trade sizing, daily risk halt.
- DONE in paper and OHLC replay: stage TP1 at 1R for 25% original size, TP2 at 1.5R for 25%, break-even stop after TP1, then trailing remaining exposure once 2R favorable reached; best-quote fill versus OHLC stop-first fill modeling.
- NOT done on Binance testnet: live order replacement and partial exits. Testnet supports single guarded entry plus server-side close-all stop/target only; there is no autonomous order manager for multiple production trades.
- Deliberately NOT inherited: disabled daily loss breaker, unverified win-rate claims, unsafe cancel-before-replace of stops.

## Source 2 — Professional Quantitative Trading Bot

- DONE: four independent voted strategies — trend following, mean reversion, volume breakout and timestamped funding + open-interest fade — requiring TWO independent agreement votes before taking a signal.
- DONE: 1h completed macro trend gate, 15m confirmation, market-data-only funding and OI snapshots when available; otherwise funding strategy abstains.
- DONE: shared risk gates, ledger and multi-symbol OHLC portfolio replay.
- PARTIAL: strategy performance weighting is NOT enabled; no trustworthy evidence yet for adaptive weights.
- LIMITATION: funding/OI strategy cannot be historically replayed by current OHLC backtester because the required historical derivative snapshots are not recorded. Therefore historical performance evaluates the first 3 strategies only; NEVER claim complete parity with live funding filtering.

## Source 3 — Binance Futures AI Bot

- DONE: ATR-based exits and an offline logistic classifier training workflow with purged time-ordered holdout validation; an unvalidated model is rejected.
- DONE: entry-time feature recording with final closed PAPER round-trip labels; partial executions are journaled separately to prevent duplicate training labels.
- NOT trained: no 250+ independent labeled trade outcomes exist as of this review. An ML feature is NOT proof that useful predictive AI is active.
- NOT implemented: Claude or another LLM as autonomous market confirmation. That remains outside production trade permission until independently validated.

## Source 4 — StrikeChart

- DONE: corrected /public/stream bookTicker route and stale quote protection.
- DONE: real aggregated trade taker-flow / top-book depth filter and dynamic liquidity + price-change radar ranking based on market data, not fabricated whale/liquidation numbers.
- PARTIAL: radar is an opt-in candidate scanner; not a copy of StrikeChart's 18 detectors; custom UI and dedicated historical order-book capture have not been ported.
- LIMITATION: dynamic radar requires REST quotes and is deliberately incompatible with the fixed-symbol WebSocket stream in current version. Historical radar rankings are NOT replayed in current portfolio backtests.

## Pre-simulation safety requirements

- RUN_MODE remains paper/backtest only. Production funds MUST NOT be wired to repo.
- TESTNET is an explicitly armed single-entry commissioning path and MUST be verified against the actual exchange before use.
- Current testnet order manager does not support autonomous staged trailing like paper mode; do not call the two equivalent.
- No actual market simulation, real testnet orders, server deployment or model fitting has occurred in this development review.
- Before simulation: verify recorded signal counts on actual historical candles, then record fee/slippage sensitivity and forward paper fills.
- Only TESTNET-issued credentials; never commit tokens to GitHub.
