# Five-position PAPER basket contract

The current smart basket strategy is the deployment default. Configure a fresh
wallet with `python -m vortex.configure --equity 100` or use `run_paper.sh`.
No signed orders, mainnet, new voter or heavy dependency is introduced.

1. Rank current accepted Radar signals by score, strong label, vote weight,
   ADX and symbol. Open exactly five eligible distinct members together or none.
2. Request 10% of marked group-start account equity as each initial margin,
   rounded down by lot size, leverage capped at 5x. The initial fill-ratio filter
   is 0.90. Total margin remains capped at 60% of frozen group-start equity and
   current deployable capital; portfolio/per-trade stop risk remains unchanged.
3. On every fresh poll, estimate group net with executable bid/ask, modeled
   slippage and all entry/exit fees. Before ten minutes, close all members at
   3% of historically posted group margins, including adds. From ten minutes,
   **strictly positive** net requests closing all members, including losers.
   Zero or negative net does not itself trigger a timed close.
4. No 15-minute expiry in the current preset. At net <= minus 10% of fixed
   session starting equity, close all members: -2 USDT for a 20-USDT wallet.
   Original member-price stops and the account 25% floor also remain. The
   group loss stop does not permanently halt the account; cooldowns still apply.
5. Smart loss averaging starts at the first poll after five minutes, then
   at least five minutes between decisions, maximum three rounds. Each round
   considers all held losing members with fresh accepted side-aligned signals.
   Price winners are never modified, even if tiny gains do not cover fees.
   Additional executable entry must improve average entry and be at least
   0.5 **entry ATR** further adverse than the preceding add price (entry for
   the first add). No repeated additions at an unchanged quote or flipped signal.
6. Each request is capped by that member's fixed initial margin; no doubling.
   Reserve exchange minimum lots within remaining margin, then share remaining
   allocation among eligible members. If all minimum orders cannot fit, consider
   strongest signals first. Existing spread, price-runaway, correlation, funding,
   depth participation and original stop-risk caps can still reject an add.
   One rejected member does not cancel other successful members. All successful
   additions in a round commit through one atomic state/journal batch.

Preparation uses closed candles and current decision time; stale flow/OI
abstain. New rounds prepare fresh candles. The timer remains group-relative,
independent of Radar entry windows; missed freshness windows can yield a skip.
Exit checks run before additions and while collecting guard data. Any latched
close blocks all additions and new groups. Never refill a member's exited slot.

Round decisions persist before staging. A crash can skip a round, never replay
it as a new addition; pending journal batches replay idempotently. Group phases
ACTIVE → CLOSING → CLOSED persist across partial exits/restarts. Missing fresh
quotes can leave members pending and realized loss can exceed its nominal stop.
Original entry/stop R anchors remain fixed; average entry changes only on adds.

Active deployment flags:
- `BASKET_HOLD_UNTIL_TARGET`: true.
- `BASKET_LOSS_STARTING_EQUITY_FRACTION`: 0.10.
- `BASKET_ANY_PROFIT_AFTER_SECONDS`: 600.
- `BASKET_SMART_ADDS`: true.
- `BASKET_SMART_ADD_INTERVAL_SECONDS`: 300.
- `BASKET_SMART_ADD_MAX_ROUNDS`: 3.
- `BASKET_SMART_ADD_STEP_ATR`: 0.5.
- `BASKET_MIN_ENTRY_FILL_RATIO`: 0.90.

Saved-policy schemas retain historical deadline and add fields, but current
launches never select that policy. Old wallets remain unchanged as evidence;
changing policy requires a new isolated session. Retained `deadline_ms` is
ignored in current deployment. The loss limit is 10 USDT from a 100-USDT start.

Read `baskets.jsonl` and per-member journals together. Smart round decisions
record selected symbols, per-symbol skip codes, due time and delay. Group
outcomes drive reserve/streak accounting once; reserve is inside the wallet.
Funding payments and exchange liquidation remain unmodeled. The bounded session
timer still ends observation and saves any open positions without invented
closes. Neither averaging, frequency nor profitability is guaranteed.
