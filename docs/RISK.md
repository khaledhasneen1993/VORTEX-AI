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
