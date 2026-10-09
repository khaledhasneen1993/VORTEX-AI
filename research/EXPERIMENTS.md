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

## E013 — 15m volatility-compression expansion (pre-registered)

Registered before implementation or replay; September remains exposed
DEVELOPMENT data. Use completed 15m decision candles and actual 1m execution.
For each completed setup candle, compute relative Bollinger width as four
population standard deviations of its trailing 20 closes divided by their
mean. Define compression when the setup width is <= the 20th-smallest value
from exactly 100 preceding rolling 20-close widths (nearest-rank 20th
percentile); the setup value is excluded from its reference distribution.

The next completed 15m candle must close strictly above the highest high or
below the lowest low of the preceding 20 completed candles (including the
compressed setup), with a body in the breakout direction. Its true range must
be >=1.25 times ATR14 computed through the setup candle, and its volume must be
>=1.5 times the mean volume of those preceding 20 candles. ATR14/decision close
must remain in the existing 0.0008..0.045 sanity range. No EMA, ADX, RSI, macro
trend, symbol/side selection or minute confirmation is added.

Enter at the next 15m open under the unchanged gap/slippage check. Size stop
and target from decision-time ATR14 at 1.5 ATR and 4.5 ATR (3R), retaining the
baseline staged exit engine, normal modeled costs and every financial risk
setting. No threshold search on September. Positive development results must
be frozen before independent periods; non-positive or inadequate samples fail.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --entry-policy compression-expansion --output research/results/E013-compression-expansion-15m.json`

## E013 result and E014 registration

E013 FAILS after normal costs: 111 closed trades, 49 winners (44.14%), net
-67.142891, PF .7783680195, maxDD 9.564%, fees 106.511229, ending equity
932.857108 and no open positions. Adding fees back yields +39.368338 while
modeled slippage remains embedded, so the entry family has positive pre-fee
movement but insufficient net edge. BNB (+9.339947, PF 1.218) and XRP
(+11.096404, PF 1.204) are positive post-cost; BTC, DOGE, ETH and SOL are
negative. Do not select the two winners post hoc. Thirteen of 29 active days
are positive. Only 6 trades reach final target; 105 end at a stop, though 58
positions with staged exits net +231.477 versus -298.620 for 53 without any
partial. This argues against removing staged exits and points to entry economics.

E014 is one cost-viability ablation on the frozen E013 signal stream. Preserve
every compression, breakout, volume, true-range, ATR, stop/target and exit rule.
Reject only signals whose 1.5-ATR initial stop gap is less than three times the
normal modeled round-trip fee+slippage per unit, using the same frozen E004
formula: `(entry + max(entry, stop)) * (.0005 + 3/10000)`, multiplied by 3.
The gate remains based on normal costs even in any later cost stress. This is
not permission to tune the multiplier or select symbols after the result.
September is exposed development data; passing still requires independent
months, doubled costs and forward PAPER.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --entry-policy compression-expansion-cost --output research/results/E014-compression-expansion-cost-15m.json`

## E014 result and E015 pre-registration

E014 FAILS and is worse than E013: 76 closed trades, 38 winners (50%), net
-81.022327, PF .7578575017, maxDD 12.451%, fees 86.230419, ending equity
918.977673 and no open positions. The cost gate reduced turnover but did not
isolate positive expectancy. Four symbols remain negative; the one BTC trade
and positive ETH/XRP subsets are far too small and observed to justify symbol
selection. Fourteen of 27 active days are positive. Reject the gate and restore
the unfiltered E013 entry stream for the next exit hypothesis.

E015 is pre-registered before implementation or replay. Preserve E013 entries,
stops, targets, baseline staged exits and all costs/risk settings exactly. Add
one failed-breakout invalidation: while TP1 has not executed, if a completed
15m candle AFTER entry closes back at or inside the original broken channel
boundary (LONG close <= signal channel_high; SHORT close >= signal channel_low),
close the entire remaining position at the next 15m open with normal adverse
slippage and entry/exit fees. Stops and partial/target executions inside the
completed candle remain resolved first from actual 1m bars; only a surviving
position can invalidate at the following open. After TP1, never use this rule
and retain baseline exit management. No time limit, threshold tuning, cost
filter, or symbol/side selection. September remains exposed development data.

This directly tests whether failed expansion should be abandoned when its
structural premise is invalidated, rather than waiting for the full ATR stop.
It is not yet executed. Main remains unchanged and no candidate is promoted.

## E015 result and E016 registration

E015 FAILS severely: 118 closed trades, 33 winners (27.97%), net -176.418197,
PF .4637627060, maxDD 18.091%, fees 112.569058, ending equity 823.581803 and
no open positions. Fifty-four breakout-invalidation exits are all net losers
and total -202.444806; 60 later stop exits net -6.525824 and 4 final targets
net +32.552433. All six symbols are negative and only 7 of 29 active days are
positive. Earlier exits also free portfolio capacity and produce 7 additional
accepted trades versus E013, increasing turnover. Reject this exit policy; do
not tune its boundary or delay, and restore baseline exits.

E016 changes entry timing based on the observed immediate breakout failures.
Start from the exact E013 compression-expansion candidate, but do NOT enter at
the next open. Inspect exactly one subsequent completed 15m candle. LONG must
touch at or below the original channel_high with its low, then close strictly
above channel_high with a bullish body. SHORT must touch at or above the
original channel_low with its high, then close strictly below channel_low with
a bearish body. This is a one-bar retest-and-reclaim, not delayed optimization:
if that immediately subsequent candle fails, discard the setup permanently.

Use only histories available at each close. Recompute E013 on data ending at
the expansion candle and cut higher history to that timestamp. On a valid
retest, enter at the following 15m open, size a new 1.5-ATR stop and 4.5-ATR
target from ATR14 through the retest candle, and use baseline staged exits.
Preserve E013's compression, expansion, volume and true-range gates; no cost
filter, macro trend, symbol selection or threshold search. All risk/account
settings and normal costs remain frozen. September is development-only.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --entry-policy compression-retest --output research/results/E016-compression-retest-15m.json`

## E016 result and next-run boundary

E016 FAILS severely: 27 closed trades, 7 winners (25.93%), net -137.167120,
PF .1273937409, maxDD 14.092%, fees 29.340363, ending equity 862.832880
and no open positions. Twenty-six positions end at a stop for -147.986564;
only one reaches the final target for +10.819444. All six symbols are negative
and only 4 of 17 active days are positive. The smaller sample does not excuse
the strongly negative expectancy. Reject the retest entry without tuning.

E013-E016 have now measured direct expansion, a cost gate, failed-breakout
invalidation and one-bar retest. All are negative after costs; E015/E016 are
materially worse. Retire this family on exposed September. Do not combine its
best-looking symbols or days, adjust the percentile/volume/range thresholds,
or relabel E013's pre-fee movement as an edge.

The next hypothesis must be orthogonal and registered before implementation.
Investigate a cross-sectional, market-relative family that limits correlated
directional exposure by comparing the same timestamp across all six symbols,
rather than another per-symbol breakout/mean-reversion rule. Specify ranking
lookback, minimum dispersion, simultaneous long/short selection, and portfolio
conflict handling before replay. It must retain the frozen account risk limits,
actual 1m execution, costs, and development-only status of September. Main
remains unchanged; no current candidate qualifies for independent validation.

## E017 — 4h cross-sectional relative-strength pair (pre-registered)

Registered before implementation or replay; September remains exposed
DEVELOPMENT data. Use completed 15m candles and evaluate only at six fixed UTC
anchors per day, when the next bar opens at 00:00, 04:00, 08:00, 12:00, 16:00
or 20:00. For each of all six configured symbols, calculate the simple return
from the close exactly 16 completed 15m bars earlier to the just-completed
close. Rank returns ascending with symbol name as deterministic tie-breaker.
Require strongest minus weakest return >=2.00 percentage points.

Queue exactly two simultaneous signals for the next 15m open: LONG the single
strongest symbol and SHORT the single weakest. If any position or pending order
exists at the anchor, skip the whole rebalance; never stack or rotate an
existing pair. If either next-open gap check, exchange minimum, account gate or
sizing check fails, cancel BOTH legs. Divide the existing 25% aggregate margin
capacity equally, capping each new leg at 12.5% equity margin while preserving
the 5x leverage ceiling and 10% per-trade modeled risk ceiling. This allocation
does not change the configured caps. After entry, legs exit independently.

For each leg use its completed decision-timeframe ATR14: 1.5 ATR initial stop,
4.5 ATR target and baseline staged exits. Require ATR/price 0.0008..0.045 on
both legs. Use normal fees/slippage and actual 1m exits, stop-first on ambiguous
minutes. No EMA/ADX/volume filter, symbol exclusion, interim rebalance or pair
forced-close. No threshold/lookback search on September. Even a positive result
must be frozen before independent periods and doubled-cost stress.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --portfolio-policy relative-strength-pair --output research/results/E017-relative-strength-pair-15m.json`

## E017 result and E018 registration

E017 FAILS: 56 closed trades (28 atomic pair entries), 27 winners (48.21%),
net -65.681310, PF .6404020888, maxDD 7.129%, fees 33.987447, ending equity
934.318690 and no open positions. LONG legs net -18.721487 (PF .7994) and
SHORT legs net -46.959823 (PF .4742). Fifty-five trades end at a stop for
-80.874482 and one reaches the final target for +15.193172. BNB and SOL are
slightly positive but the observed subsets cannot be selected. Only 5 of 19
active days are positive. The pair structure reduces drawdown and fees but has
no positive post-cost expectancy.

E018 is the exact directional ablation of E017. Preserve six UTC anchors,
16-bar/4h returns, 2.00-point dispersion threshold, deterministic ranks,
atomic next-open execution, equal 12.5% margin caps, ATR sanity, 1.5/4.5 ATR
stop/target, staged exits, actual 1m execution and every account/cost setting.
Change only direction: LONG the weakest return and SHORT the strongest return.
Never select one side or symbol independently. This tests cross-sectional
reversal versus continuation; September remains exposed development data.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --portfolio-policy relative-strength-reversal --output research/results/E018-relative-strength-reversal-15m.json`

## E018 result and E019 registration

E018 FAILS, though it improves on E017: 56 closed trades, 26 winners (46.43%),
net -43.122906, PF .7489626279, maxDD 6.758%, fees 33.941083, ending equity
956.877094 and no open positions. LONG weakest legs net -15.193502 (PF .7992)
and SHORT strongest legs net -27.929405 (PF .7094). Fifty-five trades finish
at a stop and one at target. DOGE/ETH are positive observed subsets, but four
symbols and both sides are negative; no post-hoc symbol selection is allowed.
Ten of 21 active days are positive. Reject both directional variants as-is.

E019 keeps the exact E018 contrarian pair entry and tests alignment between
the 4h ranking horizon and holding horizon. Each surviving leg closes at the
open exactly 4 hours after its pair entry, with adverse slippage and fees.
Actual 1m stops, partials and targets during the preceding completed candles
remain authoritative and occur first; the scheduled exit sees only the new
4h-anchor open and cannot use later bar extremes. If a leg exits earlier, the
other leg remains managed until its own stop/target or the shared 4h horizon.
Do not rebalance while either leg is active. All E018 entry/risk/cost settings
stay frozen; no symbol/side selection or threshold change.

Command: `python -m research.replay --month 2026-09 --decision-interval 15m --execution 1m --portfolio-policy relative-strength-reversal --exit-policy pair-horizon --output research/results/E019-relative-strength-reversal-4h-exit.json`

## E019 result and research boundary

E019 FAILS: 60 closed trades, 22 winners (36.67%), net -86.665693,
PF .5269072028, maxDD 9.999%, fees 35.048065, ending equity 913.334307
and no open positions. Nineteen scheduled 4h exits net +34.908651, but 40
positions stopped before the horizon for -122.878116; one target nets +1.303772.
LONG and SHORT legs are both negative and only 4 of 20 active days are positive.
Do not remove/widen the protective stop based on this result: that would evade
the frozen risk premise rather than demonstrate an edge. Reject E019.

E017-E019 cover continuation, reversal, and horizon-aligned reversal for the
cross-sectional pair. All fail post-cost. September has now informed 18
strategy/exit trials (E002-E019; E001 was measurement), so it is exhausted for
strategy selection. No more September-driven threshold, direction, exit or
family changes are permitted. E018 remains merely the least-negative pair
variant, not a candidate and not eligible for symbol selection or promotion.

Next run must first implement a chronological multi-month walk-forward harness
and register development/validation calendar periods before downloading or
reading their strategy returns. New hypotheses must be selected on declared
development periods only; any viewed period is permanently marked exposed.
Validation still requires >=3 months, aggregate PF >=1.2, >=100 trades, DD
<=20%, positive normal and doubled costs, followed by >=7 days forward PAPER.
Main remains unchanged and PR #11 stays draft.

## W000 — chronological walk-forward registry

Registered before downloading or reading any strategy returns for the new
calendar periods. Development is 2026-01 through 2026-03. Locked validation is
2026-04 through 2026-06. July is a secondary locked period. August is explicitly
ineligible as a pristine holdout because its archives were already accessed as
September warmup. September remains exposed development and cannot select
another strategy. There is currently no candidate, so the harness refuses to
construct a validation command or read validation returns.

The replay now accepts a chronological comma-separated month range and runs it
as one continuous portfolio: wallet, open positions, daily breaker and equity
drawdown carry across month boundaries. Gaps, duplicates and reordered months
are rejected. This avoids understating drawdown by resetting equity monthly.

The registry freezes the existing acceptance gate unchanged: positive normal-
cost net over at least three validation months, aggregate PF >=1.2, at least 100
closed validation trades, maxDD <=20%, and positive net with fees/slippage at
2x. A candidate must be preregistered for development, then frozen with the
development-result SHA256 and exact research source hashes before validation
or cost stress can be constructed. Any source change after freeze relocks the
gate. Historical passage would still require at least seven forward PAPER days.

Registration command (no market download):
`python -m research.walk_forward --phase register --output research/results/W000-walk-forward-registry.json`

## W001 — preregistered 24h time-series momentum candidate

Registered before downloading or reading January-March returns. Hypothesis:
the cross-sectional pairs may neutralize a broad market move; independent
time-series momentum can retain it while still using fixed evaluation times.
This is a new development candidate, not a rescue or parameter search on the
failed September pair results.

On completed 15m candles, evaluate each symbol only for next opens at the six
fixed 4h UTC anchors. Compute the close-to-close return over exactly 96 bars
(24 hours). LONG when return >=+2.00%, SHORT when <=-2.00%; otherwise skip.
Require ATR14/price in 0.0008..0.045. Use a 1.5 ATR protective stop, 4.5 ATR
target, baseline partial/breakeven/trailing management, actual 1m execution and
a maximum holding horizon of exactly four hours. Stops/targets inside completed
minutes remain authoritative; ambiguity is stop-first. A surviving position
closes at the frozen horizon open with adverse slippage and fees.

No symbol selection, EMA/ADX/volume filter, threshold search or overlapping
position on the same symbol. Account settings remain 10% modeled stop budget,
5x leverage, at most three positions, 25% total margin and 50% daily breaker,
with no consecutive-loss stop. Run one continuous 2026-01..2026-03 development
replay. Do not access April-June validation unless W001 first passes development
and is frozen with its result and source hashes.

Development command:
`python -m research.walk_forward --phase development --output research/results/W001-development-normal.json`

## W001 result and W002 preregistration

W001 FAILS on its continuous January-March development set: 449 closed trades,
186 winners and 263 losses, net -479.895277, PF .6811707833, maxDD 52.661%,
closed-trade fees 336.369879, ending marked equity 521.989801 with ETH open.
All three months are negative: January -64.593397 (141 closes), February
-268.975254 (158), March -146.326626 (150). LONG nets -251.052453 and SHORT
-228.842824. Five of six symbols are negative; DOGE's observed +43.124111 must
not be selected after the fact. Only 32 of 87 active days are positive.

The failure exists before fees: adding closed-trade fees back leaves
-143.525398. Three hundred forty stop exits lose -833.831517, 23 targets gain
+293.801864 and 86 scheduled horizon exits gain +60.134376. The result SHA256
is `0b6bed390aa91b7efe394e05526a66d4b92aeb022fc23b35e7cc029a50bbf7d1`.
Reject W001; it is nowhere near the development gate and validation remains
locked. Do not select DOGE, widen the stop or tune the 2% threshold.

W002 changes one thing only: reverse W001's direction. At the identical anchor,
lookback and absolute 2% return threshold, LONG after a <=-2% return and SHORT
after a >=+2% return. Preserve every timing, ATR, stop, target, horizon, cost and
account parameter. Hypothesis: W001's 340 stops may mean the 24h move marks
short-horizon overextension rather than continuation. This exact ablation is
registered before running or reading W002 returns; it is not combined with
symbol selection or a looser protective stop.

Development command:
`python -m research.walk_forward --phase development --output research/results/W002-development-normal.json`

## W002 result and W003 preregistration

W002 FAILS on the same January-March development set: 452 closed trades,
191 winners, net -481.315027, PF .6191329097, maxDD 51.044%, total fees
300.102324 and marked equity 515.119584 with ETH open. It loses before closed-
trade fees (-181.536389). January, February and March are each negative
(-240.699657, -138.809026, -101.806344). Both sides and all six symbols are
negative. Three hundred twenty-three stops lose -892.865381; 116 horizon exits
gain +273.321583 and 13 targets gain +138.228771. Result SHA256:
`eead66f88a09c4529563f5ce597d0431fcc3356970fb7533d81135eb4eaf89f1`.
Direction reversal therefore does not repair this family. Validation remains
locked; do not tune direction, select a symbol or widen the stop.

W003 keeps W001's 24h direction and frozen 2% threshold but changes entry
timing based on the development evidence. On any completed 15m candle while
the 24h return remains >=+2%, LONG only when the preceding close was at/below
its completed EMA9 and the current bullish candle closes above its completed
EMA9. Mirror for SHORT at <=-2%. Enter next open. Keep 1.5/4.5 ATR levels,
baseline staged management, four-hour maximum horizon, actual 1m execution,
normal costs and every account constraint. No ADX, RSI, volume, symbol filter
or threshold search. This tests whether waiting for a pullback/reclaim avoids
the immediate stops seen in both fixed-anchor directions.

Development command:
`python -m research.walk_forward --phase development --output research/results/W003-development-normal.json`

## W003 result — reject the 24h momentum family

W003 FAILS: 737 closed trades, 291 winners, net -706.715624,
PF .6216706648, maxDD 72.804%, fees 391.334210 and ending marked equity
292.742112 with ETH open. It loses before closed-trade fees (-315.564593).
All three development months are negative: January -265.190282 (218 closes),
February -263.996948 (274), March -177.528394 (245). LONG loses -364.498453
and SHORT loses -342.217171. Five symbols are negative; ETH's observed
+86.871696 cannot be selected after the fact. Five hundred eighty stops lose
-988.948202, 129 horizon exits gain +106.487470 and 28 targets gain +175.745108.
Result SHA256 is
`19e2292e04b9ddfef889847bc9d2084314f1c2eea51ada3d4098a6d3b4f7f3a4`.

Reject W003 and the tested 24h-return family: fixed-anchor continuation,
fixed-anchor reversal and pullback/reclaim timing all lose before fees, in all
three months, with both sides negative. Do not tune the return threshold, select
ETH/DOGE or widen/remove the protective stop. January-March have now informed
three candidate trials (W001-W003) and remain exposed DEVELOPMENT only.
No candidate advances, so April-June validation and 2x-cost stress stay locked.
The next hypothesis must change the source of edge, not another direction or
timing tweak to this 24h-return family. Main and all financial caps remain
unchanged.

## W004 — preregistered high-volume liquidity-sweep reversal

Registered before W004 returns are generated. This changes the source of edge
after rejecting the 24h-return family. On completed 15m candles, form the prior
20-bar high/low excluding the current candle. A SHORT candidate must trade above
the prior high, close back below it, and have an upper wick at least 50% of its
full range. Mirror for LONG below the prior low. Require current volume >=1.5x
the prior 20-bar mean; reject candles sweeping both sides.

Place the structural stop 0.1 ATR beyond the sweep extreme. Require the entry-
to-stop distance to be 0.5..2.5 ATR and target 3R. Use baseline staged exits,
actual 1m ordering and stop-first ambiguity. Enter next 15m open under the
existing gap rule. ATR/price remains 0.0008..0.045. No trend filter, symbol
selection, time-of-day filter or threshold search. Risk remains 10% modeled
stop budget, 5x leverage, three positions, 25% total margin, 50% daily breaker
and no consecutive-loss halt. April-June validation remains locked.

Development command:
`python -m research.walk_forward --phase development --output research/results/W004-development-normal.json`

## W004 result and W005 preregistration

W004 FAILS: 592 closed trades, 202 winners, net -729.186614,
PF .4424074882, maxDD 73.374%, fees 344.231591 and ending equity 270.813386
with no open position. It loses -384.955023 before closed-trade fees. January,
February and March are all negative (-311.830534, -306.066701, -111.289379).
Both sides and every symbol lose. Five hundred fifty-six stops lose
-888.208284; 36 targets gain +159.021669. Result SHA256 is
`75c0e4b6c8bd6366b90f4bc33bbc760672d49883abe63f0f8d94ff3c013d396e`.
Reject W004 and keep validation locked.

W005 is an exact directional ablation registered before reading its returns.
Preserve W004's completed 20-bar sweep, close-back-inside requirement, 50% wick,
1.5x volume, ATR bounds, structural risk distance, 3R target, next-open timing,
1m execution, costs and account limits. Invert direction only: continue upward
after the high sweep and downward after the low sweep. Mirror the same frozen
entry-to-stop distance around entry, so risk sizing remains comparable. Do not
combine with filters or select symbols. This determines whether the event is
continuation rather than exhaustion; it does not tune W004 thresholds.

Development command:
`python -m research.walk_forward --phase development --output research/results/W005-development-normal.json`

## W005 result and W006 preregistration

W005 FAILS, though continuation is less bad than reversal: 584 closed trades,
229 winners, net -501.603771, PF .6437825054, maxDD 50.202%, fees 402.207329
and ending equity 498.396229. It loses -99.396442 before closed-trade fees.
January loses -364.099087, February gains +12.963014, March loses -150.467697.
Both sides and every symbol are negative overall. Five hundred thirty-one stops
lose -816.916886 and 53 targets gain +315.313116. Result SHA256 is
`df670d9994eb63c8a70148ff7eef12b781eb3a51bbff0541a01f166890e76262`.
It fails every development gate; validation stays locked.

W006 keeps the exact W005 entry stream, continuation direction, structural
stop distance and already frozen 3R target. Change exit management only: hold
the entire position to initial stop or full 3R target, disabling partial exits,
breakeven and trailing. Actual 1m stop-first execution and normal costs remain.
This isolates whether staged exits and their extra transactions consume a weak
continuation edge; it does not change entry thresholds or financial caps. Even
if improved, it must pass the full development gate before validation access.

Development command:
`python -m research.walk_forward --phase development --output research/results/W006-development-normal.json`
