# Measurement-first upgrade log

## Phase 0 — blocked, no strategy promotion

Reviewed maintained main `c5e7dc5213556749945f6958eb31792facfb2409`
(VORTEX 0.2.0). Measurement work uses `research/phase0-baseline`; main stays intact.
No Phase 1–5 entry/risk/exit changes are authorized by these results.

### Changes and evidence

- Optional `VORTEX_SIGNAL_AUDIT=false`: canonical strategy emits accepted/rejected
  evaluated decisions to `DATA_DIR/signals.jsonl` when enabled. Votes not evaluated
  because an earlier gate rejected the candidate are **null**, not fictional
  abstentions. Available indicators, regime and exact veto are recorded. Forward
  outcome is explicitly pending; this does not calculate future shadow trades.
- Dedicated journal flock, fsync and propagated write errors; existing broker
  flock, crash journal, Testnet uncertainty handling and freshness checks untouched.
- Optional `VORTEX_EXTENDED_HISTORY=false`: opt-in 90-day pagination, strict first/
  last-bar coverage. Default remains 45 days. This is a larger data request, not an
  assurance that all-symbol 1m history fits a low-RAM Android phone.
- Descriptive per-voter win rate/PF/average R utility. Cohorts overlap; marginal
  contribution remains null until paired leave-one-voter-out replay exists.
- Bounded sequential command-attempt recorder with unique output folder, source
  hashes and full failure logs. It is not a complete baseline pipeline.

The four commands actually ran on 2026-10-09, 22:01:45–22:02:16 UTC (2026-10-10,
01:01:45–01:02:16 Asia/Amman), against instrumented reference
`544ea2b3884be2f179d742a45fe60011f1217035`:

| Command | Requested days | Exit code | Evidence |
|---|---:|---:|---|
| `vortex backtest --days 30` | 30 | 1 | HTTP 451 on exchangeInfo |
| `vortex portfolio-backtest --days 30` | 30 | 1 | HTTP 451 on exchange time |
| `vortex backtest --days 90` | 90 | 1 | HTTP 451 on exchangeInfo |
| `vortex portfolio-backtest --days 90` | 90 | 1 | HTTP 451 on exchange time |

Executed via the identical `python -m vortex.cli` entrypoint. Logs and source SHA256
are in [attempt manifest](../research/baselines/phase0-20261009/attempts.json).
**No market baseline loaded, no performance result accepted.** PnL, PF, win rate,
average R and marginal contribution are unavailable, not zero. No before/after
performance table can be produced. No claim about edge or profitability follows.

### Frozen next measurement plan (no price outcomes seen in this run)

- Cutoff: 2026-10-09 00:00 UTC, end exclusive. Thirty days:
  2026-09-09–2026-10-09; ninety days: 2026-07-11–2026-10-09.
  These are development/baseline periods, **not unseen validation**. The 30-day
  sample overlaps the 90-day sample and is not an independent confirmation.
- Initial fixed universe: BTC/ETH/SOL/BNB/XRP/DOGE USDT-M, with BTC as the
  single-symbol baseline. This does not reconstruct historical Radar membership.
- Keep current strategy/risk/operations, starting virtual equity 1000, taker fee
  0.0005; maker 0.0002 only if maker fills can actually be justified (none in current
  market-fill engine). No cheap maker rate assigned to market fills.
- Keep adverse ATR/spread/assumed-latency costs. Volume scaling is still pending;
  changing it requires a separately labeled cost-model experiment and comparison.
- Actual settlement events require published contemporaneous marks; as-of funding
  timing/OI/price inputs are separate data. Never insert final settlement rates as
  historically available forecasts. Both engines must use identical frozen sources.
- Protect stop-first 1m ambiguity handling, track gaps/open positions, exclude
  warmup from accounting, record source hashes and coverage. Missing history blocks
  the full-profile test; never silently switch guards off.
- Shadow rejected candidates independently with fixed rules, without letting their
  future outcomes affect entry-time votes. Null unobserved outcomes remain null.
- Voter ablations need identical windows/costs and full portfolio replays, because
  omitting a voter changes trade timing, capital, correlation and subsequent risk.
- Economic acceptance criteria remain unchanged: independent three months, PF
  >=1.2, >=100 validation trades, DD <=20%, positive net at doubled costs, followed
  by >=7 days forward PAPER. Any smaller cohort gets a low-sample warning.

### Problems found, still requiring work before a complete Phase 0

The current CLI cannot load historical depth/funding observations or a frozen
cutoff. Replay requires that input and will reject its absence even if REST works.
Historical `analyze` calls do not supply derivative votes. Single-symbol replay
does not settle funding, and its warmup/accounting window differs from portfolio
replay. Current portfolio CLI uses 5m exit execution despite downloading minutes;
1m replay exists in the engine but must be selected explicitly in a future harness.
Current OHLC engine skips strategy evaluation when exposure/cooldown/halt blocks
entries: the opt-in journal covers **evaluated candidates**, not every universe
candidate or every later execution-risk veto. Full shadow coverage remains pending.

### Rejected shortcuts

No disabled liquidity/funding guards to manufacture a full-profile baseline. No
synthetic candles passed off as market evidence. No causal contribution inferred
from overlapping cohorts. No profit claims from green CI. No new real-money path.

### Validation actually run

```text
python -m pytest -q
195 passed in 0.77s
ruff check --select E9,F63,F7,F82 vortex tests research
All checks passed!
python -m compileall -q vortex tests research
exit 0
```

Tests are synthetic software contracts, not market performance. The prior unchanged
main suite also ran: `190 passed in 0.82s`.

### Next three steps

1. Supply real hashed candles plus as-of execution/derivative observations from an
   accessible source, with the cutoff above and full warmup; do not bypass HTTP 451.
2. Complete a low-memory historical harness for frozen windows, funding, 1m exits,
   all-candidate shadow labels and paired voter ablations without changing strategy.
3. Run the four measurements and doubled-cost tests, report sample limitations,
   then review whether Phase 1 is justified. Until then Phase 0 remains blocked.
