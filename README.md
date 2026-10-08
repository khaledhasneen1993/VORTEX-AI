# VORTEX AI — four-source pre-simulation implementation

Python 3.11+ Binance USDT-M Futures market scanner and PAPER trading framework with a separate TESTNET-ONLY, manually armed one-shot execution experiment.

**No profit claims. No production orders. No live-money mode. No simulation has been started in this review.** This repository has NOT been certified for real futures trading.

## Current strategy: FOUR independent voters

1. 15m trend following with EMA, MACD histogram, ADX and a **completed 1h** macro bias.
2. 5m mean reversion with Bollinger expansion, short RSI, VWAP and market-regime check.
3. Volume-confirmed 5m price breakout and directional OBV.
4. Funding-rate crowding fade only when **real** funding and two separate open-interest readings exist, and the readings have not expired.

A trade needs at least TWO independent strategies agreeing on LONG or SHORT, plus the 1h macro must not oppose them. Missing derivative readings mean strategy #4 ABSTAINS. The historical OHLC backtest cannot independently reconstruct past funding/OI: its reported results include the first 3 voters only. No model may bypass risk gates.

## Running locally

Install from this PR branch, not main, until the user reviews the change.

- git clone https://github.com/khaledhasneen1993/VORTEX-AI.git
- cd VORTEX-AI
- git switch feat/vortex-pre-simulation-hardening
- python -m pip install -e '.[dev]'
- cp .env.example .env
- python -m pytest -q

Commands (DO NOT run unless you intend the corresponding work):

- vortex status — read-only PAPER portfolio status
- vortex dashboard — local-only http://127.0.0.1:8765 view
- vortex paper --once — one public-market scan and PAPER ledger update; no Binance orders
- vortex paper — ongoing paper runner on your OWN machine, not on GitHub
- vortex backtest --symbol BTCUSDT --days 30 — optional historical single-pair backtest
- vortex portfolio-backtest --days 30 — optional historical combined portfolio evaluation
- vortex train-ai --dataset data/closed_trades.jsonl — requires 250+ labeled completed trades and time-purged holdout validation
- vortex testnet-doctor — authenticated **read-only** testnet inspection (only with testnet keys)
- vortex testnet-once --symbol BTCUSDT --ack-testnet — only one order if env VORTEX_TESTNET_ARM=TESTNET_ONLY and all safety checks pass
- vortex testnet-watch --ack-testnet — armed TESTNET-only watchdog capable of emergency position reduction; requires explicit arm env

## Optional market inputs

- USE_WEBSOCKET=true uses the correct 2026 Binance PUBLIC /public/stream bookTicker route and rejects stale quotes.
- USE_RADAR=true ranks liquid USDT futures movers across exchange symbols using public 24h volume/change. It requires USE_WEBSOCKET=false because the current WS feed is fixed-symbol; mixing them is rejected.
- USE_MICROSTRUCTURE=true requires real order-book and aggregate-trade confirmation on selected positions.
- USE_AI_MODEL=true is **disabled by default** and fails closed unless the trained holdout model has been validated. Training from PAPER outcomes is not equivalent to real exchange fill performance.
- VORTEX_TELEGRAM_TOKEN and VORTEX_TELEGRAM_CHAT_ID provide optional alerting. Keep them secret.

## Risk and exits

- Default 1% risk per trade, at most three simultaneous paper positions, 5x modeled leverage cap, 25% total paper margin budget.
- Five consecutive losing **completed positions** latch the paper halt. Daily drawdown cap is 5%.
- Paper: quarter closes at +1R and +1.5R, then move remaining stop to entry and trail it inward after 2R favorable movement; any remaining quantity closes at main target or stop.
- Historical OHLC replay: staged exits use the same thresholds, with stop FIRST when a single candle touches stop and target. A touched bar level does **not** prove exchange liquidity/fill.
- Final closed trade labels are recorded once per complete round trip. Partial exits are stored in a separate file, do not become extra 'winning trades'.
- TESTNET currently only supports single guarded market entry with two exchange-held close-all protective orders, not paper-style staged TP/trailing. Never equate TESTNET and paper behavior.

## Verification limits and safety

Automated GitHub Actions tests exercise mocked/order-policy code; they DO NOT execute trades or prove strategy profit. The USD-M TESTNET order signing and Algo order paths have NOT been verified with real testnet keys in this review. No automated production adapter exists. Funding payments, historical order-book fills, mark-price trigger divergence, margin liquidation and market impact remain unmodeled in backtests.

No permission to turn on real trading is implied. The repository is PUBLIC. Never upload exchange credentials or the local .env file. Host deployment and long-lived PAPER tests require an independent always-on machine.

**Reviewer references:** docs/COMPLIANCE_MATRIX.md (the four original projects, specific coverage and missing work) and docs/REVIEW.md (acceptance checklist).
