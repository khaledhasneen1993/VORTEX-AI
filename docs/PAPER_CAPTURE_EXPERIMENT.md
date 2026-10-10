# PAPER capture experiment (disabled by default)

`PAPER_EXP_ENABLED=true` is restricted to PAPER live. BACKTEST refuses it because
there is no historical execution model for this experiment. All ordinary profiles
leave it off. Use a new session: full policy and initial bankroll are persisted.
No new dependencies, exchange orders, profitability claims or promised trade counts.

## Capture

With master + `PAPER_EXP_CAPTURE_ENABLED=true`, at least two completed 1h/15m/5m
EMA directions must agree; MACD agreement is no longer mandatory. ATR percentile
floor is min(configured floor,20). Real absolute ATR bounds, completed/gap-checked
history and signal freshness remain. Trend can vote with max(ADX5,ADX15)>=18 and
relative volume>=0.8. One aligned primary (Trend, Breakout or Volume Spike) suffices,
subject to MIN_SCORE. Ordinary strong classification is kept separate from normal
risk. Flow and kline-CVD are auxiliary votes/diagnostics, including opposing values,
and no longer veto a primary. Missing flow never becomes positive confirmation.
The launch script disables the existing UTC session-hours filter and uses 5-minute
per-symbol cooldown. Capture false retains ordinary entry rules.

## Exits and one adverse add

- `PAPER_EXP_PROFIT_MARGIN=0.04`: close ALL size at 4% cumulative modeled net PnL
  divided by **total posted margin**, including add margin. Allowed range 3–5%.
  Entry/add fees, exit fees and adverse slippage are included. Leverage is already
  represented by quantity/margin: do not multiply returns again. This is neither
  a 4% coin-price move nor 4% of notional. Staged, break-even, time-stagnation and
  trailing exits do not apply to experimental positions.
- `PAPER_EXP_STOP_PRICE=0.10`: LONG original executable entry minus 10%, SHORT
  plus 10%. The stop stays fixed after an add; original R remains immutable.
- `PAPER_EXP_AVERAGE_ENABLED=true`: one add only, at least 60s after opening,
  after an adverse original-entry move of `PAPER_EXP_AVERAGE_TRIGGER=0.05`.
  Size is **at most** `PAPER_EXP_AVERAGE_FRACTION=0.50` of original quantity.
  A crossed stop forbids adding. Weighted entry and combined fee/margin target
  are recomputed. Existing profitable pyramiding is not used in this mode.
  `pyramids.jsonl` stores the durable add with `add_type=adverse_average`.
- `PAPER_EXP_ACCOUNT_LOSS=0.25`: equity <=75% of INITIAL session bankroll latches
  full liquidation and prohibits entries/adds ($20 -> $15). Equity includes
  floating PnL and modeled exit fees. The latch is saved before closing and
  survives restarts/day changes; reset-halt cannot clear it. Fresh available
  positions close; missing prices wait for fresh observations. Polling gaps,
  slippage and fees can overshoot the floor. Never invent a flattening price.

Five positions are allowed only with master enabled. Lower configured limits and
conservative caps still apply. Existing leverage <=5x, total margin <=25%, per-entry
margin, stop-risk budgets, reserve, correlation, funding/depth/spread guards,
progressive cooldown and rolling drawdown latches remain. New activity may halt
before reaching $15. Fresh funding timing is re-fetched before experimental entry;
stale observations still reject it. Flock, journals and uncertain-write protection
are unchanged. PAPER does not settle funding payments or simulate liquidation.

**$20 limit:** default per-entry margin 6.25% permits at most $6.25 initial
notional at 5x; a half-size add is at most about $3.125. If minimum notional is $5,
the add cannot execute. Five $5 entries consume the whole $5 aggregate margin
budget before fee/loss effects. No rounding up or raised caps to force entries.
Averaging increases exposure and does not guarantee recovery.

## Run / revert

Stop older PAPER first. In activated `.venv`:

```sh
git pull --ff-only origin main
python -m pip install -e .
bash research/run_capture_paper.sh
```

This explicitly enables a new recorded three-hour $20 session with fast scanning,
five-position ceiling and the above defaults, without rewriting `.env`. Other
custom thresholds/lower caps remain. Count evaluations, accepted signals, entries
and unique candles separately. There is no guarantee of 400 signals or fills.
Inspect saved equity, entry/close/add journals, account latch and recorder gaps.
Revert using `PAPER_EXP_ENABLED=false` in a new isolated session. Never discard
old exposure or change the policy of a saved wallet to migrate positions.
