# Current basket risk and units

| Policy | Value |
| --- | --- |
| Starting virtual wallet | 100 USDT by default |
| Each initial margin | 10% of marked group-start equity, rounded down |
| Positions / leverage | Two to five eligible members / maximum 5x |
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

At 100 USDT, initial total margin is about 20–50 depending on member count, fixed net target 0.20, and group
stop 10 (fifty target amounts). A smaller target alone does not establish an
improved edge. Initial margin/cap
leave about 10–40 USDT for adds before other constraints. No expected profitability
or successful averaging follows from these numbers. Funding cashflows and
liquidation are unmodeled; fee default is 0.0005, base slippage 3 bps.
