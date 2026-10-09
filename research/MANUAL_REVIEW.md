# Public-data cards for manual review

This independent command scans the current Radar candidates with the existing
consensus rules and corrected derivative clock. It never creates a PaperBroker,
connects to a private account, loads API keys, or calls an order endpoint. The
user makes every execution decision manually in Binance. Existing PAPER runs
and saved positions are not touched. No live execution switch is added.

Amount may be left unset; quantity and margin are then null. Later, illustrative
sizing requires an operator-supplied current equity and day-start equity;
committed margin and position count must also be accurate. Values are static
snapshots, not connected account monitoring. Multiple cards are independent
alternatives: their margins are NOT reserved, and they must not be added
together without a new account check. The command does not detect manual closes
or enforce actual account protection or cooldown. No live-account integration
has been claimed or implemented.

Prices are indicative calculations, not exchange-accepted orders; check current
quotes, expiry, price tick, active positions, account margin, protective orders,
and costs before any independent manual action. Funding payments and liquidation
are not simulated. Existing financial caps remain unchanged.

Termux (inside tmux):

```sh
cd ~/VORTEX-20M
git pull --ff-only
source .venv/bin/activate
termux-wake-lock
python -m vortex.manual_signals --duration-seconds 10800 --output runs/manual-signals-01
```

Leave the amount unset until the operator chooses it. A later session can use
`--equity AMOUNT --day-start-equity DAY_START --committed-margin IN_USE --positions COUNT`.
Do not overwrite old output directories. Cards append to cards.jsonl, logs to
session.log. Public network requests may exceed the timer briefly while an
in-flight request finishes. No alert delivery to third parties is performed.
