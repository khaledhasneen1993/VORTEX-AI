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
