# Operating the current PAPER basket system

Update main after stopping the old process, install with `python -m pip install
-e .`, then migrate using `python -m vortex.configure --equity 100`. Existing
sessions are preserved; do not overwrite or change policies on saved positions.
Every deployment launch uses the current five-position smart basket strategy.
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

Exactly five eligible signals open together. Before ten minutes the target is
3% of posted margins; after ten minutes strictly positive group net closes all.
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
