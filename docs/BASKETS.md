# Five-position PAPER basket contract

Disabled by default (`BASKET_ENABLED=false`). Enable with `configure --basket`
for continuous operation or the explicit `run_paper.sh DURATION --basket`
option. The former writes `.env`; the latter starts an isolated fresh wallet.
No mainnet, signed orders, new voter, dependency or historical replay is added.

1. Read existing Radar/strategy data and rank current accepted signals: score,
   strong label, directional vote weight, 5m ADX, then symbol. Open exactly five
   eligible distinct symbols together or open none. Final guard checks can skip
   a higher-ranked signal; the next eligible one can take its place.
2. Freeze marked account equity at group opening. Request 10% of it as each
   position's posted margin at 5x, rounded down to exchange lots. At 20 USDT,
   this is approximately 2 each, 10 total. Group margin ceiling is 60% of this
   frozen equity, also bounded by currently deployable capital. This explicitly
   replaces only the legacy entry/aggregate margin limits in this opt-in path.
3. On each fresh poll, estimate net PnL using executable bid/ask, modeled
   slippage and all entry/exit fees. At 3% of total historically posted group
   margins, latch collective closing and close all members, even losing ones.
   Leverage is already represented in margin: do not multiply returns again.
4. At the first poll after five minutes, if group net is
   negative, choose its strongest two freshly accepted side-aligned members.
   Request half each member's actual initial margin once. Both additions commit
   together or neither commits. Added margin increases the target denominator.
   Closed-candle histories are prefetched before the timer and reevaluated at
   decision time; stale flow/OI abstain. The timer does not wait for the next
   Radar window. Original stop/entry R anchors stay fixed. A non-losing group or fewer
   than two eligible members produces one recorded skip. Missing quotes defer
   the decision; missing signal data is not a substitute for a current signal.
5. Current explicit `--basket` selects `BASKET_HOLD_UNTIL_TARGET=true` and
   `BASKET_LOSS_STARTING_EQUITY_FRACTION=0.05`: no 15-minute expiry. Hold until
   the margin target or protection. Net basket PnL at or below minus 5% of
   **session starting equity** requests closing every member: -1 USDT for a
   20-USDT session, even after wallet changes or adds. Net includes estimated
   entry/exit fees and slippage. This closes the group; it does not permanently
   halt the account or disable existing cooldowns. An original
   member-price stop or account floor can request closing earlier. Never refill
   a stopped/exited slot or overlap two groups. New groups require fresh
   signals, cooldown clearance and all safety guards.

The 60% allocation cap uses group-start equity so the half-margin request does
not shrink with each mark, while the original 30% portfolio stop-risk budget
continues to use deployable current capital. Per-trade risk cap, profit reserve,
funding timing, liquidity participation, spread, correlation, stale-book and
signal rejection all remain. A request is not a guaranteed fill or addition.
Near the 5-USDT minimum notional, rounding a 1-USDT margin add at 5x down often
prevents it; no rounding up or synthetic minimum-size exemption is used.

Group outcomes drive reserve and losing-streak accounting once at completion;
member-level closed PnL/R is still journaled. Summed member net PnL equals group
net PnL; reserve is inside wallet, not an extra profit. Funding cashflows and
exchange liquidation remain unmodeled.

Atomic state saves and pending journal batches protect virtual openings/adds.
The add decision is persisted before staging, so a crash can skip that attempt
but cannot repeat it. Closing is latched before the first member exit. A missing
quote can leave members pending after a close request; known fresh legs still close
and recovery continues until flat. Polling and price gaps mean neither deadlines
nor nominal stops guarantee exact execution or a maximum realized loss.

Watch `paper_state.json` / `telemetry.json` basket fields and `baskets.jsonl`:
`ACTIVE`, `CLOSING`, `CLOSED`; opening, added/skipped decision, final net outcome.
The single-writer lock, existing journals, recorder and health checks remain.
Basket persistence errors terminate PAPER to prevent further uncertain writes.
Four groups per hour and profitability have not been established.

The add journal records its scheduled `add_due_ms`, actual decision time and
`add_delay_ms`. Network delays or missing fresh data can still block an add;
preparation never extends the 90-second signal freshness limit.

`BASKET_MIN_ENTRY_FILL_RATIO` is an optional initial-allocation quality filter:
zero (default) preserves old downward lot rounding. The current `--basket`
configure/session commands explicitly set 0.90. An entry that cannot reach 90%
of its requested margin within the 10% cap is skipped and the next ranked
eligible signal is considered. If five qualifying symbols remain unavailable,
no partial group opens. It does not increase quantity or alter add minimums.
Entry journals record requested margin and actual allocation ratio. Old saved
baskets without the field retain the disabled policy; changing it needs a new
session.

These two new flags default to false/zero, preserving the old 15-minute
contract for unmodified policies. Holding without a deadline requires a
positive loss threshold. Old saved baskets restore their original policy;
changing policy requires a new isolated session. The retained `deadline_ms`
field is historical schema data and is ignored when holding is enabled; live
logs show `deadline_ms=disabled`. The session duration still stops the process;
open positions remain saved and are not automatically flattened at that time.
