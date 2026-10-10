# Phase 2: optional transparent confirmations

All new feature switches default to **false**, including under
`OPS_PROFILE=aggressive`. Phase 1 still controls risk, cooldown and Radar presets.
There are no new dependencies, account endpoints or mainnet order routes. The
canonical strategy executes in PAPER/BACKTEST; existing TESTNET protection tools
stay restricted to TESTNET and automatic TESTNET entry remains unavailable.

## Public-trade flow

Enable `PHASE1_FLOW_ENABLED=true`. A single public aggTrades request reads a
15-second window for each candidate. Memory is bounded to at most 1000 aggregate
prints, with no cross-cycle cache or tick recorder. REST backoff stays in the
existing Market gateway. This can add API weight and scanning delay; use a small
Radar universe or a focus symbol on a constrained device.

- Window CVD in base units = sum(taker-buy quantity) minus sum(taker-sell quantity).
- Base imbalance = CVD / total base quantity.
- Taker aggression = signed buy/sell notional difference / total notional.
- Binance `m=false` identifies a buyer taker. One `order_flow` vote uses aligned
  signs of CVD and both normalized imbalances; these are not three independent votes.

CVD here is cumulative **within the sampled window**, not an all-session CVD.
Notional aggression is a simple executed-flow imbalance. It is **not** book-event
OFI: book updates, cancellations and queue changes are not measured. Neither
metric proves absorption, hidden orders, liquidation or actual fillability.

`PHASE1_FLOW_MODE=confirm` rejects valid opposing or neutral flow and permits
aligned flow. Missing, stale, future, malformed, gapped, low-count or potentially
truncated data abstains: the old signal can proceed, but is labeled unconfirmed.
Exactly a full page is treated as uncertain coverage, even if it might coincidentally
be complete. No pagination or kline-derived substitute is used. Freshness checks
both the requested window end and the newest observed print against decision time.
Default minimum is 20 **aggregate prints**, freshness 5000ms and imbalance 0.10.
Flow is measured at strategy decision time, not continuously at simulated fill time.

`PHASE1_FLOW_MODE=voter` instead adds one auxiliary vote (weight 1). It cannot
replace a primary strategy. Opposing flow can lower the weighted consensus and
veto strong single-vote exceptions; a normal majority may still qualify. Select
`confirm` to require alignment whenever a valid flow observation exists. Existing
kline CVD and execution freshness/liquidity gates remain independently enforced.

OHLC-only replay cannot reconstruct these prints. No live REST request is made
from a historical strategy call. Without an as-of `FlowObservation`, the new flow
layer abstains and records that limitation; this is not a validated flow-enabled
backtest. An explicit observation can be passed through `analyze(..., flow=...)`;
future or stale observations cannot add an affirmative vote.

## Completed-price regimes

Enable `PHASE1_REGIME_ENABLED=true`. The helper combines the existing completed
ATR percentile/ADX with 20-close Bollinger width and directional efficiency.
Width = 4 * population standard deviation / mean close. Efficiency = absolute
first-to-last displacement / sum of absolute close-to-close changes.

| Label | Default rule | Entry behavior |
|---|---|---|
| Dead | ATR percentile <20 AND width <0.004 | Reject new entry |
| Trend | ADX15 >=25, ADX5 >=18, efficiency >=0.35 | Keep primary trend/breakout; may bypass the optional ATR percentile floor |
| Range | Both ADXs <20, efficiency <0.35, not dead | Existing Mean Reversion may supply an auxiliary vote |
| Chop | Other valid combinations | Reject new entry |
| Unknown | Missing/invalid regime inputs | Reject new entry |

Dead-market classification takes precedence over trend. A clear trend bypasses
only the existing **relative ATR percentile floor**, not absolute ATR bounds,
closed-data validation, sessions, MTF/CVD or execution/risk protection.
Mean Reversion remains restricted to range. It does not gain standalone entry;
all paths still need a primary signal and macro alignment. This deliberately
retains the existing limitations on range opportunities and countertrend reversal.
Thresholds are configuration assumptions, not optimized performance evidence.

## Optional completed-candle voters

`PHASE1_VOLUME_SPIKE_ENABLED=true`: require a close beyond the previous swing
window, relative volume >=3, directional body >=0.6 ATR and a close in the outer
25% of the candle. ADX15/ADX5 must meet trend/breakout thresholds. If the existing
breakout also votes, the volume-spike vote **replaces** it rather than adding
another correlated vote. It is a primary breakout variant; normal consensus,
strong-signal and macro requirements still apply.

`PHASE1_LIQUIDITY_SWEEP_ENABLED=true`: require a wick beyond a prior 20-bar swing
by >0.1 ATR, a directional close reclaiming the swing by >0.1 ATR, relative volume
>=1.5 and a wick >=50% of the candle range. Sweeping both boundaries abstains.
It adds one auxiliary vote (weight 1), never standalone execution. A swing sweep
is a price-pattern label, not proof that a liquidity pool was consumed. When regime
filtering is enabled, dead/chop markets have already been rejected.

`PHASE1_FUNDING_FLOW_CONFIRM=true` requires `PHASE1_FLOW_ENABLED=true` and adds
observed flow alignment to the **existing** funding/OI extreme-fade vote. Funding,
OI, paired price change and all timestamp/interval requirements remain unchanged.
Unavailable/opposite/neutral flow removes only the funding vote, not a valid
primary signal. It never treats missing OI/funding as bullish or bearish.

## Decisions and saved sessions

The existing `decisions.jsonl` now includes accepted as well as rejected decisions,
with `code`, `flow` and `regime` fields. Strategy reasons include plugin/funding
codes when enabled. Not-evaluated and disabled labels are explicit; missing values
are never logged as a confirmed zero CVD. Candidate decisions and execution skips
can create multiple records; record counts are not trade counts. Entry/exit journals
keep selected votes and observed features. No Data Recorder was added.

New policy settings are bound to saved PAPER sessions. Changing them requires a
new state directory; old sessions with absent switches are interpreted as disabled.
Flock, journals, uncertain-write halts, stale quotes, exits, correlation, reserve,
portfolio stops, 5x actual leverage and 25% margin protections are unchanged.
Only the existing Phase 1 flags may change risk bands. This phase makes no market
performance claim; synthetic tests verify semantics and boundaries only.

## Enable or disable for live public-market PAPER

Follow the Phase 1 branch/install steps in README. Stop any older process first.
To enable the new layers explicitly, use a new virtual session:

```sh
RUN_MODE=paper STARTING_EQUITY=20 OPS_PROFILE=aggressive \
STRICT_VOTES=false ALLOW_SINGLE_STRONG_VOTE=true MIN_STRONG_SCORE=6 \
PHASE2_AGGRESSIVE_STRONG_RISK=true PHASE2_STRONG_MAX=0.18 \
OPS_SHORT_LOSS_COOLDOWN=true RADAR_LIMIT=30 RADAR_FAST_RANKING=true LOOP_SECONDS=10 \
PHASE1_FLOW_ENABLED=true PHASE1_FLOW_MODE=confirm \
PHASE1_REGIME_ENABLED=true PHASE1_VOLUME_SPIKE_ENABLED=true \
PHASE1_LIQUIDITY_SWEEP_ENABLED=true PHASE1_FUNDING_FLOW_CONFIRM=true \
USE_RADAR=true USE_WEBSOCKET=false OPS_FOCUS_SYMBOL= OPS_TELEGRAM_ALERTS=false \
DATA_DIR="data/vortex-phase2-$(date -u +%Y%m%d-%H%M%S)-$$" \
python -m vortex.cli paper
```

To turn off all Phase 2 layers explicitly, retaining the selected Phase 1 settings:

```sh
RUN_MODE=paper PHASE1_FLOW_ENABLED=false PHASE1_REGIME_ENABLED=false \
PHASE1_VOLUME_SPIKE_ENABLED=false PHASE1_LIQUIDITY_SWEEP_ENABLED=false \
PHASE1_FUNDING_FLOW_CONFIRM=false OPS_TELEGRAM_ALERTS=false \
DATA_DIR="data/vortex-phase2-off-$(date -u +%Y%m%d-%H%M%S)-$$" \
python -m vortex.cli paper
```

Environment overrides win over `.env`. For subsequent resume, reuse the original
directory and identical settings. The commands start PAPER only; no run or PnL
result is claimed by documenting them.

## Concepts and public sources

Minimal formulas were reimplemented locally; no external codebase was copied.
Sources consulted for public-trade side semantics and open-source delta concepts:

- [Binance USDT-M aggregate trades](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- [Freqtrade public-trade orderflow concepts](https://www.freqtrade.io/en/stable/advanced-orderflow/)

The implementation deliberately omits footprints, large raw-trade caches and ML
training to keep runtime and memory suitable for Termux and low-RAM Linux.
