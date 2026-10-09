# Current strategy

The filenames retain their implementation-stage names, but this is the only
maintained strategy, not a selectable old/new pair. `vortex.strategy.analyze`
always routes to the completed-data weighted strategy in `phase1_strategy.py`.

Trend Following and Volume Breakout are primary. Reversion is auxiliary only when
5m/15m ADX indicates a range (<20 by default). Normal signals require agreeing
weighted votes with a primary strategy and 1H/15m/5m alignment. Exceptional strong
signals can qualify with fewer votes only under the stronger ADX, volume and candle
conditions. Opposing votes veto the selection.

All candles are completed at decision time. Past ATR percentile, configurable UTC
sessions, actual kline taker-buy volume/CVD and fresh paired OI/mark-price changes
filter signals. Missing/stale funding/OI abstains; missing required price/flow inputs
reject the candidate. Every rejection has diagnostic logging.

Settings use `PHASE1_*` names in `.env.example`. `PHASE1_ENABLED=false` is rejected
by runtime configuration; it cannot restore the deleted old voting implementation.
Individual filters/thresholds remain configurable. Strong-signal eligibility is
separate from the financially bounded size calculation.
