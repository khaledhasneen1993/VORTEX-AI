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
in-flight request finishes. Telegram delivery is opt-in as described below.

## Telegram manual cards (2026-10-09)

The operator configured their own private bot/chat and reported a successful
test message. Credentials stay in the phone's ignored `.env` with mode 600:
`VORTEX_TELEGRAM_TOKEN` and `VORTEX_TELEGRAM_CHAT_ID`. No credentials or personal
chat IDs are committed. Add `--telegram` to the manual command to send accepted,
unexpired cards. Default remains local cards only. No strategy or financial
parameter changes are made, and no Binance account/order integration is added.

Messages include direction, indicative entry/stop/target, votes, score, leverage,
expiry in UTC, and optional illustrative sizing. Unset amount stays unset.
Cards are still saved locally if delivery fails. Logs show sanitized delivery
status, never API URLs or tokens.

`DATA_DIR/manual_telegram.sqlite3` persists an atomic send-attempt claim keyed by
bot/chat hash, symbol, candle timestamp and direction, across output directories
and restarts sharing that DATA_DIR. An uncertain network response/crash is not
retried: at-most-once attempts avoid duplicates but can lose a notification.
Failure pauses subsequent delivery attempts for 60 seconds. Expired cards are
never intentionally submitted, but network/Telegram delays may deliver them
after expiry; review the timestamp on receipt. No delivery guarantee is made.

Stop the old watcher with Ctrl+C before updating. In Termux/tmux:

```sh
cd ~/VORTEX-20M
git pull --ff-only origin research/hourly-development
source .venv/bin/activate
termux-wake-lock
python -m vortex.manual_signals --telegram --duration-seconds 10800 --output runs/manual-telegram-$(date +%Y%m%d-%H%M%S)
```

Mocked tests cover expiry, missing credentials, message content and persistent
duplicate prevention after successful/uncertain sends. No hosted test sends a
real Telegram message or Binance order. This is delivery plumbing, not evidence
of trading profitability.
