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
reduces base risk/positions/day-loss caps; `aggressive` retains the table above.
Detailed Telegram notices are optional and disabled by default. Public-data manual
cards remain available as a separate command; they send no Binance orders or account
protection guarantees. See [manual review](research/MANUAL_REVIEW.md).

## Documentation and verification

- [Strategy](docs/PHASE1_STRATEGY.md): current weighted signal rules.
- [Risk](docs/PHASE2_RISK.md): budgets, reserves, correlation and pyramiding.
- [Operations](docs/OPERATIONS_PROFILE.md): exits, execution gates, monitoring,
  historical observation requirements and offline stress/version comparisons.
- [Acceptance status](docs/ACCEPTANCE_STATUS.md): maintained software vs economic validation.
- [Archived evidence](archive/README.md): inert previous measurements, not executable versions.

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
