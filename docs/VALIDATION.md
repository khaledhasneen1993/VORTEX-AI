# Validation and remaining limits

Adopted strategy source: `d54ee349d470c97862059058ecefa8285c1a0083`.
Deployment defaults were compared with the user's saved three-hour session
configuration, excluding its unique session path. Algorithms and risk controls
were retained. Current regression tests cover sizing, journals, locks, policy
binding, quote recovery/freshness, recorder integrity and time alignment. These
checks do not establish a trading edge.

Old deployment commands and phase-specific documentation were consolidated.
Git history and recorded sessions are retained. Low-level dataclass constructors
and replay/protection modules support historical safety fixtures; their legacy
fixture defaults are not `Settings.from_env()` deployment defaults and are not
selectable production profiles. The supported deployment is PAPER only.

Short sessions with profitable closed trades and remaining open losses cannot
establish a 100% win rate or expected profit. Floating PnL, latest mark timestamp,
fees, reserve and open exposure must be reported separately. Reserve is already
inside the wallet and must not be counted twice.

Remaining gaps: funding cashflows and liquidation are not simulated; REST data
can be missing, stale or truncated; exits are polled; account-floor closure needs
fresh quotes; correlation and minimum size can sharply restrict a 20-USDT wallet.

Next steps:
1. Run longer PAPER sessions and inspect health, recovery and recorder gaps.
2. Reconcile entries, closed PnL, open exposure and current equity from journals.
3. Build validation using recorded data with realistic costs and missing-data
   handling before considering any strategy change.

## Basket validation boundary

The new group behavior is opt-in and has synthetic regression checks for ranked
five-entry atomicity, margin units, net-after-cost targets, closing losing legs,
deadlines, price stops, account floors, missing quotes, one half-margin add pair,
rollback on second-add failure, journal replay and uncertain-write shutdown.
Legacy regressions remain. These checks prove behavior under their fixtures,
not live profitability, four groups per hour, or successful small-wallet adds.

Next basket checks: run a new PAPER session with `--basket`; reconcile
`baskets.jsonl` net outcomes with all member/add journals; review quote gaps,
loss-stop overshoot, ten-minute positive-net exits and smart-add refusals before
considering further loosening.

Follow-up basket regressions reproduce opening at a 74-second candle offset and
verify the group-relative five-minute decision without waiting for another Radar
window. They cover profitable/loss cases, bounded parallel guard collection,
original funding timestamps, stale/deadline rejection, optional coarse-lot
allocation filtering, old saved policy compatibility and the four-hour launcher.
The follow-up four-hour session exercised quote and guard timing fixes, but
preceded the current smart-add / 10% group-stop policy. It cannot validate the
newest policy. See [project review](REVIEW.md).

Current regressions also cover loser-only multi-round adds, price spacing,
strictly positive after-ten-minute net exits, original risk caps, read-only status
under an active writer lock, directory durability, fatal persistence errors in
both PAPER paths and quote completion clocks. Synthetic tests establish these
behaviors, not profitability or uninterrupted live quote availability.
