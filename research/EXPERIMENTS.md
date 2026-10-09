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

## E004 result — failed third entry hypothesis

36 closes, net -89.543420, end 910.456580, PF .5297654329,
maxDD 10.079%, fees 40.967759. Fewer trades and lower drawdown do not establish
an edge: net remains negative, PF <1, average net per trade is worse than E001.
Reject for promotion. Risk defaults remain unchanged. No candidate qualifies
for stress/independent validation or forward PAPER promotion yet.

E000 independently matches EVERY original trade record after removing added
diagnostics, and all 42 ZIP SHA256 values match the uploaded report. Original
risk, fee, gap, entry timing and quantity accounting are thus reproduced.

## Next-run handoff — E005 pre-registration (not executed)

Three actual entry hypotheses tested: E002 extension cap, E003 delayed
continuation, E004 cost viability; all failed. Do not repeat these.
E001 is an execution-resolution measurement, not an additional strategy trial.

Next diagnostic: invert the ORIGINAL accepted signal's direction while keeping
same ATR distances, staged exits, cost model and account caps. Entry remains
next-open. Recompute opposite stop/target symmetrically, keep a recorded source
direction and explicitly label inverted votes as contrarian research, not
original strategy votes. Do NOT combine E002/E003/E004. This isolates whether
the original directional vote has useful contrarian information. It is an
ablation on exposed development data, not a validated contrarian strategy.
If still negative, compare original signals with a full-size fixed 3R exit
(no partials/breakeven/trailing) as a separately preregistered exit ablation.
Keep main untouched; implement/test only on this branch and append full results.
Stop selecting September-only winners: any promising candidate then needs
independent periods, cost stress and forward PAPER before acceptance.

PR #11 is the ongoing research PR. First research CI run 37859064802 passed.
All 121 local tests passed after E004 registration. Latest result/code commits
may have their own CI pending; check Actions by exact remote HEAD.

## E005 — invert the original accepted direction

Status: preregistered above and now implemented exactly as specified. Use the
original accepted signal timestamp and next-open fill. LONG becomes SHORT and
SHORT becomes LONG. Preserve the original absolute ATR stop and target
distances, but mirror them around entry. Prefix recorded votes with
`contrarian:` and record source direction in features so results cannot be
mistaken for the original strategy. No E002/E003/E004 filters, no risk change.
Use the same 1m execution and cost model as E001. September remains exposed
development data; even a win here is only a hypothesis for independent tests.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy invert-direction --output research/results/E005-invert-direction-1m.json`

## E005 result and E006 registration

E005 FAILS: 106 closes, net -192.768772, end 807.231228, PF .4046116085,
maxDD 20.496%, fees 112.910445. Direction inversion is worse than E001 and
breaches the proposed 20% drawdown criterion. Reject; do not combine it with
other filters. This is evidence against a simple contrarian interpretation.

E006 exit ablation: restore original signals and next-open entries. Hold the
ENTIRE position until its unchanged 3R target (4.5 ATR target / 1.5 ATR stop)
or initial stop. Disable TP1, TP2, breakeven and ATR trailing only for this
explicit research exit policy. Use actual 1m execution; stop wins an ambiguous
minute. Risk sizing, leverage, margin, fee and slippage remain unchanged.
This tests whether staged exits monetize winners too early; it is not a new
entry hypothesis and September remains exposed development data.

Command: `python -m research.replay --month 2026-09 --execution 1m --exit-policy fixed-3r --output research/results/E006-fixed-3r-1m.json`

## E006 result and E007 registration

E006 FAILS: 94 closes, net -147.876015, end 852.123985, PF .6178096183,
maxDD 15.147%, fees 93.156863. PF improves over E001 but remains far below 1;
the entry stream is still negative after costs. Reject fixed-3R for promotion.

E007 changes the entry family instead of adding another breakout filter. Enter
with the aligned 1h EMA50/200 and 15m EMA9/21 trend only after a completed 5m
pullback and EMA9 reclaim: previous close on the pullback side of EMA9, current
close crosses back through EMA9 with directional body, EMA9 remains beyond
EMA21, 15m ADX >=25, relative volume >=0.8, RSI14 50..70 LONG or 30..50 SHORT.
Use completed candles only, enter next open, keep original 1.5 ATR stop, 4.5
ATR target, baseline staged exits and every account-risk parameter unchanged.
These common fixed thresholds are preregistered once; do not search alternatives
on September. September is exposed development data. If promising, freeze and
test other predeclared calendar months plus doubled costs before any promotion.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy trend-pullback --output research/results/E007-trend-pullback-1m.json`

## E007 result and E008 registration

E007 FAILS: 149 closed trades, realized net -243.245253, marked ending equity
754.634264 with XRP still open, PF .3979681511, maxDD 25.373%, fees 145.160869.
It is substantially worse and breaches the drawdown criterion. Reject this
entry family; do not tune its RSI/ADX/volume thresholds on September.

E008 return to ORIGINAL entry signals and test a full-size fixed +1R target
against the unchanged initial stop. Evidence motivating this one exit ablation:
in E001, the 45 positions that reached staged exits netted +142.7232, while 59
that never reached a partial exit lost -308.366. Close 100% at first +1R;
disable TP2, breakeven and trailing. Use real 1m ordering, stop-first ambiguity,
normal costs and unchanged risk/account settings. This deliberately changes
reward/risk and may fail after costs; threshold is frozen before the replay.

Command: `python -m research.replay --month 2026-09 --execution 1m --exit-policy fixed-1r --output research/results/E008-fixed-1r-1m.json`

## E008 result and E009 registration

E008 FAILS: 107 closes, net -195.069969, end 804.930031, PF .4114887621,
maxDD 20.199%, fees 114.779865. It is worse than staged baseline and breaches
the drawdown criterion. Reject; retain the baseline exit for subsequent work.

E009 tests whether the trend-pullback family failed because 5m decisions are
too noisy. Use completed 15m candles for pullback/reclaim decisions, completed
1h candles for both EMA9/21 higher trend and EMA50/200 macro regime, and actual
1m bars for exit execution. Preserve E007 thresholds exactly—no tuning after
its result—and restore baseline staged exits. Entry is next 15m open subject to
the same gap check. Risk/leverage/margin/cost settings stay frozen. September
remains exposed development data; a positive result must be frozen before any
other month is retrieved or inspected for this candidate.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --entry-policy trend-pullback --output research/results/E009-trend-pullback-15m.json`

## E009 result and E010 registration

E009 FAILS but is materially less negative: 69 closes, net -50.861325, end
949.138675, PF .8065317730, maxDD 8.075%, fees 65.318839. It still has no
positive expectancy and cannot advance. Do not tune its thresholds on September.

E010 is a timeframe control: run the ORIGINAL vote engine and staged exits on
15m decision candles, completed 1h history as higher and macro inputs, and 1m
exit execution. No entry filter, inversion or exit ablation. The original
strategy was designed around 5m/15m/1h semantics, so this is explicitly a
research comparison rather than a production-compatible claim; the ledger and
result identify the changed decision interval. Risk and costs remain frozen.
If negative, do not keep searching September thresholds or combinations.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --output research/results/E010-original-votes-15m.json`

## E010 result and next-run boundary

E010 FAILS: 40 closes, net -32.520502, end 967.479498, PF .8515335286,
maxDD 10.360%, fees 41.900710. It is the closest result so far but remains
negative after normal costs, has only 40 trades and does not qualify for cost
stress or independent validation. Do not combine failed September filters or
select symbols/sides based on these post-hoc splits.

Eight strategy/exit experiments have now been observed on September (E002-E010
excluding E001 measurement). Stop tuning trend/breakout parameters on this
month. Next hypothesis must be an orthogonal entry family registered before
execution: standalone range mean reversion in low-ADX conditions, rather than
requiring the contradictory trend vote. Use completed 5m reversal back inside
a 20-bar 2-standard-deviation band, 5m and 15m ADX below 20, RSI7 exhaustion,
actual completed 1m reversal confirmation, 1.5 ATR stop and 3 ATR target with
baseline staged exits. Specify exact RSI and volume gates before running.
September can only be development evidence. If promising, freeze all choices
and preregister three other calendar months before downloading their returns.

Current conclusion: neither the original nor any tested modification has a
demonstrated profitable edge. Main must remain unchanged and PR #11 stays draft.

## E011 — standalone low-ADX range mean reversion (pre-registered)

Registered before implementation or replay; September remains exposed
DEVELOPMENT data. Use completed 5m candles only for the setup. Define the band
from the 20 completed candles immediately BEFORE the setup candle: arithmetic
mean plus/minus 2 population standard deviations. The setup candle must close
strictly outside that frozen band. The next completed 5m decision candle must
close back inside the same band with a body in the reversal direction. Require
ADX14 <20 on both completed 5m and completed 15m histories, ATR14/close in the
existing sanity range 0.0008..0.045, RSI7 at the decision close <=40 LONG or
>=60 SHORT, and decision-candle volume divided by the preceding 20-candle mean
in the inclusive range 0.8..1.5. Require the existing completed-1m divergence
and StochRSI reversal confirmation at or before the decision close. No macro
trend vote is required; this is deliberately orthogonal to trend/breakout.

Enter at the next 5m open under the unchanged gap/slippage checks. Initial stop
is 1.5 ATR and target is 3 ATR from the decision close (2R); retain baseline
staged exits, sizing, 10% modeled risk budget, 5x leverage, 3-position/25%
margin caps and 50% daily breaker. No threshold search or symbol/side selection.
If net or PF is non-positive, reject without tuning this family on September.
If promising, freeze it before registering and downloading three other months.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy range-reversion --output research/results/E011-range-reversion-1m.json`

## E011 result and E012 registration

E011 is REJECTED for zero sample: 0 closed trades, no open positions, zero
fees/PnL and PF undefined. This is not evidence of profitability. Gate tracing
across all six symbols found 2,386 frozen-band reclaims, 466 also below both
ADX limits, 415 also inside the ATR sanity range, 169 also inside the frozen
volume range, and 59 also passing RSI7. The existing 1m divergence + StochRSI
confirmation accepted 0/59. Counts are descriptive diagnostics computed from
the same exposed month and cannot be used as validation evidence.

E012 is a single gate ablation to measure the range entry family rather than an
unobservably rare conjunction. Preserve E011's band, ADX, ATR, RSI7, volume,
stop/target, baseline exits, costs and all account-risk settings exactly. Remove
only the 1m divergence/StochRSI requirement; the completed 5m directional body
and frozen-band re-entry remain the reversal confirmation. Do not substitute or
tune another minute threshold after viewing September. This ablation was
registered before its replay. A positive September result would still require
the entire rule to be frozen and evaluated on independently registered months;
a non-positive result rejects the family without threshold tuning.

Command: `python -m research.replay --month 2026-09 --execution 1m --entry-policy range-reversion-ablation --output research/results/E012-range-reversion-ablation-1m.json`

## E012 result and next-run boundary

E012 FAILS: 48 closed trades, 17 winners (35.42%), realized net -105.493683,
PF .3509032175, maxDD 10.774%, fees 56.803722, cash 893.962735. One BTC
position remains open at the calendar boundary; marked equity is 892.756735
(open unrealized net -1.206001), so the open position does not rescue the
result. All six symbols are net negative. The closed stream is approximately
-48.69 even after adding fees back, while modeled slippage remains embedded;
cost alone therefore does not explain failure. Only 3 of 25 active trade days
are net positive. Reject the family; do not tune its band/ADX/RSI/volume limits
or select symbols/sides on this exposed month.

The next hypothesis must not retune trend pullback, original breakout, or range
reversion. Register before execution a volatility-compression expansion family
on 15m decisions, motivated by E010/E009's lower noise but avoiding their late
trend/pullback entries. Specify the compression window, expansion trigger and
volume rule exactly before replay. Keep actual 1m execution, baseline exits and
all financial risk settings frozen. September remains development-only.

Current conclusion remains: no tested version demonstrates a profitable edge;
main stays unchanged and PR #11 remains draft.
