# Termux seven-day live-data PAPER observation (opt-in, not financial acceptance)

This is an **independent virtual-money session** using the current consolidated strategy.
Only public Binance USD-M GET data are read; no wallet/mainnet orders or API keys.
Changes live solely on the research branch, not `main`.

## Android setup and safe isolation

Obtain Termux from a current maintained distribution. Open Termux:

```sh
pkg update -y
pkg install -y python git tmux
git clone --branch research/phase0-baseline --single-branch https://github.com/khaledhasneen1993/VORTEX-AI.git ~/vortex-termux-paper
cd ~/vortex-termux-paper
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m vortex.configure --equity 20
python -m research.paper_hour --help
```

Use a **new clone** rather than editing/reusing an old `.env` or stateful broker session.
If `~/vortex-termux-paper` already exists, inspect it; do not delete or overwrite
it blindly. Change the isolated directory for a fresh experiment.

The simulation bankroll is $20 virtual by example; change it in BOTH of the
`--starting-equity` arguments only if deliberately using a different *virtual*
bankroll. Small virtual bankrolls may be rejected by exchange minimum notional.

## Stay alive in Termux

Disable Android's battery optimization for Termux, ensure stable network and
power, then run:

```sh
termux-wake-lock
cd ~/vortex-termux-paper
. .venv/bin/activate
mkdir -p runs
tmux new -s vortex-paper
```

Inside the new tmux session, paste this **single, sequential command**:

```sh
python -m research.paper_hour --duration-seconds 1200 --starting-equity 20 --output "runs/smoke-$(date -u +%Y%m%dT%H%M%SZ)" && python -m research.paper_hour --duration-seconds 604800 --starting-equity 20 --output "runs/week-$(date -u +%Y%m%dT%H%M%SZ)"
```

The first 20-minute health check must complete with successful fresh market data
before the 7-day session starts. If preflight fails (HTTP 451, stale quotes,
missing candidates) the chain stops safely and writes `summary.json`; never
bypass depth/funding/quote guards. The seven-day session starts from a **fresh
virtual state** so the smoke session does not inflate its bankroll.

Detach using **Ctrl+B**, then **D**. Reattach using
`tmux attach -t vortex-paper`. Never start duplicate sessions against the
same state directory. To inspect the results from a *second Termux session*:

```sh
cd ~/vortex-termux-paper
ls -lt runs
find runs -name progress.json -print
find runs -name summary.json -print
find runs -name closed_trades.jsonl -print
```

At end, look for `runs/week-*/summary.json`, `session.log`,
`state/paper_state.json`, `state/closed_trades.jsonl` and
`state/partial_exits.jsonl`. A `summary.json` with
`completed_duration` confirms the supervisor timer reached its requested
duration with some successful polls; **it does not prove uninterrupted uptime
or a valid economic performance baseline**. Count actual successful polls,
cycle errors and the gaps in market observation before evaluating anything.

## Limits and safety

- Termux may be suspended/killed by Android; no seven-day uptime guarantee.
  This wrapper fails rather than resurrecting an old session or inventing ticks
  across a connectivity gap. Inspect/recover state deliberately after any failure.
- PAPER entries and exits are modeled against observed quotes, not real fills.
  Funding payments, liquidation and queue position are not fully simulated.
- `RUN_MODE=paper`, `USE_AI_MODEL=false`, `USE_CLAUDE=false` and no
  Telegram or signed/order endpoints are used by the bounded runner.
- Stale quote rejection, order journal, risk halts, funding/depth guards,
  position limits and original strategy parameters remain unchanged.
- A single market week, regardless of PnL, is not the missing verified
  historical 90-day economic baseline and is not approval to trade live.
