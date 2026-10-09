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

Testnet automatic portfolio entry remains unavailable; old commissioning strategy
was removed. Existing TESTNET-only audit/protection tools do not imply strategy
parity or a full automatic Testnet deployment.

## Cleanup policy

Old voting strategy, research-only entry/exit ablations, obsolete replay/search
scripts and their tests were removed. Historical measurements and exposure registry
are inert under `archive/`; they cannot be selected by the runtime. Old explanatory
material was replaced by current documentation. Git history remains intact; no
reset/force-push. Policy changes require a new state directory, not balance reset.
