# VORTEX-AI — adopted PAPER system

The default deployment is the user-adopted configuration tested at source
`d54ee349d470c97862059058ecefa8285c1a0083`. This release consolidates that
configuration and its commands; entry, sizing, averaging and exit algorithms are
unchanged. Adoption is a configuration decision, not evidence of profitability.

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

The bounded launcher applies the adopted defaults explicitly, creates a unique
`runs/vortex-approved-*` directory, saves its path in
`runs/latest-paper-path.txt`, and records logs, effective configuration, Git
version, saved wallet, decisions, health and recorder manifests. It does not
close open positions at the timer with an invented price. Supported durations:
`1200`, `3600`, `10800` (default), `21600` seconds.

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
[validation limits](docs/VALIDATION.md) describe this system.

```bash
python -m pip install -e '.[dev]'
python -m compileall -q vortex tests research
python -m ruff check --select E9,F63,F7,F82 vortex tests research
python -m pytest -q
```

No profitability, future win rate, uninterrupted operation, or live exchange
execution quality is established by a short PAPER session.
