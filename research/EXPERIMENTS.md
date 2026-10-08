# VORTEX research ledger

## Protocol registered 2026-10-08 UTC

Base: ef623d37ab411ca13864450940ee786a08eca1d4. Main stays unchanged.
Risk unchanged: 10% modeled stop budget, 5x effective leverage, 3 positions,
25% aggregate margin, 50% daily latched breaker; no loss-streak halt.
Research only, no signed exchange calls, keys or real funds.

September 2026 is already exposed DEVELOPMENT data. Never call it holdout.
Run chronological expanding-window tests on other months and explicitly mark
any previously exposed month. A historical test before the September evidence
is retrospective robustness, not a genuinely prospective test of this design.
The final independent evidence must include forward PAPER >=7 days. Passing
this gate is a promising research result, not guaranteed future profitability.

Pre-registered acceptance target: positive net over >=3 independent monthly
validation periods, aggregate PF >=1.2, >=100 validation trades, maxDD <=20%,
positive net with fees AND slippage doubled. Record trial count and periods;
never change thresholds after seeing those same validation results.
Do not inspect validation returns to choose among many parameter settings.
If reused to choose the next hypothesis, retire that period from holdout use.

## E000 — reproduce original 5m baseline with diagnostic tracing

Status: pending replay. Original attachment reported 105 closes,
net -158.704105, ending equity 841.295895, PF .4949635292,
maxDD 15.87%, fees 104.04376. Use actual September monthly archives,
August 1m/15m/1h warmup, current exchangeInfo filters. Preserve archive hashes.
5m does NOT receive August warmup to match the original calendar replay.
Caution: original attachment says ~65 warmup bars but strategy requires >=70.

Command: `python -m research.replay --month 2026-09 --execution 5m --output research/results/E000-baseline-5m.json`

## E001 — exit-resolution measurement, same signals and risk

Status: pre-registered; not a strategy improvement claim.
Use actual 1m bars for exit execution, stop-first within each remaining
ambiguous minute. This can reduce 5m ordering ambiguity but does not recreate
tick paths. ATR and signal decisions use completed 5m bars; risk/equity checks
remain at 5m boundaries. Compare trades and PnL, do not cherry-pick either mode.
MFE/MAE fields exclude terminal execution bar; they are lower bounds and cannot
establish exact ordering inside a minute. Partial-exit and stop traces expose
execution accounting. Re-run default without tracing to verify unchanged PnL.

Command: `python -m research.replay --month 2026-09 --execution 1m --output research/results/E001-baseline-1m.json`

## E002 — avoid stretched breakout entries (first strategy hypothesis)

Status: pre-registered before E000/E001 results are generated.
Hypothesis: consensus trend+breakout entries may chase exhausted moves.
Single change: reject a signal if abs(close - EMA9)/ATR > 2.0. Exactly 2.0
passes. Missing/nonfinite measurement rejects in this experimental policy.
No search of alternate thresholds, symbols, leverage or stop-risk parameters.
Run with 1m exits, compare with E001. Main/PAPER defaults remain unchanged;
research policy is explicitly selected by `--entry-policy extension-cap`.
If this DEVELOPMENT result fails, record it and formulate E003 using diagnostics.
If it improves, freeze it and collect independent evidence before promotion.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy extension-cap --output research/results/E002-extension-cap-1m.json`

## Verification and next-run handoff

118 local tests passed after diagnostics, 1m ordering and opt-in policy changes.
Dedicated tests verify unchanged coarse accounting, precise partial-fee sums,
minute-order resolution, refusal of missing minutes, exclusion of post-exit
extremes and frozen filter threshold.
Primary fapi.binance.com returned HTTP451 here. Public fapi1.binance.com
exchangeInfo succeeded; record the exact endpoint and response hash.
Data cache is reproducible intermediate data under ignored data/; results and
this ledger must be committed on research/hourly-development before ending.
Check PR and Actions before launching another replay. Never overlap a duplicate
experiment. Save failing experiments, not just the winner.
