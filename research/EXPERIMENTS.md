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
Primary fapi.binance.com returned HTTP451 here. The fapi1 hostname returned an HTML redirect (rejected as metadata).
The official www.binance.com/fapi/v1/exchangeInfo endpoint returned validated
JSON. Freeze one metadata snapshot across compared experiments and record its
serverTime, endpoint and SHA256; no invented exchange filters.
Data cache is reproducible intermediate data under ignored data/; results and
this ledger must be committed on research/hourly-development before ending.
Check PR and Actions before launching another replay. Never overlap a duplicate
experiment. Save failing experiments, not just the winner.


## Results recorded before E003

| Experiment | Closes | Net USDT | End equity | PF | MaxDD % | Fees |
|---|---:|---:|---:|---:|---:|---:|
| E000 original 5m | 105 | -158.704105 | 841.295895 | .4949635292 | 15.870 | 104.043760 |
| E001 original 1m | 104 | -165.642777 | 834.357223 | .4773810153 | 16.564 | 104.703677 |
| E002 extension cap | 73 | -144.050378 | 855.949622 | .4070429079 | 14.588 | 75.161091 |

E000 exactly reproduces attachment PnL/count/fees/PF. E001 confirms loss is not
fixed by finer exit ordering. E002 FAILS: less absolute loss with fewer trades,
but worse PF and worse average net per trade; reject for promotion.
59 no-partial E001 positions lost a combined 308.366 USDT; 45 staged positions
netted +142.7232. Pre-entry average EMA9 distance was 2.126 ATR in winners vs
1.810 in losers. Capping extension removed some stronger profitable moves.
These are descriptive development findings, not causal proof.

## E003 — require completed continuation after breakout

Registered after inspecting E000-E002 development results; independent returns
have not been read. Hypothesis: immediate entries include breakouts that fail
before TP1; test confirmation rather than clipping stronger moves.
One new closed 5m candle must continue past the candidate close in its direction
and have a body in that direction. Recompute the original candidate using only
histories available at the PREVIOUS close. If hourly macro flips, reject.
Reprice stop/target around the confirmation close preserving original ATR
distances. Entry is NEXT bar open with normal gap/slippage checks. No other
filter or risk change, no EMA extension cap, no optimizing thresholds.
Main and PAPER remain unchanged. Compare to E001 on exposed September only.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy confirmed-breakout --output research/results/E003-confirmed-breakout-1m.json`

E000-E002 source versions are recorded using file hashes, with their base
commit and dirty flag. All archive and filter snapshot hashes are saved.
The official endpoint's filters exactly match the original PR10 fixed snapshot.
A failed early metadata request (HTTP451/HTML) generated no result and was
corrected; never interpret HTTP200 HTML as exchangeInfo.


## E003 result and E004 registration

E003 FAILS: 51 closes, net -124.764962, end 875.235038, PF .3092988266,
maxDD 12.771%, fees 55.688922. Lower absolute loss again comes with fewer
trades; expectancy and PF are worse. No promotion; no combination with E002.

E004 hypothesis: model costs consume too much of the small ATR stop/target
price distance. Keep original entry timing/votes/exits, but require initial
stop gap >=3 times modeled NORMAL round-trip fee+slippage per unit:
(entry + max(entry,stop)) * (.0005 + 3/10000). Frozen threshold 3, not a search.
Compare 1m execution to E001. This selects sufficient price movement; it does
not change stake/leverage or multiply losing positions. When stressing costs,
keep this normal-cost entry criterion frozen so selection is not changed.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy cost-floor --output research/results/E004-cost-floor-1m.json`
