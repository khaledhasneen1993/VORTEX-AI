# Project review — 2026-10-11

Scope: current PAPER CLI/configuration, voters and market observations, basket
selection/exits/averaging, risk sizing, state/journals/flock, bounded scanners,
recorder, session launcher, monitoring and retained replay/TESTNET safety helpers.
No new strategy, risk threshold, signed order path or dependency was introduced.

## Corrected faults

- `status` no longer recovers journals or writes state. An active PAPER worker
  can be monitored without racing its ledger; pending recovery is reported.
- All PAPER paths stop on uncertain filesystem writes. State replacement and
  first journal creation now fsync the containing directory as well as the file.
- Nonbasket execution/health use the completed REST quote validation time.
  Unused ATR requests are skipped in capture mode; legacy ATR requests precede
  executable quote collection. Existing live resilience permits one extra bulk
  refresh when serial depth recovery leaves critical books stale; exchange
  timestamps and the four-second freshness bound remain mandatory.
- Recorder accepts thirty Radar names plus all five disjoint held names.
- Dashboard reports protection/account-floor halts as well as the daily gate.
- Legacy OHLC replay refuses current capture/basket configurations rather than
  reporting results from exits it does not implement.
- Risk/strategy/validation notes now describe the explicit current basket preset,
  retaining the distinction from old default-disabled policies and saved wallets.

## What the available live record establishes

The supplied four-hour session ran an earlier policy: 5% group loss stop,
no smart multi-round adds and no ten-minute any-profit exit. It recorded five
groups, four completed and five positions still open at observation end.
Three completed profitable groups earned 0.96617130 USDT combined; one losing
group lost 1.03963852 USDT. Closed net was -0.07346721 USDT and latest marked
account equity was approximately 19.89529 USDT. Reserve is already in wallet.
These are observed session figures, not expected future performance.

That record contained 34 missing-fresh-position-quote cycle failures and five
public time-endpoint failures. This review improves recovery but cannot guarantee
quotes during an outage. The recorded run does not validate the latest smart-add
and 10% stop policy; that policy requires its own new multi-hour PAPER record.

## Remaining limitations and priorities

1. Validate the latest exact commit in a new isolated PAPER session. Check all
   five entry margins, stop requests, ten-minute exits, and every successful or
   skipped smart round against group/member journals; retain open PnL at shutdown.
2. Measure quote gaps and exit delays on Termux. A bounded refresh cannot fix
   unavailable exchange data. Exits require fresh bid/ask and can overshoot stops.
   Metadata is cached for the process lifetime; intrarun filter changes remain
   a limitation. Recorder samples are partial snapshots, not a full depth/tick replay.
3. Add funding-payment and liquidation modeling before treating the simulator as
   complete cost validation. Funding guards/observations do not charge cashflows.

Risk structure still deserves scrutiny: initial 3% of ~10 USDT posted margin
is ~0.30 USDT, while the current fixed group stop is 2 USDT from a 20-USDT start.
After ten minutes the profitable-close amount can be smaller. One large loss
can erase several wins. Five market-aligned positions can share directional
exposure; all recorded entries were LONG. That alone is not a routing defect.

The initial ~50% allocation and aggregate 60% margin cap leave ~2 USDT before
fees/reserve/other caps. Five exchange-minimum add orders may not fit. The code
prioritizes eligible strong signals within limits rather than promising all adds.
Averaging reduces entry price but increases exposure; no success is guaranteed.

Supported deployment remains PAPER only. TESTNET helpers are retained for safety
fixtures with domain restrictions and explicit arming, not an active CLI route.
No mainnet execution exists. Current implementation is suitable for further
instrumented PAPER testing; a durable trading edge has not been established.
