# Adopted PAPER risk and exits

| Policy | Active value |
| --- | --- |
| Starting wallet | 20 USDT virtual |
| Normal modeled stop risk | 8–10% |
| Strong modeled stop risk | 12–18% |
| Initial entry margin ceiling | 6.25% of deployable capital |
| Aggregate margin / leverage | 25% / 5x maximum |
| Portfolio stop-risk budget | 30%, including modeled costs |
| Positions | Maximum 5; capacity is not guaranteed |
| Positive closed-profit reserve | 50%, retained inside wallet |
| Daily loss / experiment account floor | 25% |
| Rolling drawdown halts | 12% in 1h, 18% in 2h |

Modeled signal risk is a sizing request. Actual size is bounded by leverage,
margin, stop exposure, order filters, reserve, correlation and liquidity. A
requested 18% does not mean every strong position risks 18% of the account.
The rolling drawdown controls can halt before the 25% account floor.

The adopted profit target is **4% net PnL divided by total posted margin**
(`PAPER_EXP_PROFIT_MARGIN=0.04`, allowed 0.03–0.05). Entry and exit fees and
simulated slippage are included; leverage is already reflected in margin and
must not be applied twice. It is neither 4% of wallet nor a 4% coin-price move.

The stop remains 10% adverse from the original coin-entry price (LONG down,
SHORT up). There are no staged profits, break-even, trailing, or stagnant exits
in this capture mode. At least 60 seconds after entry, a 5% adverse original-price
move permits at most one averaging add, no more than half the original quantity.
It must satisfy the existing guards and cannot move the original stop farther
away. With small wallets the add is often prevented by minimum size or caps.

The account floor uses marked equity including floating PnL and modeled exit
fees. A 20-USDT start reaches its 25% loss floor at 15 USDT. The halt is persisted;
closure requires fresh executable quotes. Missing quotes cannot justify an
invented liquidation price or guaranteed loss ceiling. Polling, gaps and slippage
can produce losses beyond a nominal threshold.

Original R is immutable `abs(original_entry - original_stop)`. Net R divides
cumulative net PnL by `original_quantity * original_R`; averaging and tightened
stops do not redefine it. Margin-return targets are a separate unit.

Funding-payment cashflows and exchange liquidation are not simulated. Fees are
0.0005 and slippage is 3 bps by default. Funding freshness/direction guards remain,
which is distinct from charging actual funding payments.

## Opt-in basket overrides

With `BASKET_ENABLED=true`, fixed initial margin is 10% of marked account equity
at group start per member (about 2 USDT each from 20), at 5x. The per-entry 6.25%
ceiling is replaced for this sizing path. The aggregate cap is explicitly 60%
of **group-start equity**, bounded also by current available deployable capital.
The launcher sets `MAX_MARGIN_FRACTION=0.60`; legacy mode remains capped at 25%.
Portfolio stop-risk 30%, normal/strong modeled risk, reserve, original trade-risk
caps and execution guards still bound acceptance. A refused fixed allocation
is skipped rather than silently reduced, except for downward lot rounding.

The group target replaces individual 4% exits: **3% of sum of posted margins**,
including successful add margins, using net PnL after entry/exit fees and modeled
slippage. Individual losing members can close in a profitable group. Positive
reserve and losing-streak accounting use the completed group's net outcome;
per-position PnL and original R remain separately recorded. Individual profit
exits and the legacy 5%-adverse averaging trigger are inactive in basket mode.
A member hitting its unchanged original price stop closes the whole group.

The explicit current basket preset enables smart loss adds from five minutes:
losers only, fresh side-aligned accepted signals, improved weighted entry, and
at least 0.5 entry ATR further adverse than the preceding add price. At least
five minutes between decisions, maximum three rounds, each request capped by
that member's initial margin. Successful eligible members commit together;
minimum order sizes and remaining capacity can prevent some or all additions.
Price winners remain untouched. See [BASKETS](BASKETS.md) for the exact guards.

The current preset has no 15-minute expiry. From ten minutes, strictly positive
group net after modeled costs closes all members without waiting for 3%.
At group net <= minus 10% of fixed session starting equity, close all members
(-2 USDT from 20). This group stop does not permanently halt the account. The
original member price stop and permanent account floor remain. Default-disabled
new flags preserve the old deadline and one half-margin pair add for old wallets.

Account-floor, polling gaps, funding/liquidation exclusions and freshness limits
above still apply. Neither targets nor nominal stops guarantee execution speed
or a hard loss ceiling. Missing quotes may leave a group partially closing.

The current basket launcher explicitly sets `BASKET_MIN_ENTRY_FILL_RATIO=0.90`.
Initial lot rounding below 90% of the requested margin rejects that candidate;
other eligible signals can replace it. Default zero retains old rounding.
Neither this filter nor the launcher rounds orders up beyond the requested
margin. Added orders still face their original lot/minimum and risk constraints.

From 20 USDT, five initial margins total approximately 10 USDT and the initial
3% target is approximately 0.30 USDT net. The fixed 2-USDT group stop is materially
larger; increasing it is not evidence of an improved edge. The 60% margin cap
leaves approximately 2 USDT for adds before other constraints, so exchange
minimum sizes can make adding to all losing members impossible. Targets and
caps evolve differently: targets include all posted add margins, the group loss
stop remains anchored to the original session balance.
