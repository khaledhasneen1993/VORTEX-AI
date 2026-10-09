# Phase 2 — bounded aggressive PAPER portfolio risk

Implemented 2026-10-09 on research/hourly-development. Parent commit:
77fa463c02435de90b95bd5960bffce21cc46fcc. Main and every prior research result
are preserved. No production trading path, credentials or orders are added.
Economic edge and forward performance are NOT validated. Phases 3/4 not started.

## Activate a new isolated session

Existing .env is not overwritten. Supplied .env.example enables Phase1/Phase2
for NEW installations. For an existing session, stop it and use a new output
folder; never overwrite results or reinterpret an active legacy portfolio.

```dotenv
RUN_MODE=paper
TIMEFRAME=5m
PHASE1_ENABLED=true
PHASE2_ENABLED=true
RISK_PER_TRADE=0.12
MAX_POSITIONS=4
MAX_DAILY_LOSS=0.55
TRAILING_ATR_MULT=0.8
MAX_LEVERAGE=5
MAX_MARGIN_FRACTION=0.25
USE_RADAR=true
USE_WEBSOCKET=false
```

Settings.from_env supplies .12/4/.55/.8 defaults WHEN Phase2 is enabled and
those four keys are absent. Explicit .env values always win. Direct Settings()
and PHASE2_ENABLED=false preserve legacy defaults .10/3/.50/1.0 for frozen
research. Disabling Phase2 also requires returning financial caps to legacy
limits; .12/.55/4 with Phase2 disabled rejects startup. Both new phases require
5m base candles. Phase2-only legacy signals lacking strong_signal are NORMAL.

For the previously requested $20, three-hour, no-Telegram PAPER session:

```sh
python -m research.paper_hour --duration-seconds 10800 --starting-equity 20 --diagnostics --output runs/phase2-paper-$(date +%Y%m%d-%H%M%S)
```

This is a virtual portfolio. The wrapper suppresses Telegram and submits zero
exchange orders. It does not promise Android background survival. No session
was launched during implementation, and an already running phone process
retains its previously loaded code/settings until restarted.

## Dynamic risk (after costs)

RISK_PER_TRADE is the strong-signal BASE risk, not a promise of stake or margin.
Normal setup: linearly 8–10% of tradable capital as score rises from MIN_SCORE
(default5) to10. Strong setup: requires Phase1 strong_signal=1 and score at least
MIN_STRONG_SCORE (default7), then linearly12–15% over scores7–10. Below MIN_SCORE
is rejected outright. With default RISK_PER_TRADE=.12 the full stated bands
apply: normal8–10%, strong12–15%. Strong budget scales from the configured base
by (interpolated strong band / STRONG_MIN), then clips at STRONG_MAX (<=.15).
Normal clips at both its interpolated band and RISK_PER_TRADE. Lower operator
base values can reduce budgets below these bands; a higher base cannot exceed
NORMAL_MAX/STRONG_MAX. Selected monetary risk is captured per position.

Sizing includes entry/stop-side fees and adverse slippage, rounds quantity DOWN
and respects exchange minimums. Effective leverage stays <=5x. Aggregate margin
stays <=25% of tradable capital. A new per-entry margin cap defaults6.25%, so one
entry cannot consume all room for four positions. This limits actual modeled
stop risk below the headline ceiling in many setups. Portfolio remaining
nonnegative modeled stop exposure + conservative exit costs is capped at30% of
tradable capital; budget exhausted rejects new risk. Margin and risk checks
also apply to additions. MAX_POSITIONS is a maximum, not a guaranteed count.

Daily breaker uses full marked portfolio equity versus its historical/live UTC
day start, latches at55%, and remains latched across day changes until explicit
operator reset. It prohibits entries/additions, continues managing existing
stops, and cannot guarantee losses never exceed55% during gaps. Floating-point
threshold equality is handled conservatively. Loss-streak counts remain
observational only; no martingale, averaging down or automatic loss multiplier.

## Winner-only pyramiding

Defaults: trigger +2 ORIGINAL R, one addition, add <=25% of original quantity,
add-on stop-risk budget <=2% of current tradable capital. Configurable trigger
range1.5–3R, max additions1–3, each added quantity at most50% of original,
extra spacing .5R and minimum time five minutes between origin/additions.
Both original partial stages must already have executed. The position must
have a positive favorable mark, unchanged stop behind the add-on fill and
unchanged target still ahead. Existing stop is never widened or target moved.

Before adding, model combined net trade at the unchanged stop, including
realized stages, remaining entry fees, new entry fees, conservative exit fees
and adverse stop slippage. Negative combined net rejects. This is model-based
protection, NOT a guarantee under unmodeled gaps/liquidation. Original per-trade
risk ceiling, per-symbol margin share and total portfolio stop/margin limits
must still hold. No addition to a losing/unprotected trade or halted account.
Correlation veto also applies against OTHER symbols when adding.

PAPER: a fresh public executable quote plus completed candle confirming the
trigger; exits and daily-loss checks run first. Backtests: trigger confirmed
by preceding completed5m CLOSE; addition at NEXT open with adverse slippage.
Current high cannot justify an addition before it occurred. After adding,
weighted-average entry carries accurate PnL/fee accounting; immutable
anchor_entry/initial_risk keep R/trailing thresholds unchanged. TP stage flags
never reset. Total quantity and pyramid count are recorded. Orders/fills are
simulated; PAPER polling and OHLC intrabar limitations remain.

## Partial compounding

Default50% of every positive realized NET exit stage is retained for future
risk; the other50% is a persisted reserved_profit budget excluded from sizing.
No unrealized profit compounds. Tradable capital:
max(0, min(cash_wallet, liquidation-fee-adjusted marked_equity) - reserved_profit).
Negative realized stages never automatically release reserve. Existing
exposure can still reduce total wallet below reserve; reserve is bookkeeping,
not a bank withdrawal or guaranteed protected funds. Zero tradable capital
blocks new risk. Fractions0..1 are supported. Actual funding cash flows, where
provided to portfolio replay, are handled when observed, not fabricated.

Saved reserve, add count/anchor/cost basis and pending journal survive restart.
A policy change during state restoration rejects and requires a new isolated
session. Active legacy positions cannot be reclassified as Phase2 exposure.
New state has a policy fingerprint for risk/position/day-loss/trailing settings;
it is not a complete experiment/configuration identity. Full summary config
and source hashes remain the audit record. Saved pending add/exit journal is
flushed idempotently before subsequent state-changing actions.

## Correlation

60 aligned completed5m RETURNS (61 closes) -> Pearson. Exposure-adjusted rho
= raw_rho * candidate_side_sign * existing_side_sign. Reject >=.80, including
negatively correlated assets held on opposite sides. Positive correlation on
opposite sides is not rejected by this filter, but remains subject to ordinary
risk caps. Missing/future/stale/gapped/unaligned history or zero variance rejects;
no hard-coded BTC/ETH guess. Threshold/lookback/filter are configurable. This is
a backward-looking approximation, not proof of safe diversification.

PAPER fetches histories of open positions even if they leave the24-symbol
Radar. Portfolio backtests use only histories before entry/open; single-symbol
backtests have no other-symbol exposure to correlate against. Existing manual
cards do not manage portfolio state: Phase2 illustrative sizing with existing
positions/margin is rejected because correlation/reserve state is unavailable.

## Testnet boundary

Phase2 portfolio/addition/compounding execution is PAPER/BACKTEST ONLY.
The existing TESTNET runner is an explicitly armed one-entry commissioning
path; it has no full portfolio runtime/reconciliation for these features.
It now rejects Phase2 before credentials or exchange access. Legacy TESTNET
commissioning is preserved only with Phase2 disabled and valid legacy caps.
No automated multi-position Testnet implementation is claimed or hidden
fallback to production allowed. Actual exchange execution remains unverified.

## Configuration / files

Every RiskPolicy field has PHASE2_<UPPERCASE_FIELD> in .env.example:
ENABLED, NORMAL_MIN/MAX, STRONG_MIN/MAX, PORTFOLIO_STOP_RISK,
ENTRY_MARGIN_FRACTION, COMPOUNDING_FRACTION, PYRAMIDING, PYRAMID_TRIGGER_R,
PYRAMID_SPACING_R, PYRAMID_MAX_ADDS, PYRAMID_SIZE_FRACTION,
PYRAMID_RISK_FRACTION, PYRAMID_MIN_INTERVAL_MS, CORRELATION_FILTER,
CORRELATION_LOOKBACK, CORRELATION_MAX. Startup rejects nonfinite/unsafe values.

New: vortex/phase2.py, tests/test_phase2.py, docs/PHASE2_RISK.md.
Modified: vortex/config.py, models.py, risk.py, exits.py, paper.py, cli.py,
backtest.py, portfolio.py, testnet_runner.py, manual_signals.py,
research/paper_hour.py, .env.example, README.md, docs/ACCEPTANCE_STATUS.md,
docs/PHASE1_STRATEGY.md, research/EXPERIMENTS.md.

Verification:227 local pytest cases pass (30 additional Phase2 cases), compile
and fatal-code lint pass. Synthetic tests prove symmetric LONG/SHORT add
accounting, original R/stop/target preservation, bounded repeat spacing,
partial reserve persistence, append-failure recovery, four-position/margin and
55% equality latching, correlation/future/missing-data rejection, weak-signal
sizing refusal, all env keys, and next-open5m/actual-child1m replay accounting.
These test fixtures are NOT real-market performance or actual exchange fills.

## Risk / research acceptance

Risk12–15% and daily loss55% are highly aggressive. Four positions, repeated
additions and faster .8 ATR trailing can worsen fees, stop-outs and drawdown.
Small bankrolls ($20) often cannot satisfy minimum notional for additions or
some symbols; never round up to force a trade. Correlation changes over time.
Profitability is not guaranteed. No strategy adoption or economic gate passed.

P2 is one initial operator-requested policy variant, zero performance trials.
Existing exposed and locked periods remain as in research/EXPERIMENTS.md;
reconfirm exposure before research, preregister periods/costs and compare
same-source Phase1/Phase2 portfolios, trade count/symbol/day breakdown and
normal versus doubled fees/slippage. Do not label synthetic tests validation.
Keep >=3 independent months, PF>=1.2, >=100 trades, maxDD<=20%, net positive
under doubled costs plus >=7 days forward PAPER before calling it promising.
Phases3/4 require separate approval.
