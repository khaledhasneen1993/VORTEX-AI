# VORTEX AI — pre-simulation review candidate

VORTEX AI is a Python 3.11 Binance USD-M PERPETUAL **paper-first** breakout engine, with separate **TESTNET-ONLY** order commissioning tools. It is NOT certified for real-money trading and has not been shown profitable. The "AI" component is **untrained** until it passes genuine chronological holdout validation; there is no magical oracle.

## Available modules

| Capability | Current implementation |
| --- | --- |
| Market scanner | 5m breakout with 15m EMA trend, RSI, ADX, ATR, relative volume |
| Fast quote feed | Public WebSocket bid/ask with age rejection; optional USE_WEBSOCKET=true |
| Flow/depth filter | Public /depth + /aggTrades, no fabricated "whales"; optional USE_MICROSTRUCTURE=true |
| Risk | 1% stop-distance+fees sizing, at most 3 positions, max leverage 5x, margin cap, 5% daily cut-off and 5 consecutive loss halt |
| Paper exchange | Persistent ledger, adverse fills & fees, crash-recoverable close journal |
| Backtest | Single-symbol next-bar OHLC and multi-symbol synchronized portfolio replay (up to 45 days of retrieved candles) |
| Model pipeline | Optional chronological purged logistic ML training; NEVER enabled unless out-of-sample holdout improves Brier score |
| Exchange execution | Separate, manually armed **testnet-only** single-entry guard; rejects unmanaged positions, hedge and non-isolated margin |
| On-exchange protection | Binance /fapi/v1/algoOrder STOP_MARKET and TAKE_PROFIT_MARKET close-all, price + side verification, explicit protected state |
| Monitoring | Localhost-only read-only dashboard, Telegram alerts, testnet watchdog with explicit permission |
| CI | Python syntax, smoke CLI and tests under GitHub Actions |

## Install

```sh
git clone https://github.com/khaledhasneen1993/VORTEX-AI.git
cd VORTEX-AI
python -m pip install -e '.[dev]'
cp .env.example .env
python -m pytest -q
vortex status
```

Use the review branch while PR #2 is open:

```sh
git fetch origin feat/vortex-pre-simulation-hardening
git switch feat/vortex-pre-simulation-hardening
```

## Modes

Paper scanner: `vortex paper`. Single cycle: `vortex paper --once`. It DOES use real public market data and paper funds only.

Readonly status: `vortex status`. Local dashboard: `vortex dashboard --port 8765` (on the same machine, at 127.0.0.1:8765). Remote access: use an SSH tunnel, not a public port.

Single-symbol historical test (DO NOT use until selecting test inputs): `vortex backtest --symbol BTCUSDT --days 30`.

Multi-symbol portfolio test: `vortex portfolio-backtest --days 30`. No funding, funding settlement, liquidation, order-book replay or random fill claims. Does not prove future return.

**No tests of market performance or simulated live runs have been started in the development session for this revision.** The automated pytest suite uses fixtures and mocked HTTP data, not user funds, API orders or actual market trade simulation.

## TESTNET commissioning (important)

Keep `.env` out of Git. Supply **TESTNET**-issued credentials as local environment variables `VORTEX_TESTNET_KEY` and `VORTEX_TESTNET_SECRET`. The code contains no production signed trade endpoint.

1. With testnet credentials, `vortex testnet-doctor` performs read checks; no exchange writes.
2. For one deliberately selected commissioning order ONLY, set `VORTEX_TESTNET_ARM=TESTNET_ONLY`, then run `vortex testnet-once --symbol BTCUSDT --ack-testnet`. The same account must be in ONE-WAY / ISOLATED mode, otherwise it refuses. The order is sent only if a fresh eligible signal and risk budget pass. It is a real order **on testnet with fake funds**, and may not trigger immediately.
3. `vortex testnet-watch --ack-testnet` with the same TESTNET ARM variable is an ACTIVE guardian; if one of its protective algo orders disappears while a position exists, it **may send an emergency reduce-only testnet close** and latch a halt. Never confuse it with read-only doctor.
4. If a signed write times out, never retry the order ID; examine the exchange/account/position manually. STOP/TP orders are verified using Binance's dedicated Algo endpoints.
5. Commissioning is SINGLE-ENTRY. The local state record blocks repeated experiments until it is reviewed and reset intentionally outside the program. Never delete a failed journal to evade a safety halt. No production mode is provided.

The emergency close is best-effort, not a guarantee against gaps, API outages, mark-price dislocations or liquidation. Genuine Testnet integration/latency testing cannot occur without testnet keys and exchange access.

## ML training policy

`vortex train-ai --dataset /path/to/genuine_labeled_trades.jsonl` needs >=250 actual *closed*, timestamped labeled entry records with all features: `volume_ratio, rsi7, adx14, atr_pct, return3, is_long`. Each must also have `entry_ts`, `exit_ts`, and net-profit label `y` (0 or 1). Training uses chronological holdout and purges train samples whose outcomes overlap holdout entry; it only marks a model valid if held-out Brier is measurably better than a constant-rate baseline. No dataset/model exists in the repo. Only then should `USE_AI_MODEL=true` be considered. The ML score cannot affect margin, leverage, stops or risk gates.

## Operator protections

- NEVER paste or commit Binance/Telegram secrets to GitHub. Use exchange-restricted trade-only TESTNET credentials. The repo is PUBLIC.
- Production credentials and production signed order endpoints are deliberately unsupported. Exchange API keys must never have withdrawal permission.
- Discordant position/order state, uncertain responses, partial fills, failed stops and unrecognized account config require a stop and a human review.
- No doubling down, martingale, fake fill probability, auto increase in risk or performance guarantee.
- Monitor host clock skew, quotas, websocket freshness, process restarts, fee schedules and exchange-specific trading restrictions.

See [docs/REVIEW.md](docs/REVIEW.md) for the acceptance checklist. Acceptance of this PR means **code review readiness**, not testnet/production approval.
