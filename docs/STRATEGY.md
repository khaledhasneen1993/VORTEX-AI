# Adopted capture strategy

The production PAPER configuration is the effective configuration of source
`d54ee34` in the user's three-hour session on 2026-10-11. This adoption changes
configuration defaults and packaging, not signal calculations.

Completed 5m candles drive decisions with completed 15m and 1h history. Capture
uses the existing relaxed directional agreement and ATR percentile floor
`min(20, PHASE1_ATR_PERCENTILE_MIN)` (configured 40); absolute ATR limits and the
90-second signal freshness limit remain. Trend and volume breakout are primary
voters; mean reversion and funding fade keep their existing conditions.

`STRICT_VOTES=false`, `ALLOW_SINGLE_STRONG_VOTE=true`, `MIN_STRONG_SCORE=6` and
`MIN_SCORE=5` are adopted. Capture may accept a normal single vote under its
existing score rules; a score of 6 alone does not make a signal strong. Normal
and strong labels follow the existing vote/weight criteria.

Public-trade flow is enabled as an extra voter (`PHASE1_FLOW_MODE=voter`). Missing,
future, stale or insufficient prints abstain; they are not manufactured and do
not become a universal confirmation veto. The completed-candle taker-volume
proxy is distinct from full-trade CVD. Volume-spike breakout is enabled. Enhanced
regime filtering, liquidity sweep, funding-flow confirmation and session filtering
are disabled. Baseline range/trend conditions still apply to their voters.

Every decision logs reason codes. `ACCEPT` is a strategy decision; broker
`accepted=True` / an entry journal record is an actual simulated entry. Repeated
signals, cooldown, spread, liquidity, funding, minimum notional, correlation and
capital limits can prevent entries. Radar scans up to 30 movers using four
bounded workers; scan time can exceed the 10-second polling interval.

No Order Flow data is assumed complete. A sampled/truncated REST window cannot
establish full-session CVD or true order-book OFI. No new strategy or AI model is
introduced by this adoption.
