# VORTEX-AI 0.2.0 acceptance status

**Maintained software release:** current consolidated strategy/risk/operations code.
User-approved promotion replaces the old project implementation; it does not claim
financial performance approval. No production execution exists.

## Implemented

- One completed-data weighted strategy: trend and volume breakout primary,
  range-only reversion, observed funding/OI/price divergence, MTF/session/ATR/CVD.
- Dynamic 8–10% / 12–15% modeled risk, 5x leverage ceiling, four positions,
  25% aggregate margin, 55% daily-loss halt, 0.8 ATR trailing.
- Bounded profitable pyramiding, partial profit reserve and exposure correlation.
- +0.8R price break-even, 30/30/trailing runner, stagnation exit, conservative
  stop-first OHLC/gap handling with no retroactive tightened-stop fills.
- Fresh funding timing/depth/spread gates; modeled volatility and latency costs.
- Persisted loss cooldown and rolling drawdown latch; continued protective exits.
- Crash-recoverable journals, rejection records, sampled read-only dashboard,
  optional Telegram and PAPER Focus/aggressive/conservative configuration.
- Offline identical-source stress/version comparisons with explicit incomplete
  historical execution-model labeling when funding/depth observations are missing.
- Default/current configuration tests plus safety, no-lookahead, restart, cost,
  canonical replay, public-data and Testnet-boundary tests.

## Not accepted as a profitable system

Economic trials for the consolidated release: **0**. No fabricated market runs or
fills. At least three independent validation months, PF >=1.2, >=100 validation
trades, maximum drawdown <=20%, positive net with doubled fees/slippage, then
seven days forward PAPER are still required before an economic acceptance claim.
Observed September and October data remain development data. Criteria unchanged.

Measurement-first Phase 0: four actual command attempts (30/90-day single and
portfolio) failed at Binance public-data access with HTTP 451; **no completed
economic trial or baseline metrics**. Optional audit/history tooling is on the
research branch only, with future shadow outcomes and causal voter ablations still
pending. [Upgrade log](UPGRADE_LOG.md) contains hashes, logs, scope and blockers.

Testnet automatic portfolio entry remains unavailable; old commissioning strategy
was removed. Existing TESTNET-only audit/protection tools do not imply strategy
parity or a full automatic Testnet deployment.

## Cleanup policy

Old voting strategy, research-only entry/exit ablations, obsolete replay/search
scripts and their tests were removed. Historical measurements and exposure registry
are inert under `archive/`; they cannot be selected by the runtime. Old explanatory
material was replaced by current documentation. Git history remains intact; no
reset/force-push. Policy changes require a new state directory, not balance reset.

### Offline archive input follow-up

Optional local OHLCV reader/downloader verified against 4,320 real BTCUSDT 1m
candles (Oct 6–8, 2026), with official ZIP checksum and local CSV hashes. Local
software suite: 204 passing. This is input-integrity evidence only, not a completed
30/90-day baseline or economic acceptance. Missing historical execution/derivative
observations remain blocking; strategy and risk defaults are unchanged.

### Supplemental collection status

July–September: 1,656 actual funding rows (18 files); September 30: 207,360
aggregated depth rows (6 files); October 8: 1,728 raw OI rows (6 files). Publisher
ZIP checksums and CSV hashes verified. Genuine filters still unavailable (HTTP 451),
October funding/depth archives requested are unavailable (HTTP 404). Raw funding
is realized and lacks settlement marks/pre-event forecasts; aggregate depth is not
a bid/ask execution book. Full window/as-of coverage remains unproven. No new
backtest ran, Phase 0 remains incomplete, no economic acceptance or main merge.
Software suite: 213 passing locally.
