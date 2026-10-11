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
