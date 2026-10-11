# Operating the adopted PAPER system

Use `bash run_paper.sh 10800` for three hours, or `21600` for six hours. The
launcher sets the adopted configuration before importing settings, chooses a
unique output directory and refuses to overwrite a session. `python -m
vortex.cli paper` runs continuously with the current `.env`.

On first migration, stop the current process, update `main`, install the package,
and run `python -m vortex.configure --equity 20`. This creates a fresh `DATA_DIR`
and updates the adopted flags. Saved wallets and open positions are not migrated
or deleted. Later, choose the saved session explicitly via `DATA_DIR` for status.
Changing policy on an existing saved wallet is rejected.

Keep Termux awake and connectivity available. The launcher requests
`termux-wake-lock` where installed. An Android process kill can still interrupt
execution. Ctrl+C requests graceful shutdown and recorder sealing; forced kills
are reported rather than disguised as a completed session.

Inspect `session.log`, `progress.json`, `summary.json`, `state/health.json`,
`state/paper_state.json`, decision/entry/closed-trade journals and the recorder
manifest. A fresh PAPER equity line is needed to value open positions; wallet
balance or old marks alone are not current equity. The timer does not flatten
positions at an unobserved price.

* `QUOTE_RECOVERED`: fresh public depth recovered a required held/candidate quote.
* `QUOTE_MISSING` / `Missing quote for open position`: reject new trades and adds;
  mark/manage only positions having executable fresh quotes.
* `FLOW_ABSTAIN_*`, `FUNDING_STALE`, stale OI: incomplete observations, not zeros.
* `Cycle failed closed`: degraded cycle. Repeated errors mean the session is not
  operating normally even if the process is alive.
* `SIGNAL ... accepted=False`: strategy qualified, broker guard refused entry.

Never widen freshness, delete journals, replace saved prices with mark prices,
or reset a halt to force activity. REST time failures and missing data can still
prevent position management. Recovery and health reporting do not guarantee
multi-hour uptime.

## Build history

The single Build & Test workflow checks compilation, dependencies, correctness,
tests and PAPER status. After a successful push build on `main`, its cleanup job
removes older completed workflow runs, keeping the current main build. It never
cancels running jobs, deletes newer runs, or edits source, Git history or local
PAPER sessions. Deleted build logs and attached Actions artifacts are permanent.
Set workflow `KEEP_LATEST_SUCCESSFUL_BUILD` to `false` to retain history. The
Actions-write token is confined to the main-push cleanup job; PR test jobs keep
read-only permissions. Cleanup errors are visible but do not change passing
project-test results.

## Basket testing

Stop the running process before an update. For the new opt-in group profile:

```bash
cd ~/VORTEX-20M
source .venv/bin/activate
git fetch origin main
git switch main
git pull --ff-only origin main
python -m pip install -e .
python -m vortex.configure --equity 20 --basket
bash run_paper.sh 10800 --basket
```

Use `14400 --basket` for four hours or `21600 --basket` for six hours. `run_paper.sh` deliberately uses its explicit
option rather than inheriting a stale `.env`. To restore legacy deployment, run
`python -m vortex.configure --equity 20` and omit `--basket` on bounded launches.
Both operations create new virtual sessions; old wallets are preserved.

For current basket-session status, pass the saved policy settings:

```bash
RUN_DIR="$(cat runs/latest-paper-path.txt)"
BASKET_ENABLED=true BASKET_MIN_ENTRY_FILL_RATIO=0.90 BASKET_HOLD_UNTIL_TARGET=true BASKET_LOSS_STARTING_EQUITY_FRACTION=0.05 MAX_MARGIN_FRACTION=0.60 DATA_DIR="$RUN_DIR/state" python -m vortex.cli status
```

Read `baskets.jsonl` alongside the per-position journals. Telemetry/dashboard
include group phase, total margins, estimated net, target, deadline and one-add
decision. `basket_needs_five_eligible` means no group was opened.
`basket_add_skipped` explains the one rejected add decision. `CLOSING` with a
held member means a fresh exit quote is still needed; no new group can open.
An uncertain persistence failure stops the basket engine rather than continuing
from possibly uncommitted memory. Resume only the same saved policy and path.

Basket execution observations are collected in parallel on the existing bounded
scan pool, with a maximum ten-second batch and funding refreshed after depth.
Their original exchange timestamps are rechecked at the final quote snapshot;
late responses are discarded. This removes the old sequential all-candidate
wait that expired early funding observations, without widening the 15-second
funding/depth guards or four-second book limit. Missing public observations can
still refuse a group or add.

Current `--basket` disables the 15-minute group expiry and requests collective
closing at net PnL <= -5% of fixed session starting equity (-1 USDT for 20),
or the unchanged +3% of group-margin target. All other protections remain.
`BASKET_STARTING_EQUITY_LOSS_STOP` identifies this close request in logs.
It persists across partial closes/restarts; no add is allowed at the threshold.
A fresh quote is required for each exit, so gaps can exceed the nominal loss.
The four-hour timer still ends observation and saves any open positions.
