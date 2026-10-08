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
  25% aggregate margin cap, 5% daily drawdown halt, 5 successive-loss halt.
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
- [x] `MAX_DAILY_LOSS=0.05` and five-consecutive-loss halt remain enabled.
  **A 10% per-position risk budget can exceed a 5% daily loss limit in one
  stopped-out position**. The daily breaker blocks later entries; it is
  NOT a guarantee no single trade loses over 5%.
- [x] No Live path or real funds; Testnet remains unverified on a real Testnet
  account without operator-provided testnet credentials.
