# Current strategy

The filenames retain their implementation-stage names, but this is the only
maintained strategy, not a selectable old/new pair. `vortex.strategy.analyze`
always routes to the completed-data weighted strategy in `phase1_strategy.py`.

Trend Following and Volume Breakout are primary. Reversion is auxiliary only when
5m/15m ADX indicates a range (<20 by default). Normal signals require agreeing
weighted votes with a primary strategy and 1H/15m/5m alignment. Exceptional strong
signals can qualify with fewer votes only under the stronger ADX, volume and candle
conditions. Opposing votes veto the strong single-vote exceptions; the existing normal path
uses its weighted majority and required agreeing-vote count.

All candles are completed at decision time. Past ATR percentile, configurable UTC
sessions, actual kline taker-buy volume/CVD and fresh paired OI/mark-price changes
filter signals. Missing/stale funding/OI abstains; missing required price/flow inputs
reject the candidate. Every rejection has diagnostic logging.

Settings use `PHASE1_*` names in `.env.example`. `PHASE1_ENABLED=false` is rejected
by runtime configuration; it cannot restore the deleted old voting implementation.
Individual filters/thresholds remain configurable. Strong-signal eligibility is
separate from the financially bounded size calculation.

## Phase 1 opt-in entry relaxation

`STRICT_VOTES=true` preserves the old normal-vote weight threshold. `false`
uses the lesser of the configured normal weight and 3, while keeping the normal
vote count (at least two), primary-strategy and MTF requirements.

`ALLOW_SINGLE_STRONG_VOTE=true` adds a separate clear-primary path: exactly one
agreeing primary vote, zero opposing votes, ADX15 >=max(trend ADX, strong ADX-5),
relative volume >=strong volume+1, directional candle body/ATR >=strong body+0.2,
weight >=min(strong weight,2) and score >=`MIN_STRONG_SCORE`. This path marks the
signal strong for sizing. The existing ADX30/volume3/body0.6 strong exception is
preserved even with the new flag off. Both require `PHASE1_STRONG_ENABLED=true`.
Freshness, missing-data rejection, sessions, ATR/CVD and all execution gates are
unchanged. Unprefixed vote/score variables override their `PHASE1_*` aliases.

`OPS_PROFILE=aggressive` supplies false/true/6 for these three settings when they
are absent. `default` and `conservative` supply true/false/7. Explicit overrides
win. The lower strong score also changes eligibility for strong sizing on existing
signals; it does not bypass quote, liquidity or portfolio limits.
