# VORTEX-AI 0.2.0

Current maintained release: aggressive Binance USDT-M **PAPER/BACKTEST** engine.
There is one strategy implementation and one current risk/operations profile.
No production trading route, wallet connection or Binance production keys are used.
Profitability is **not guaranteed or economically validated**.

## Current behavior

Radar ranks up to **24** liquid moving contracts after each completed 5-minute
candle. Trend Following and Volume Breakout are primary; Mean Reversion is limited
to range regimes. Weighted votes use completed 1H/15m/5m data, session and ATR
percentile filters, observed taker flow/CVD, and fresh paired funding/OI/price data.
Missing or future observations never count as affirmative votes.

| Setting | Current default |
|---|---:|
| Base risk parameter | 12% |
| Normal signal modeled risk | 8–10% |
| Strong signal modeled risk | 12–15% |
| Actual leverage ceiling | 5x |
| Maximum open positions | 4 |
| Aggregate margin ceiling | 25% |
| Daily loss halt | 55% |
| Trailing ATR multiplier | 0.8 |
| Price break-even | +0.8R |
| Scale-out | 30% at +1R, 30% at +1.5R, remaining trailing |

Actual size is constrained by margin, exchange minimums, modeled stop costs,
reserved profits and exposure correlation; risk budget is not margin allocation.
Pyramiding only adds to a sufficiently profitable trade with bounded risk. No
averaging down or martingale. Progressive loss cooldown and 1h/2h drawdown latches
persist across restarts. Protective exits continue when new entries are halted.

Fresh funding timing, spread and near-price depth gates protect entry/adds.
Volatility/spread/assumed-latency slippage is modeled, not measured exchange fills.
PAPER does not settle actual funding or simulate liquidation. Price break-even
can still produce a net loss after costs or a gap.

## Install and configure (Termux)

```sh
cd ~/VORTEX-20M
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e .
python -m vortex.configure --equity 20
```

Configuration updates `.env` while preserving existing secrets and unrelated
options. It selects the current financial defaults and a fresh isolated PAPER
state directory; it never starts trading, resets an old wallet, or migrates open
positions. Without `--equity`, the existing virtual starting balance is retained.
Old session artifacts are left intact. Stop an older process before starting the
new release. Never paste API tokens into chat or commit `.env`.

```sh
termux-wake-lock
python -m research.paper_hour --duration-seconds 10800 --starting-equity 20 \
  --output runs/vortex-020-3h
# Alternatively run the unbounded PAPER engine:
python -m vortex.cli paper
# Read-only dashboard in another Termux session:
python -m vortex.cli dashboard
```

The bounded runner uses a new output directory, real public market data and
virtual money only. It sends no Telegram messages and retains open positions at
its timer cutoff. An existing output is never overwritten. Avoid running duplicate
sessions. Android battery restrictions may stop a background process.

`OPS_FOCUS_SYMBOL=BTCUSDT` overrides PAPER Radar. `OPS_PROFILE=conservative`
reduces base risk/positions/day-loss caps; `default` retains the table above.
`aggressive` is now an explicit opt-in preset described below.
Detailed Telegram notices are optional and disabled by default. Public-data manual
cards remain available as a separate command; they send no Binance orders or account
protection guarantees. See [manual review](research/MANUAL_REVIEW.md).

## Phase 1 aggressive toggles (opt-in)

With no profile selection, `OPS_PROFILE=default` retains the previous strategy,
risk bands, cooldowns, 24-candidate Radar and 20-second polling. `conservative`
keeps its lower account caps. An existing `.env` with `OPS_PROFILE=aggressive`
now explicitly selects the new preset: review it and use a **new state directory**.
Explicit settings override preset defaults; the commented values in `.env.example`
show the old defaults without preventing profile selection.

| Setting | Default / conservative preset | Aggressive preset |
|---|---|---|
| `STRICT_VOTES` | `true`: normal weight >=4 | `false`: normal weight >=3 |
| `ALLOW_SINGLE_STRONG_VOTE` | `false` | `true` |
| `MIN_STRONG_SCORE` | 7 | 6 |
| `PHASE2_AGGRESSIVE_STRONG_RISK` | `false` | `true` |
| `PHASE2_STRONG_MAX` | 0.15 | 0.18 |
| `OPS_SHORT_LOSS_COOLDOWN` | `false`: 30/60/90/120 min | `true`: 10/20/30/40 min |
| `RADAR_LIMIT` | 24 | 30 |
| `RADAR_FAST_RANKING` | `false`: full sort | `true`: bounded top-k selection |
| `LOOP_SECONDS` | 20 | 10 |

Normal entries still need two agreeing votes and a primary strategy. Relaxing
weight alone may not add entries when the existing votes already clear weight 4.
The old strong single-vote exception remains unchanged. The new optional path
requires one primary vote, no opposing vote, all existing data/MTF/session/ATR/CVD
gates, 15m ADX >=max(trend threshold, strong threshold minus 5), relative volume
>=strong volume plus 1, directional body/ATR >=strong body plus 0.2, and score
>=`MIN_STRONG_SCORE`. At default thresholds these are ADX >=25, volume >=4,
body/ATR >=0.8 and aggressive score >=6. Disabling `PHASE1_STRONG_ENABLED`
disables both strong entry exceptions.

Only strong-qualified signals receive the opt-in 12–18% modeled risk band;
normal signals retain 8–10% with existing lower account budgets respected.
The 5x leverage, 25% margin, per-entry margin, portfolio stop-risk and liquidity
caps can make actual size unchanged despite a larger modeled budget.
Loss-streak cooldown remains progressive and persisted; existing shorter values
are respected. Per-symbol 15-minute cooldown, drawdown/daily halts, flock,
journals, uncertain-write protection and stale-quote rejection stay in force.

Radar keeps the same 20M USDT turnover floor and deterministic ordering. Top-k
avoids sorting the entire eligible universe; no measured speedup is claimed.
10-second polling can reach a newly completed candle sooner, while ranking and
entry evaluation remain once per completed 5m candle. No intrabar entries, new
Order Flow/CVD, strategies, recorder, dependencies or mainnet execution were added.
Automatic Testnet strategy entry remains unavailable.

Run live public-market PAPER with virtual $20 on the Phase 1 branch (stop the
older process first; do not overwrite `.env`):

```sh
cd ~/VORTEX-20M
git fetch origin
git switch phase1/aggressive-opportunities
git pull --ff-only origin phase1/aggressive-opportunities
python -m pip install -e .
# Termux only, if available:
command -v termux-wake-lock >/dev/null && termux-wake-lock
RUN_MODE=paper STARTING_EQUITY=20 OPS_PROFILE=aggressive \
STRICT_VOTES=false ALLOW_SINGLE_STRONG_VOTE=true MIN_STRONG_SCORE=6 \
PHASE2_AGGRESSIVE_STRONG_RISK=true PHASE2_STRONG_MAX=0.18 \
OPS_SHORT_LOSS_COOLDOWN=true RADAR_LIMIT=30 RADAR_FAST_RANKING=true \
LOOP_SECONDS=10 USE_RADAR=true USE_WEBSOCKET=false OPS_FOCUS_SYMBOL= \
OPS_TELEGRAM_ALERTS=false \
DATA_DIR="data/vortex-phase1-$(date -u +%Y%m%d-%H%M%S)-$$" \
python -m vortex.cli paper
```

These overrides take precedence over old `.env` values. Other existing custom
thresholds and lower financial caps still apply. Later restarts must reuse the
chosen directory and identical policy to resume that session. To revert, select
`OPS_PROFILE=default`, unset the aggressive overrides and use a new directory;
existing positions/journals are never migrated or reset. No market performance
claim was made or validated by this phase.

## Documentation and verification

- [Strategy](docs/PHASE1_STRATEGY.md): current weighted signal rules.
- [Risk](docs/PHASE2_RISK.md): budgets, reserves, correlation and pyramiding.
- [Operations](docs/OPERATIONS_PROFILE.md): exits, execution gates, monitoring,
  historical observation requirements and offline stress/version comparisons.
- [Acceptance status](docs/ACCEPTANCE_STATUS.md): maintained software vs economic validation.
- Retired experiments are excluded from the maintained file tree; their history remains in previous Git commits.

```sh
python -m pytest -q
python -m compileall -q vortex tests research
ruff check --select E9,F63,F7,F82 vortex tests research
```

Testnet auditing/protection utilities remain restricted to Binance TESTNET.
Automatic Testnet strategy entry is **not implemented** for this release and returns
an explicit refusal; no old strategy can be selected to bypass that limitation.
A green CI validates software checks, not a profitable strategy. Independent
three-month validation and seven-day forward PAPER acceptance are still pending.
