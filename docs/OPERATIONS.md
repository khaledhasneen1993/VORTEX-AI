# Operating the current PAPER basket system

Update main after stopping the old process, install with `python -m pip install
-e .`, then migrate using `python -m vortex.configure --equity 100`. Existing
sessions are preserved; do not overwrite or change policies on saved positions.
Every deployment launch uses the current 2–5-position smart basket strategy.
`--basket` is retained for command compatibility and is no longer required.

`bash run_paper.sh 3600` creates a fresh 100-USDT one-hour session. Durations:
1200 / 3600 / 10800 (default) / 14400 / 21600 seconds. Set STARTING_EQUITY explicitly
for another bankroll. `python -m vortex.cli paper` is continuous operation using
.env. On Termux keep wake lock and disable app battery restriction.

The latest path is in runs/latest-paper-path.txt. Read session.log, summary.json,
state/paper_state.json, telemetry.json, health.json and all group/member journals.
Status is read-only; it needs the saved session's starting balance and policies.
Dashboard binds loopback only. A displayed wallet excludes floating PnL; reserve
is already inside it. Marked equity has an observation timestamp: stale equity
must not be presented as end-of-session equity.

The strongest two to five eligible signals open together. Fewer than two
opens nothing; initial margin is at most 10% per member, reduced to fit risk. A total group net of at least
0.20 USDT requests closing every selected member immediately at a fresh poll, without a
ten-minute wait. After complete closing, search/ranking is requested immediately, even if that
candle was already scanned. An expired candle abstains;
candle freshness, symbol cooldowns and all execution guards remain.
The group loss threshold is fixed 10% of session starting balance. Original
member stops, account floor and risk guards remain. Smart round decisions begin
after five minutes; max three, >=five minutes apart. Adds require losing aligned
members, a new adverse price move and sufficient capacity. A skipped round is
not permission to widen limits or fabricate a fresh signal.

Missing held quotes freeze new entries; any latched closure remains CLOSING until
fresh prices permit all legs to exit. Original four-second quote and 15-second
execution-observation bounds remain. API time failures, late responses and stale
flow/OI must remain visible. One bounded extra bulk refresh may help serial quote
aging, but cannot guarantee service during an outage.

Any uncertain ledger write stops PAPER. Restart only the same saved policy under
flock after inspecting the state/journal. Manual halt reset requires acknowledgement
and zero positions; it does not reset wallet or bypass the permanent account floor.

Recorder failures fail soft. STOPPING_TIMEOUT means unsealed data needs recovery;
it does not establish clean recorder shutdown. The session timer stops observation
and saves remaining positions without invented liquidation prices. See VALIDATION
and REVIEW for gaps from the most recent one-hour 100-USDT session.

Current migration also selects `PAPER_10X_LEVERAGE=true`, `MAX_LEVERAGE=10`.
No engine starts during configure. The next new 100-USDT session requests about
at most 10-USDT initial margin per member, at most about 100-USDT notional. Normal risk/capital,
funding and liquidity guards still apply. Do not reuse or convert saved 5x wallets.


Migration now selects `BASKET_ADAPTIVE_ENTRY_SIZE=true`. Initial entries may use
less than the requested 10% margin; logs `BASKET_ENTRY_SIZE` and entry journals
show actual sizing. The 90% fill-ratio check applies only when this flag is false.
Exchange minimums and all execution guards remain. Adaptive sizing applies only
to new members, not to add budgets, and changing the flag on a saved wallet is
refused. Update/install/configure, then start a new isolated PAPER session.
