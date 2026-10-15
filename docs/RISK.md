# Current basket risk and units

| Policy | Value |
| --- | --- |
| Starting virtual wallet | 100 USDT by default |
| Each initial margin | Up to 10% of marked group-start equity, risk-sized and rounded down |
| Positions / leverage | Two to five eligible members / 10x explicitly enabled for PAPER baskets |
| Aggregate margin | 60% of frozen group-start equity, also capped by current capital |
| Normal / strong modeled stop-risk requests | 8–10% / 12–18%; actual size remains capped |
| Portfolio original-stop risk | 30%, including modeled costs |
| Group loss close | 10% of fixed session starting balance: -10 USDT from 100 |
| Original member price stop | 10% adverse move; triggers whole-group closing |
| Daily loss / permanent session account floor | 25%; account floor 100 → 75 |
| Rolling drawdown halt | 12% in 1h / 18% in 2h |
| Positive group profit reserve | 50%, already inside wallet |

The profit trigger is a fixed **0.20 USDT net for the entire group**, checked
from its first fresh poll. It stays fixed after ten minutes and after adds.
Fees and simulated slippage are included; leverage is already reflected in margin.
No 15-minute expiry. Individual targets/legacy averaging fields are inactive.

Smart adds leave price winners untouched, require fresh aligned accepted signals
and improved average entry with another 0.5 entry ATR adverse move. At most three
rounds, at least five minutes apart, each request capped at initial member margin.
Exchange minimums, remaining cash/margin, liquidity/funding/correlation and original
trade/portfolio risk caps can prevent additions. See [BASKETS](BASKETS.md).

The group stop closes the group; it does not permanently halt the account. The
account floor is permanent for that session. All closes require fresh executable
bid/ask; polling, missing data and gaps can exceed nominal thresholds. No stop
level guarantees an executable price or maximum realized loss.

Original R is immutable abs(original entry - original stop); net R divides net
PnL by original quantity times original R. Adds do not redefine the R anchors.
Group margin-return targets use a separate unit. Reserve is not additional equity.

At 100 USDT, initial total margin is at most about 20–50 depending on member count, fixed net target 0.20, and group
stop 10 (fifty target amounts). A smaller target alone does not establish an
improved edge. Actual initial margins and the aggregate cap determine remaining add capacity. No expected profitability
or successful averaging follows from these numbers. Funding cashflows and
liquidation are unmodeled; fee default is 0.0005, base slippage 3 bps.

## Explicit 10x PAPER leverage
`PAPER_10X_LEVERAGE=true` with `MAX_LEVERAGE=10` enables a shared leverage
definition for initial sizes, fixed margins, minimum add budgets and added margins.
Disabled or nonbasket paths retain the original 5x cap. No signed execution exists.
A ~10-USDT margin now requests ~100 USDT notional. The original 10% price stop
therefore risks ~10 USDT before costs, which exceeds the 8–10% normal-signal
budget at 100 USDT in many cases. With `BASKET_ADAPTIVE_ENTRY_SIZE=true`, initial lots shrink to fit those budgets
instead of requiring the full requested allocation. False retains exact-margin
refusal. Neither the original trade cap nor the 30% portfolio stop-risk cap is raised.
Do not interpret the maximum of five as a guaranteed fill count. Existing group
stop remains -10 USDT at 100, target remains +0.20 USDT net. Entry margin remains
10% of group-start equity rather than an immutable dollar stake.


Adaptive sizing uses the existing risk calculator after executable entry and
modeled costs are known. The old 90% fill-ratio constraint does not veto these
smaller initial entries; exchange minimums, liquidity, spread, funding, freshness
and correlation still apply. Actual initial margin is persisted and limits adds.
A normal signal can therefore qualify below 10-USDT margin at 100 equity/10x;
five members or any particular fill frequency is not guaranteed. No stop is removed.


## Alternative 913
The table above describes 911. Explicit 913 replaces collective exits/member price
stops with independent +1%/-5% **net actual-margin** triggers at 10x. All capital,
trade/portfolio risk and account halt guards remain. Entry margin is up to 10% of
current equity and aggregate margin stays 60%; a maximum of 15 is not capacity to
fund fifteen 10-USDT stakes from 100. There are no adds. See STRATEGY_913.md.
