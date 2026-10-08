# VORTEX AI — Binance Futures aggressive *paper* engine

VORTEX AI v0.1 is an original Python 3.11 project built around the ideas of fast market surveillance, independent risk controls and honest testing. **It does not trade real money.** No exchange keys are needed. "AI" is a project name, **not** a claim of trained AI predicting prices.

## Current functionality

- Binance USD-M PERPETUAL public market data for up to six configurable USDT pairs.
- Deterministic 5m breakout + momentum / trend filter: EMA(9/21), RSI(7), ADX(14), ATR(14), relative volume, 15m EMA confirmation.
- Live quote spread filter, signal age limit, adverse-move rejection and per-symbol cooldown.
- Market-order-style paper fills at bid/ask plus configurable adverse slippage; taker fees on entry and exit.
- Risk-weighted position sizing; respects exchange MARKET_LOT_SIZE, step size, min quantity and MIN_NOTIONAL.
- Per-trade risk budget (default 1% of equity), 5x notional leverage **simulation**, 25% total margin allowance, max three positions; 5% daily loss breaker, four successive losses circuit breaker.
- Durable paper portfolio snapshots and JSONL journal of closed trades.
- Single-symbol OHLC backtest using next-bar open, conservative stop-first ties, fees and slippage.
- Tests in GitHub Actions and a nonroot Docker image.

**Important limitations:** NOT order-ready for real Binance trading; no API order signing, server-side STOP_MARKET orders, reconciliation or emergency liquidation. Paper stops depend on polling uptime and may slip. No user-data WebSocket, streaming depth, real liquidation tape, trained ML/Claude model, multi-symbol portfolio backtest, funding payments, or dashboard authentication. Actual return and win rate are **unknown** until tested. A GitHub repository does not host a bot 24/7.

## Quick start (Linux / Windows / Termux with Python 3.11+)

```sh
git clone https://github.com/khaledhasneen1993/VORTEX-AI.git
cd VORTEX-AI
python -m pip install -e .
cp .env.example .env
vortex status
vortex backtest --symbol BTCUSDT --bars 1200
vortex paper --once
vortex paper
```

If using Termux, install Python and git first. On Windows copy the example file with the File Explorer or PowerShell.

Change settings in `.env` BEFORE first paper run. **Never** upload `.env` to GitHub. Keys are unnecessary and ignored in v0.1. `RUN_MODE=live` deliberately fails.

## Run with Docker on a VPS

```sh
cp .env.example .env
docker compose up -d --build
docker compose logs -f vortex
```

A running, network-connected host is required. Keep the persistent `data` volume safe. On a local shell, `vortex status` reads `data/paper_state.json`; the journal is `data/closed_trades.jsonl`. Paper equity is separate from real Binance account equity.

## Strategy

- Entry candidate: last fully closed 5m bar breaks preceding 12-bar high/low, aligns with both EMA trends (5m, 15m), ADX >=18, relative volume >=1.15x, ATR volatility within bounds and RSI direction filter.
- Score >=5 for a candidate; upper-timeframe bars cannot contain future data.
- Stop = 1.5 ATR and target = 2.5 ATR relative to the signal. At fill, distances are preserved and adapted to actual simulated entry price.
- No martingale, no averaging into a loser, no leverage increase on losses.

## Risk and model accuracy

Risk is estimated using stop distance PLUS round-trip taker fee and slip budget. Real loss can exceed the budget on a gap, outage or liquidation. The 5x factor changes notional exposure but does not multiply profits for free. The risk circuit breaker *latches*; it requires an intentional process restart. After restarting, risk limits persist from state; do not delete the state to bypass a halt. Cooling rules and exchange filters are applied before every new paper trade.

Backtesting cannot prove future profitability and excludes funding, mark-price triggers, spreads from historical order books, gap liquidity, maintenance margin and liquidation. Report open positions separately from closed profits. Backtest is single-symbol; it is NOT valid as a multi-symbol portfolio return.

## Deployment and verification checklist

1. Confirm GitHub Actions compilation + all tests are green.
2. Test with a month of historical bars (paginated history is **not** yet supported; backtest limit is 1500 bars).
3. Run paper 24/7 on a real host with a persistent writable data volume and capture signal/exit timestamps for weeks.
4. Confirm ticker freshness, alerting, exchange connection failures, fee schedule, drawdowns and crash recovery.
5. Implement and independently test exchange-side exits, order reconciliation, position mode, liquidation checks and kill-switches on Binance **testnet**.
6. Only after successful testnet operation consider an explicitly enabled, separately reviewed production adapter.

## Attribution

This repository contains independently written code, informed by architecture ideas in previously reviewed Neko Futures Trader, Professional Quantitative Bot, Futures AI Bot and StrikeChart. No third-party source files are copied. Data provided by Binance public USD-M endpoints. All strategies are experimental.
