# VORTEX AI — seven-point implementation acceptance

**Code milestone:** optional strong-vote mode, ATR-based trailing, explicit PAPER labels,
portfolio/single-symbol reports and TESTNET-only guarded orders.

## Implemented for controlled PAPER and historical experiments
- [x] `STRICT_VOTES=true` keeps two independent agreeing votes. Set `false` to admit
  one uncontested vote when score >= MIN_STRONG_SCORE (default 7), and
  relative volume >= 1.5 or ADX >= 25, and the hourly macro does not oppose.
  Every individual vote logs its direction/abstention and filter context.
- [x] ATR-based trailing after +2R guarantees a stop beyond +1R with small buffer,
  preserving the +1R/+1.5R 25% partial exits and final objective.
- [x] Both historical engines use UTC candle days for daily loss limits, model
  historical fees, and report closed trades, win rate, profit factor,
  max marked-equity drawdown, mean R and a bounded equity curve.
- [x] `vortex backtest` and `vortex portfolio-backtest` write complete JSON
  snapshots to `data/backtests/`, then print paths and summary metrics.
- [x] Full closed PAPER trade event records in `data/closed_trades.jsonl` include
  direction, approved votes, timestamps, original entry STOP/TARGET, indicators,
  net PnL and R. Partials remain in `data/partial_exits.jsonl` and do not
  inflate training labels.
- [x] Risk defaults updated to **10% maximum modeled trade-risk budget**
  (`risk_per_trade=0.10`), **5x leverage**, 3 simultaneous PAPER positions,
  25% aggregate margin cap, **50% daily drawdown halt**, no losing-streak halt.
  Quantity is the MINIMUM of loss-budget and margin/leverage caps; modelled
  round-trip fees and slippage count towards its loss budget.
- [x] `RUN_MODE=live` and actual funds remain unsupported.

## TESTNET-only guarded order path (code and MOCK tests)
- [x] Manual `vortex testnet-once --symbol BTCUSDT --ack-testnet` additionally
  requires `VORTEX_TESTNET_ARM=TESTNET_ONLY` and approved TESTNET-only credentials.
- [x] MAINNET environment aliases are rejected. As key types cannot be determined
  from their characters, a signed authentication challenge is made against
  `testnet.binancefuture.com` before any order; production keys will not authenticate.
- [x] Only one entry may be attempted; journaled INTENT/PROTECTING/PROTECTED/HALTED.
- [x] Server-held STOP_MARKET and TAKE_PROFIT_MARKET use Algo Orders, confirmed
  by a follow-up open-orders read rather than trusted acknowledgments.
- [x] Partial-entry and partial-reduce-only outcomes latch HALTED/unfinished
  journal; no automatic retry or duplicate write. Emergency flatten must
  confirm zero remaining exposure before declaring it done.
- [x] Mocked tests check client-ID isolation, unknown orders, stale exchange
  states and write-ahead durability.

## NOT independently verified
- [ ] Actual signed Binance Futures Testnet integration (no testnet credentials
  were accessed and **no real Testnet orders were sent**).
- [ ] Historical profit and forward paper performance, because this task requested
  **implementation and tests**, not a performance run.
- [ ] Historical replay of funding, order-book and radar constituents when
  no real timestamped archive exists. OHLC results cannot validate that edge.
- [ ] AI predictive accuracy: model training needs 250+ independent completed
  labeled paper trades and a holdout.
- [ ] Live VPS uptime / outages / restart behavior in market conditions.
- [ ] Production trading: not implemented, not authorized.

These statements deliberately distinguish TESTED MOCK LOGIC from actual exchange
execution. Read README.md for CLI usage.

## Seven-point user-specified update (implementation)

- STRICT_VOTES=true defaults to two agreeing strategies; false can permit a single uncontested vote only with score >= MIN_STRONG_SCORE (default 7), fresh higher-timeframe alignment, and relative volume >=1.5 or ADX >=25.
- TRAILING_ATR_MULT=1.0 uses current observed ATR after +2R with at least +1R and a small buffer protected; 25 percent at +1R and +1.5R remain.
- Historical single-symbol and portfolio summaries now include win rate, profit factor, average R, max drawdown and sampled equity curves. CLI writes full JSON to data/backtests.
- Closed paper events include entry-time indicators, approved votes, initial stop/target, net PnL and R. Partials remain separate, not duplicate training rows.
- Mainnet API variable aliases are rejected and an authenticated Testnet read is required before Testnet-only signed writes. Unexpected or partially confirmed writes latch journal HALTED.
- **Not proven:** actual signed TESTNET trading, partial-fill reconciliation with real exchange orders, backtest profitability, long-running PAPER performance, or ML predictive accuracy. No Live mode or real funds have been enabled.


## 2026-10-09 requested risk configuration change

- [x] Settings default `risk_per_trade=0.10` / `max_leverage=5`,
  loaded from `RISK_PER_TRADE` / `MAX_LEVERAGE`.
- [x] `STRICT_VOTES`, `MIN_STRONG_SCORE` and `TRAILING_ATR_MULT` remain wired to
  signal entry and staged exits in Paper, historical modes and guarded Testnet.
- [x] Validate 0 < risk <= 0.10, 1 <= leverage <= 10, 3 <= strong score <= 10,
  0.5 <= ATR multiplier <= 3.0.
- [x] `size_trade()` includes expected entry+exit fees and slippage in the
  10% risk ceiling and limits maximum total margin to 25% of marked equity.
  A position may legitimately use *less* risk when the margin limit binds.
- [x] `MAX_DAILY_LOSS=0.50` remains enabled; no consecutive-loss breaker is enforced.
  With an opening equity of 1000, new entries stop at equity <= 500;
  at 501 the daily-loss rule alone permits entry. This threshold does NOT
  limit per-trade losses or close an open position.
- [x] No Live path or real funds; Testnet remains unverified on a real Testnet
  account without operator-provided testnet credentials.

- [x] Hard invariant checks: leverage setting validates within 1..10, but
  every trading execution is additionally limited to **5x**. The hard limits
  remain three positions, 25% aggregate margin and a **50% daily breaker**.

## Final end-to-end audit of the 10% settings

- [x] `Settings.from_env()` returns real fields for `risk_per_trade=0.10`,
  `max_leverage=5`, `strict_votes=true`, `min_strong_score=7`,
  `trailing_atr_mult=1.0`. A trade-risk value over 0.10, non-finite
  configuration, and `RUN_MODE=live` are rejected.
- [x] Effective sizing caps leverage at 5x, aggregate margin at 25%,
  and conservative STOP-side round-trip fees/slippage inside the 10%
  maximum modeled loss budget (including SHORT stops above entry).
- [x] PAPER refreshes ATR from the latest completed candles for open
  positions **before** evaluating exits, with the last observed ATR
  preserved if market-data refresh is unavailable.
- [x] Repriced PAPER/TESTNET entry signals preserve vote IDs, technical
  indicator features and signal ATR. In TESTNET this supplies the staged
  trailing engine with its real, entry-time ATR.
- [x] A PAPER tick beyond the 4.5-ATR final target exits the entire
  remaining position instead of deferring to 25% partial orders.
- [x] Manual TESTNET supervisor rejects attempts above 5x, and if the
  exchange position disappears between audit and a staged update,
  HALTS for manual reconciliation instead of silently skipping it.
- [x] Regression tests include environment parsing, rejected 0.15 risk,
  effective 5x exposure, conservative SHORT stop costs, live-mode rejection,
  PAPER completed-ATR refresh and TESTNET metadata preservation.
- [ ] **Genuine TESTNET signed order integration still unverified.**
  No TESTNET credentials have been connected or orders issued here.
- [ ] No production trading or real-money Live mode exists.

## Daily portfolio loss change to 50%

- [x] `Settings.max_daily_loss` defaults to `0.50` and `Settings.from_env()` reads `MAX_DAILY_LOSS`, default `0.50`. Values outside `0 < max_daily_loss <= 0.50` are rejected.
- [x] `data`-backed PAPER and both historical modes use the same `RiskGate.can_open()` threshold: `equity <= day_start_equity * (1 - max_daily_loss)`, blocking **new entries** at a daily drawdown of at least 50%.
- [x] Tests verify 1000 -> 501 remains allowed by the daily rule, 1000 -> 500 triggers a latched halt, and configurations greater than 0.50 fail.
- [x] Unchanged: 10% planned stop risk per position, 5x maximum execution leverage, three open positions, no consecutive-loss breaker, 1.5-ATR initial stop and all staged exit/strategy rules.
- [ ] Signed Binance TESTNET behavior remains unverified on an actual Testnet account. No real-money route exists.

## Approved risk relationship (50% daily vs 10% per trade)

- **Daily portfolio circuit breaker = 50%** of that UTC day's starting equity. `RiskGate.can_open()` blocks **new entries** when `equity <= day_start_equity * (1 - 0.50)` and remains latched until an explicit risk reset.
- **Single-trade modeled risk budget = 10%** of current equity, subject to the existing 25% aggregate-margin and 5x effective-leverage caps; actual planned risk can be lower.
- **One position can lose approximately 10%** of equity at its planned stop **before the 50% portfolio breaker fires**. Gaps, costs or liquidation may cause greater actual loss; the daily breaker does not itself liquidate or close positions.
- [x] Unit coverage: `MAX_DAILY_LOSS=0.50` accepted; `MAX_DAILY_LOSS=0.60` rejected via both `Settings` and `Settings.from_env()`; starting equity 1000 permits 501 and halts at 500.
- [ ] Real signed Binance TESTNET behavior remains unverified; production Live mode is not available.

## Losing-streak halt disabled for full-month September replay

- [x] Removed `MAX_CONSECUTIVE_LOSSES` configuration/env setting and the `RiskGate` entry-block/latched halt triggered by losing streaks. This applies to PAPER and historical replay; TESTNET's separate order-safety HALT remains untouched.
- [x] A loss-streak counter may still be recorded in existing PAPER state for diagnostics and backward compatibility; it no longer changes eligibility for new trades.
- [x] Other limits unchanged: 10% planned position risk, 5× leverage, maximum three positions, 25% aggregate margin and a latched daily 50% equity breaker. Individual ATR stops and staged exits remain unchanged.
- [x] Regression coverage checks 10/20 successive losing trades still allow new entries, but the daily 50% breaker still halts them.
- [ ] Legacy local PAPER states previously halted by the old breaker stay halted until an explicit operator reset. Never reset old halted states automatically, because the halt reason might be daily risk.

## Phase 1 — 2026-10-09

Implemented on research/hourly-development, main unchanged. Full specification
and stage file map: [PHASE1_STRATEGY.md](PHASE1_STRATEGY.md).
Weighted primary strategies, range-only auxiliary reversion, UTC session,
ATR percentile, real rolling CVD, stronger 1h/15m/5m confirmation, fresh paired
funding/OI/price and exceptional strong single-vote path are configurable.

Functional verification: 197 pytest tests passed locally (12 new Phase 1 tests),
fatal-code lint passed. No actual Testnet order or new market-performance test
was performed. Economic acceptance remains PENDING, with unchanged research
gates. This is research implementation acceptance only, not profitability,
production readiness or authority to place real-money orders. No phase 2
risk increase, pyramiding, new state backend or phase 4 leverage/veto change.
