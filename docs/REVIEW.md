# Current release review and open findings

Current deployment: 2–5-position smart PAPER baskets, default wallet 100 USDT.
No signed orders, real money or alternate strategy launcher. Repository cleanup
removes obsolete historical/signed/unused adapters; Git history and user session
archives remain evidence. The build verifies code contracts, not a trading edge.

## Retained fixes

Status is read-only; writes are durable and failures stop execution; quote completion
clocks remain accurate; one bounded bulk refresh may restore aged critical books;
recorder accepts 30 Radar + 5 held names; dashboard includes all risk halt sources.
Safety controls and current strategy/risk calculations are unchanged by adoption.

## Latest live evidence: one hour, 100 USDT, source 82540c4

Twenty entries across four groups; fifteen closed trades, five left open. Completed
group nets: +0.450359462, +0.048561881, +0.134062042 USDT. Sum +0.632983385; the
saved wallet 100.509465694 includes open-entry fees but excludes floating PnL.
Last complete marked equity 99.808873218 at 00:52:03 Jordan time, October 12.
It is not final equity: the following ~17 minutes lacked a complete fresh valuation.

Seventeen time-endpoint failures and eight missing WUSDT executable quotes blocked
cycles. Serial depth recovery can still age earlier quotes; the bulk refresh did
not eliminate it. Underlying network/rate-limit/service cause is not established
by these error messages alone. Recorder exceeded its stop budget and did not seal
its final segment. No additions executed: five decisions skipped; GRASS liquidity
was one explicit rejection, while other prefilter reasons lack detailed per-symbol
logging. The latest basket's stop/extra rounds cannot be validated during data gaps.

## Priorities

1. Improve and measure clock/critical-quote continuity without accepting stale prices.
2. Log all smart-add eligibility failures and make recorder shutdown/recovery evidence
   explicit; do not infer that every skipped decision was a capital rejection.
3. Revalidate the unchanged strategy with reconciled fresh valuations, then build a
   matching historical model with funding and honest missing depth/flow handling.

The new fixed net target is 0.20 USDT versus a 10-USDT group stop at 100.
Earlier session figures above describe the previous target/timed-exit policy. Averaging increases exposure
and caps may prevent adds. No profitability, guaranteed stop fill, full-session
flow completeness or liquidation realism has been demonstrated.

Current minimum is two eligible members, maximum five; no active-group refill.
Per-member margin remains 10%, fixed net group target 0.20 USDT and risk caps
are unchanged. Complete closing requests immediate new search; stale candles
and cooldowns still prohibit entries. Existing recorded sessions above predate
this minimum-size change and do not validate its performance.

The subsequent 10x opt-in changes notional and fee/stop exposure at the same
10%-equity initial margin. Risk budgets are retained; fewer entries/adds can
qualify. Prior 5x sessions do not validate the new leverage. Target remains
fixed 0.20 USDT net and session group stop remains 10% of starting balance.
