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

After five minutes, one decision may add to two strongest freshly aligned
members if group net is negative. Each addition requests half its initial
posted margin. Both adds are staged together; if either violates size, liquidity,
funding, correlation or risk, neither is committed. A 1-USDT margin is near a
5-USDT minimum notional at 5x; lot rounding commonly makes it untradeable.
A lost group is not permission to exceed the portfolio stop-risk budget.

At 15 minutes, remaining members enter persisted closing, even at a loss.
Account-floor, polling gaps, funding/liquidation exclusions and price freshness
limits above still apply. Neither the target nor the deadline guarantees profit,
execution speed or a hard loss ceiling. See [BASKETS](BASKETS.md).
