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
- [x] Existing risk defaults remain: 1% stake risk, 3 max PAPER positions,
  5x leverage cap, 5% daily drawdown, halt after 5 successive completed losses.
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
