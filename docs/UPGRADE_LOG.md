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

## Local archive follow-up — candle access verified, Phase 0 still incomplete

- Added `vortex/local_data.py`: verified CSV history, frozen end-exclusive UTC date,
  no REST fallback, real exchangeInfo filters required, source manifests on reports.
- Added `research/download_ohlcv.py`: official daily USD-M ZIPs + publisher SHA256,
  bounded streamed downloads, safe member reads, atomic file publication and flock,
  cache integrity checks/no overwrite. No strategy/risk/execution guard changed.
- Routed only historical CLI commands via opt-in `--ohlcv-dir`/`--end-utc`, with
  empty-default env equivalents. Updated README and `.env.example`.
- Nine software tests cover archive corruption, paths, gaps, malformed prices/
  volumes, cache tampering, range completeness and rejection of live-worker use.
- Actually downloaded BTCUSDT 1m archives for 2026-10-06, 07 and 08; the existing
  Oct 8 verified cache was reused. Actual offline load returned **4,320 rows**,
  first open `1791244800000`, last close `1791503999999`. Source URLs and ZIP/CSV
  hashes: `research/baselines/local-ohlcv-20261009/verification.json`.
- Actual local validation: `204 passed in 0.88s`; fatal lint `All checks passed!`.
  An initial new test exposed dotenv pollution between tests; isolated its env
  loading and reran the full suite successfully. Production defaults unchanged.
- Supersedes the original candle-access/frozen-cutoff blocker, but not remaining
  Phase 0 gaps. No 30/90-day economic baseline ran against the local archives yet.
  Historical exchange filters, depth/spread, derivative observations/settlements,
  full shadow labels and paired voter ablations remain outstanding. No economic
  comparison, profitability claim or Phase 1 promotion.

## Supplemental collection — real evidence acquired, baseline still blocked

Actual run on 2026-10-09 UTC / 2026-10-10 Asia/Amman:

| Source | Acquired | Missing / limitations |
|---|---:|---|
| Realized funding, six symbols, July–September | 18 verified files, 1,656 rows | October monthly archive: HTTP 404 for six symbols; no event mark/forecast |
| Aggregated depth, six symbols, September 30 | 6 verified files, 207,360 rows | October 8: HTTP 404; percent bands incl. ±0.2%, but no best bid/ask |
| OI metrics, six symbols, October 8 | 6 verified files, 1,728 rows | Unordered raw observations; only a one-day sample |
| Current genuine contract filters | None | Official exchangeInfo returned HTTP 451 |

Added `research/download_supplemental.py` using requests + standard library only:
allowlisted official read-only sources, publisher ZIP checksum validation, streamed
bounded downloads, CSV schema/value/time checks, flock, cached source hashes and
exclusive durable evidence files. Each failed request is retained in the collection
report. Current filter snapshots require actual lot/tick/minimum notional fields;
no defaults are fabricated. Added hash validation for local filter manifests.

Initial metrics validation rejected all six official raw files as unordered. On
inspection, ordering is a source-quality issue rather than an excuse to discard
raw evidence: the collector now preserves unchanged CSVs and explicitly reports
unordered transitions/duplicates and min/max observation times. A separate retry
report preserves the original rejection history. This does not normalize, make
fresh or inject those data into the strategy.

Raw funding timestamps (including non-minute offsets) remain unchanged. No final
funding rate is used as a prior entry-time observation and no candle price is
asserted to be the exact settlement mark. Depth aggregate bands are not converted
to fictional book levels. No strategy, risk, cost, guard or real-order path changed.

Evidence and hashes: `research/baselines/supplemental-20261009/collection.json`,
`metrics-retry.json`, `readiness.json`. Actual local suite: `213 passed in 0.89s`;
fatal lint passed; compile exit 0. Nine new tests include preserving unordered raw
observations, archive corruption, genuine filter field requirements, cache refusal
and filter manifest tampering.

**No backtest rerun:** required inputs are not complete. Full 30/90-day OHLCV,
October funding, actual filter snapshot/history, as-of funding/depth/quotes and
historical derivative wiring remain pending. Shadow coverage and paired ablations
also remain unfinished. No baseline, performance figure or promotion is claimed;
main stays intact and this work remains in PR #12.

### Termux handoff helper

Added explicit `--funding-rest-start/--funding-rest-end` to the read-only supplemental
collector so an accessible connection can acquire October settlements and actual
published mark prices in one command alongside filters. Raw API pages/hashes are
preserved; bounded pagination, strict ordering/range/finite-value checks, no
inferred marks or prior forecasts. No successful remote download is claimed from
this environment; software tests use synthetic responses. This does not complete
Phase 0 or change the existing blocked data evidence.

## 2026-10-10 — Non-execution signal shadow evidence (research only)

After verified 90-day OHLCV source acquisition, the full-guard single and
portfolio trials remained correctly blocked: source archives have no genuine
as-of bid/ask, book levels, or contemporaneous funding/OI/mark observations.

- Added `research/phase0_shadow_signals.py`: **explicitly invoked** separate
  30/90-day signal-only measurement, using the unmodified canonical strategy and
  verified local 1m/5m/15m/1h candle histories. Outputs every accepted/rejected
  vote/indicator/veto decision in JSONL, plus later 60-minute observed *market*
  price movement, never executable PnL, fills or trading performance.
- Read-ahead only creates descriptive shadow labels **after** the decision; future
  bars are not supplied to the strategy. Absent as-of funding/OI cannot vote.
  No attempt is made to invent historical spread, depth or historical filters.
- Added synthetic-only contract tests under `tests/test_phase0_shadow.py`.
  Economic acceptance remains false; attribution is descriptive, not causal.
- Added isolated six-symbol GitHub Actions research workflow (parallel, bounded,
  real publisher-checksummed archives) at `.github/workflows/phase0-shadow.yml`.
  Its first run is
  [38037051647](https://github.com/khaledhasneen1993/VORTEX-AI/actions/runs/38037051647).
  Results, trade counts, net PnL and profit factor **must not** be assumed in advance.
- The production PAPER / TESTNET guards, strategy votes, sizing, runtime CLI,
  `.env.example` defaults and 55% daily breaker have not been modified.
  PR #12 is not merged; research signal shadow is not Phase 0 economic completion.
- Genuine full-period L2/order-book quote history requires a compatible real
  historical data source or fresh forward recording; official aggregated
  `bookDepth` percent bands cannot be silently promoted to executable levels.
  A subscription data source would require explicit user approval before purchase.
