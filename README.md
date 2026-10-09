# VORTEX AI — Canonical main: paper/testnet validation only

Binance USDT-M futures multistrategy market scanner, persisted PAPER broker, strict historical replay, and a separate TESTNET-ONLY guarded exchange adaptor.

**No real-money/production order route exists. No historical performance simulation or real Testnet API-order integration was run while preparing this release. Profitability is unknown.**

## Strategy — four independent voters

Default: `STRICT_VOTES=true` requires two agreeing votes. Optional `STRICT_VOTES=false` permits one uncontested high-score vote (`MIN_STRONG_SCORE=7`) with hourly trend alignment and Relative Volume >=1.5 or ADX >=25; see `docs/ACCEPTANCE_STATUS.md`.

- Hourly completed EMA **50/200** market regime and 15m EMA/MACD/ADX trend.
- Five-minute mean reversion (Bollinger/RSI/VWAP) with real completed **1-minute RSI divergence and Stochastic RSI** confirmation.
- Five-minute volume breakout with directional OBV and relative volume.
- Live extreme funding-rate fade using authentic Binance premiumIndex and two independent, time-separated open-interest readings. Unavailable readings ABSTAIN.
- At least **TWO independent LONG or SHORT strategy votes** must agree. Hourly macro cannot oppose the decision.
- Optional liquid-mover radar (up to 24), order-book/taker-flow filter, and exchange-timestamp-validated WebSocket bookTicker quotes.
- Optional Claude review (veto-only, no order/risk authority). Optional local logistic ML model needs real trade labels and chronological holdout validation.

## Risk and exits

- Default 10% **maximum modeled stop-risk budget** per trade, max three concurrent PAPER positions, 5x modeled leverage, total margin cap 25%. No martingale.
- Halt new PAPER entries at daily portfolio drawdown >=50%; a losing streak alone does not stop the bot.
- PAPER and OHLC replay: 25% TP1 at +1R, 25% TP2 at +1.5R, then after +2R guarantee +1R plus a small buffer and trail by latest completed ATR x `TRAILING_ATR_MULT` (default 1.0). The remaining position exits at stop or main target.
- TESTNET commissioning: manually armed, single-entry position with exchange-side STOP_MARKET and TAKE_PROFIT_MARKET via Algo Orders. The armed guardian supports exchange-confirmed reduce-only quarter exits and create-verify-before-cancel stop replacement. Uncertain writes persist and require manual reconciliation. It has NOT been verified using a real Testnet API account.

## Local developer install

1. Clone https://github.com/khaledhasneen1993/VORTEX-AI and use the canonical main branch.
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

The supplied `.env.example` enables dynamic radar with `USE_RADAR=true` and
`USE_WEBSOCKET=false`. Keep the fixed-symbol WebSocket disabled while radar is
enabled; enabling both is rejected at startup. Each completed-candle cycle
selects up to 24 active USDT-M perpetual candidates using observed 24h turnover
and absolute price change, then applies the existing Trend / Reversion /
Breakout / Funding vote engine and all risk gates. Ranking does not itself
authorize an entry. The 10% maximum modeled stop-risk budget, 5x effective
leverage, three-position limit and 25% total margin cap still apply.

- USE_WEBSOCKET=true — fixed-symbol public book quotes, reject out-of-order and stale exchange event time.
- USE_RADAR=true — liquid/fast-mover discovery (mutually exclusive with fixed-symbol WebSocket in current code).
- USE_MICROSTRUCTURE=true — real public depth and aggressor flow check.
- USE_CLAUDE=true — requires ANTHROPIC_API_KEY and optional VORTEX_CLAUDE_MODEL, veto-only; errors skip the signal.
- USE_AI_MODEL=true — requires a genuinely validated model in the private data directory. Invalid/missing model aborts the runner.
- Telegram alerting: VORTEX_TELEGRAM_TOKEN, VORTEX_TELEGRAM_CHAT_ID; keep both secret.

## Acceptance limitations

Green mocked tests do NOT certify real exchange compatibility, fund safety, live uptime or future profit. External real-world gates remain: signed TESTNET order integration, edge-case partial-fill/trigger testing, actual public WS latency/resume, month-scale portfolio results, forward PAPER trial, model training and independent security review before separate REAL-money code may even be considered.

Details: docs/COMPLIANCE_MATRIX.md and docs/ACCEPTANCE_STATUS.md.

## Latest risk/accuracy acceptance changes

- Historic UTC daily loss baselines reset before a day's first entry in BOTH individual and synchronized portfolio replay. An already-triggered halt stays latched.
- Final portfolio reports include **equity_with_unrealized** and **open_positions_unrealized_net**; do not mistake the cash wallet for completed-profit equity.
- Public REST `bookTicker` and WebSocket quotes must carry fresh Binance exchange timestamps; stale or untimestamped quotes cannot authorize a PAPER or TESTNET entry.
- The funding/OI vote rejects missing or stale timestamps and duplicate OI observations.
- A partially filled TESTNET emergency reduction remains a HALTED state until manual reconciliation; it is never automatically repeated.
- Concurrent PAPER workers and TESTNET signing processes using one state directory are blocked with POSIX `flock` (Linux, Termux and Linux Docker). Stateful operation requires POSIX locking and is not supported natively on Windows.
- For a complete pre-simulation honesty/acceptance review, read **docs/ACCEPTANCE_STATUS.md**. Passing mocked tests does not certify real Testnet orders or production trading.

## Version and build retention

Only `main` is maintained. The CI publishes no binary artifacts or releases. It retains the latest successful main workflow run; older run records and unchanged, merged feature branches are pruned by the main workflow after the quality checks succeed. Git commit history remains available for source recovery.

## Current seven-point controls and reporting

- `STRICT_VOTES=true`, `MIN_STRONG_SCORE=7`, `TRAILING_ATR_MULT=1.0` are validated in `.env.example`. New 10% requested trade-risk budget, 3 positions, 5x maximum leverage and 50% daily breaker are validated.
- `vortex backtest --symbol BTCUSDT --days 30` and `vortex portfolio-backtest --days 30` save full reports at `data/backtests/` with Win Rate, Profit Factor, Max Drawdown, Average R, and a compact Equity Curve. The CLI prints the path and summary.
- `data/closed_trades.jsonl` stores entry-time votes and indicators, initial stop/target, entry/exit timestamps, PnL and R. Partial fills are journaled separately to keep one label per round-trip.
- Manual TESTNET single-entry commissioning: `vortex testnet-once --symbol BTCUSDT --ack-testnet` with `VORTEX_TESTNET_ARM=TESTNET_ONLY` plus verified TESTNET-only credentials. Any ambiguous write halts for manual reconciliation; real TESTNET integration remains UNTESTED.
- No Live mode, production order path, mainnet wallet or real-money keys are supported.


## Config update: 10% risk, 5x leverage and hard margin cap

```dotenv
RISK_PER_TRADE=0.10
MAX_LEVERAGE=5
STRICT_VOTES=true
MIN_STRONG_SCORE=7
TRAILING_ATR_MULT=1.0
```

These values are loaded by `Settings.from_env()` and applied by `size_trade()`
to PAPER, Backtest and explicitly armed TESTNET entries. `size_trade()`
first determines a **maximum risk budget of 10% of current marked equity**
including modelled round-trip fees and slippage, then **reduces the order size**
if the aggregate 25% margin cap or 5x leverage would otherwise be exceeded.
With a tight stop, this can yield **actual planned stop-risk below 10%**;
the bot does not increase size or breach the margin cap to force exactly 10%.

**Important risk distinction:** the 50% daily drawdown stop is an
AFTER-THE-FACT circuit breaker, not a guarantee of a 50% maximum loss. A single
position sized under the 10% risk budget can lose more than its modeled budget due to gaps/slippage before
the daily circuit breaker blocks further entries. Slippage, gaps, funding and
liquidations can cause realized losses above modelled limits. This is a highly
aggressive PAPER/TESTNET setting; no live/real-money order path exists.

Manual experiment commands (no command started automatically):
```bash
vortex paper --once
vortex backtest --symbol BTCUSDT --days 30
vortex portfolio-backtest --days 30
```

**Non-bypassable policy limits:** configuration accepts `MAX_LEVERAGE` 1..10 as
requested for compatibility, but PAPER/BACKTEST sizing and TESTNET commissioning
always cap the **effective** trading leverage at **5x**. Values above
`MAX_POSITIONS=3`, `MAX_MARGIN_FRACTION=0.25`, or `MAX_DAILY_LOSS=0.50`
are rejected by `Settings` instead of loosening approved protections.
`MAX_CONSECUTIVE_LOSSES` is no longer loaded or enforced. Existing PAPER
state may retain a losing-streak counter as historical metadata, but it
does not block entry; an existing latched stop still needs explicit reset.

## Current end-to-end verification

The canonical Settings defaults are `risk_per_trade=0.10`,
`max_leverage=5`, `strict_votes=True`, `min_strong_score=7`,
and `trailing_atr_mult=1.0`. `Settings.from_env()` reads their
`.env` equivalents and rejects 0.15 trade risk or Live mode.

Execution safeguards: conservative SHORT stop-side fee/slippage budgets,
updated ATR from completed PAPER candles before managing already-open
positions, and preservation of all voted/ATR signal metadata on TESTNET
repricing. On a tick through the terminal 4.5 ATR target, the entire
remaining PAPER position exits at the executable quote rather than
delaying the final exit behind staged profit-taking.

Use local commands:
```bash
python -m pytest -q
vortex paper --once
vortex portfolio-backtest --days 30
```

**Genuine Binance TESTNET execution remains unverified**, and the 50% daily
breaker cannot guarantee that an individual 10%-risk position loses
no more than 50%. PAPER and historical simulation are not proof of profit.

### Daily portfolio circuit breaker: 50%

**Daily portfolio circuit breaker = 50%. Single-trade risk budget = 10%.** One position can lose approximately **10% of equity** at its planned stop **before the 50% daily breaker activates**; gaps, slippage or other costs could make the actual loss larger. The breaker blocks new entries, not existing positions, and is not a guaranteed loss limit.

The default is `MAX_DAILY_LOSS=0.50`. With a day's starting equity of 1000 USDT, `RiskGate` permits new entries at 501 USDT (assuming no other restriction) and blocks them at 500 USDT or below. Individual stops remain at 1.5 ATR, with the unchanged 10% modeled risk budget, 5x effective leverage and three-position cap. No Live/real-money execution is enabled.

## Phase 1 research strategy (2026-10-09)

The new `.env.example` selects `PHASE1_ENABLED=true`; existing .env files must
explicitly enable it. Missing/false keeps the frozen legacy vote engine.
Phase 1 requires TIMEFRAME=5m, full 15m/1h confirmation, weighted Trend/Volume
Breakout primary votes, range-only low-weight reversion, configurable UTC
sessions, past-only ATR percentile and actual kline taker-volume rolling CVD.
Funding needs fresh meaningful OI growth plus paired mark-price confirmation.
Strong high-volume aligned signals can use one primary vote; ordinary signals
need two. All thresholds and switches are PHASE1_* environment settings.

See [full rules, file map, test evidence and limitations](docs/PHASE1_STRATEGY.md).
197 local tests pass. Economic edge remains unvalidated; profitability is not
guaranteed. Financial risk caps, staged exits and effective leverage are
unchanged. PAPER/Testnet only; no real-money route. Phases 2–4 await approval.
