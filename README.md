# VORTEX-AI — adopted PAPER system

The default deployment is the user-adopted configuration tested at source
`d54ee349d470c97862059058ecefa8285c1a0083`. The default keeps that
configuration. An opt-in five-position basket layer ranks the same strategy
signals and changes group allocation, averaging and exits. Adoption and tests
are configuration decisions, not evidence of profitability.

Binance USDT-M **public market data, virtual PAPER balances only**. The supported
CLI cannot place exchange orders and needs no exchange API keys.

| Setting | Adopted value |
| --- | --- |
| Starting virtual wallet | 20 USDT |
| Primary candles | 5m; completed 15m / 1h confirmation |
| Radar | Up to 30 liquid movers, fast ranking |
| Net profit target | 4% of total posted position margin, costs included |
| Price stop | 10% adverse move from original entry |
| Adverse averaging | At most one add after 5% adverse move; caps still apply |
| Account loss floor | 25% from starting equity: 20 → 15 USDT |
| Positions / leverage / total margin | At most 5 / 5x / 25% |
| Flow / volume spike | Enabled, flow is an extra voter |
| Enhanced regime / liquidity sweep | Disabled |
| Recorder / health / quote recovery | Enabled |

A qualifying signal is not necessarily a fill. Minimum order size, liquidity,
funding, correlation, freshness, margin and risk caps can reject it. With 20 USDT,
all five position slots or an averaging add may be unavailable.

## Optional five-position baskets

Enable with `python -m vortex.configure --equity 20 --basket` for continuous
operation, or `bash run_paper.sh 10800 --basket` for a fresh three-hour test.
`BASKET_ENABLED=false` is the default. A bounded launch requires its own
`--basket` argument; configuring `.env` alone does not select the bounded profile.

| Basket rule | Behavior |
| --- | --- |
| Selection | Rank the current scan; open exactly five eligible signals together |
| Initial allocation | Each uses 10% of basket-start account equity as margin, rounded down by lot size; 5x |
| Collective target | Close every member at 3% net PnL / total posted basket margin, including add margin |
| Five-minute decision | If net loss, choose the strongest two freshly aligned members; one add each at half their initial margin |
| Deadline | Request closing all members after 15 minutes, even at a loss |
| Emergency protection | Original 10% price stop on any member requests whole-group closing; account floor remains 25% |

At 20 USDT, initial margins are about 2 USDT each (10 total), so the initial
collective target is about 0.30 USDT. Two successful adds of about 1 USDT each
raise the denominator to 12 and the target to 0.36. Leverage is counted once.
This profile explicitly replaces the legacy 25% total-margin ceiling with a
60% ceiling of **basket-start equity**, additionally capped by available capital.
Per-signal risk, portfolio stop risk, profit reserve and execution guards remain.
The current basket launcher also selects `BASKET_MIN_ENTRY_FILL_RATIO=0.90`: it
skips initial entries whose lot rounding allocates less than 90% of requested
margin and considers the next ranked signal. The flag defaults to zero (off).
Small-wallet minimum notional and risk limits can prevent additions or an entire
group. No partial five-position group is opened and no missing slot is refilled.

A deadline is a close request on the first available poll, not a guaranteed
execution timestamp. Missing quotes leave a persisted pending close until fresh
prices return. Four groups per hour is not guaranteed. See
[basket details](docs/BASKETS.md) for state, costs, ranking and limits.

## Termux / Linux

Stop the old PAPER process with Ctrl+C before updating. Existing sessions and
open positions are preserved; migration selects a **new virtual wallet**.

```bash
cd ~/VORTEX-20M
source .venv/bin/activate
git fetch origin main
git switch main
git pull --ff-only origin main
python -m pip install -e .
python -m vortex.configure --equity 20
bash run_paper.sh 10800
```

The bounded launcher applies the adopted defaults (or the explicit basket option), creates a unique
`runs/vortex-approved-*` directory, saves its path in
`runs/latest-paper-path.txt`, and records logs, effective configuration, Git
version, saved wallet, decisions, health and recorder manifests. It does not
close open positions at the timer with an invented price. Supported durations:
`1200`, `3600`, `10800` (default), `14400` (four hours), `21600` seconds.

Inspect or export the latest bounded session:

```bash
RUN_DIR="$(cat runs/latest-paper-path.txt)"
tail -n 80 "$RUN_DIR/session.log"
DATA_DIR="$RUN_DIR/state" python -m vortex.cli status
RESULT="$HOME/storage/downloads/VORTEX-paper-$(date -u +%Y%m%d-%H%M%S).zip"
python -m zipfile -c "$RESULT" "$RUN_DIR"
echo "$RESULT"
```

For continuous PAPER operation using `.env`:

```bash
python -m vortex.cli paper
```

Use `DATA_DIR` for the intended saved session when running `status` or
`dashboard`; never change its policies to bypass a halt. The bounded launcher
always starts a new wallet. `vortex.configure` preserves credentials without
printing them and does not delete or edit existing session files.

## Configuration and safety

[vortex/approved.py](vortex/approved.py) is the deployment-default source.
[.env.example](.env.example) documents the active configuration. Capture flags
retain their `PAPER_EXP_*` names for saved-state compatibility. Conservative and
legacy deployment profiles, manual-entry commands, model training and TESTNET
watchdog commands are removed from the supported CLI. Internal replay and
TESTNET protection helpers remain for safety regression tests; they are not
alternative deployed strategies. Git history remains available.

[Strategy](docs/STRATEGY.md), [risk](docs/RISK.md),
[operations](docs/OPERATIONS.md), [architecture](docs/ARCHITECTURE.md), and
[validation limits](docs/VALIDATION.md), and [basket profile](docs/BASKETS.md) describe this system.

```bash
python -m pip install -e '.[dev]'
python -m compileall -q vortex tests research
python -m ruff check --select E9,F63,F7,F82 vortex tests research
python -m pytest -q
```

No profitability, future win rate, uninterrupted operation, or live exchange
execution quality is established by a short PAPER session.
