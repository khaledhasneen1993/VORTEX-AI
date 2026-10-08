# VORTEX AI — Pre-Simulation Release Candidate

Binance USDT-M futures multistrategy market scanner, persisted PAPER broker, strict historical replay, and a separate TESTNET-ONLY guarded exchange adaptor.

**No real-money/production order route exists. No historical performance simulation or real Testnet API-order integration was run while preparing this release. Profitability is unknown.**

## Strategy — four independent voters

- Hourly completed EMA **50/200** market regime and 15m EMA/MACD/ADX trend.
- Five-minute mean reversion (Bollinger/RSI/VWAP) with real completed **1-minute RSI divergence and Stochastic RSI** confirmation.
- Five-minute volume breakout with directional OBV and relative volume.
- Live extreme funding-rate fade using authentic Binance premiumIndex and two independent, time-separated open-interest readings. Unavailable readings ABSTAIN.
- At least **TWO independent LONG or SHORT strategy votes** must agree. Hourly macro cannot oppose the decision.
- Optional liquid-mover radar (top 12), order-book/taker-flow filter, and exchange-timestamp-validated WebSocket bookTicker quotes.
- Optional Claude review (veto-only, no order/risk authority). Optional local logistic ML model needs real trade labels and chronological holdout validation.

## Risk and exits

- Default 1% risk per trade, max three concurrent PAPER positions, 5x modeled leverage, total margin cap 25%. No martingale.
- Halt new PAPER entries after five consecutively losing completed positions or daily portfolio drawdown >=5%.
- PAPER and OHLC replay: 25% TP1 at +1R, 25% TP2 at +1.5R, inward-only stop to breakeven after TP1 and tighter trailing after +2R. The remaining position exits at stop or main target.
- TESTNET commissioning: manually armed, single-entry position with exchange-side STOP_MARKET and TAKE_PROFIT_MARKET via Algo Orders. The armed guardian supports exchange-confirmed reduce-only quarter exits and create-verify-before-cancel stop replacement. Uncertain writes persist and require manual reconciliation. It has NOT been verified using a real Testnet API account.

## Local developer install

1. Clone https://github.com/khaledhasneen1993/VORTEX-AI and select the reviewed branch if PR #2 remains open.
2. Install Python 3.11+ and run: python -m pip install -e '.[dev]'
3. Copy .env.example to .env, edit only locally (never publish keys).
4. Run tests: python -m pytest -q
5. PAPER status: vortex status; readonly local dashboard: vortex dashboard

## Commands (not run while building this release)

- vortex paper --once — read public Binance prices and run ONE paper polling cycle
- vortex paper — continuous PAPER scanner on YOUR own host
- vortex backtest --symbol BTCUSDT --days 30 — honest one-symbol historical OHLC test
- vortex portfolio-backtest --days 30 — multi-symbol historical OHLC test
- vortex train-ai --dataset data/closed_trades.jsonl — requires 250+ genuinely completed labeled PAPER positions

Backtests may download tens of thousands of completed 1m candles per symbol; Binance throttling can slow or block requests. Historical data cannot recreate live funding/open-interest snapshots, dynamic radar selection or historical orderbook/taker-fill data from OHLC alone, so these live filters are not counted as historically validated. No market returns are claimed.

## TESTNET-only commissioning (may place orders with FAKE funds)

Keep credentials in local environment, never GitHub: VORTEX_TESTNET_KEY and VORTEX_TESTNET_SECRET issued for Binance TESTNET ONLY.

- vortex testnet-doctor — read-only check of isolated/one-way Testnet account
- Set VORTEX_TESTNET_ARM=TESTNET_ONLY and run vortex testnet-once --symbol BTCUSDT --ack-testnet only after reviewing the safeguards.
- vortex testnet-watch --ack-testnet — explicitly armed active TESTNET watchdog, may reduce open testnet positions and update protective STOP orders.

No production API keys are accepted in signed order paths. Testnet orders are never fired by running tests or starting the paper server. Avoid deleting or bypassing the persistent testnet order journal after an uncertain write.

## Optional configuration

- USE_WEBSOCKET=true — fixed-symbol public book quotes, reject out-of-order and stale exchange event time.
- USE_RADAR=true — liquid/fast-mover discovery (mutually exclusive with fixed-symbol WebSocket in current code).
- USE_MICROSTRUCTURE=true — real public depth and aggressor flow check.
- USE_CLAUDE=true — requires ANTHROPIC_API_KEY and optional VORTEX_CLAUDE_MODEL, veto-only; errors skip the signal.
- USE_AI_MODEL=true — requires a genuinely validated model in the private data directory. Invalid/missing model aborts the runner.
- Telegram alerting: VORTEX_TELEGRAM_TOKEN, VORTEX_TELEGRAM_CHAT_ID; keep both secret.

## Acceptance limitations

Green mocked tests do NOT certify real exchange compatibility, fund safety, live uptime or future profit. External real-world gates remain: signed TESTNET order integration, edge-case partial-fill/trigger testing, actual public WS latency/resume, month-scale portfolio results, forward PAPER trial, model training and independent security review before separate REAL-money code may even be considered.

Details: docs/COMPLIANCE_MATRIX.md and docs/REVIEW.md.
## Latest risk/accuracy acceptance changes

- Historic UTC daily loss baselines reset before a day's first entry in BOTH individual and synchronized portfolio replay. An already-triggered halt stays latched.
- Final portfolio reports include **equity_with_unrealized** and **open_positions_unrealized_net**; do not mistake the cash wallet for completed-profit equity.
- Public REST `bookTicker` and WebSocket quotes must carry fresh Binance exchange timestamps; stale or untimestamped quotes cannot authorize a PAPER or TESTNET entry.
- The funding/OI vote rejects missing or stale timestamps and duplicate OI observations.
- A partially filled TESTNET emergency reduction remains a HALTED state until manual reconciliation; it is never automatically repeated.
- Concurrent PAPER workers and TESTNET signing processes using one state directory are blocked with POSIX `flock` (Linux, Termux and Linux Docker). Stateful operation requires POSIX locking and is not supported natively on Windows.
- For a complete pre-simulation honesty/acceptance review, read **docs/ACCEPTANCE_STATUS.md**. Passing mocked tests does not certify real Testnet orders or production trading.
