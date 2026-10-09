# Additional PAPER operations profile

Status: implementation and deterministic tests, **not economically accepted**.
This is a separate opt-in profile after Phase2; no production exchange execution
exists. Testnet single-entry commissioning explicitly refuses `OPS_ENABLED=true`
before credentials/network, because its existing exit controller does not implement
this portfolio policy. Existing legacy/Phase2 results remain reproducible when OPS
is disabled. No running Termux session or its settings are remotely changed.

## Entry and exits

- Break-even moves the stop to original entry at +0.8R, even before TP1. This is
  **price break-even**, not guaranteed net break-even after fees, gaps or slippage.
- TP1 sells 30% of original quantity at +1R; TP2 sells 30% at +1.5R; the remainder
  follows the existing ATR trailing mechanism after +2R. Lot rounding changes the
  exact fractions; stages never round up or flatten a runner accidentally.
- Default `OPS_TERMINAL_TARGET=false` removes the original final-target cap for
  the trailing runner. Original target is retained as signal/journal metadata.
- After 60 minutes, close a trade that has never reached +0.5R. Time uses original
  entry timestamp and observed peak. This is stagnation-based, not a universal
  maximum duration; a trade that previously moved strongly can remain open.
- Existing stop always wins ambiguous OHLC bars and gap fills are adverse. A newly
  tightened stop applies to later bars, never retroactively inside the same bar.
  Live PAPER exits use sampled executable quote side; there is no tick-perfect path.

## Data and costs

Large funding within five minutes blocks entry or pyramiding. `lastFundingRate`,
`nextFundingTime` and timestamp must come from a fresh public premium-index
observation; this is a timing heuristic, not a prediction of the final settlement
rate. Missing, stale or future observations reject entry. Beneficial as well as
adverse extreme funding is conservatively blocked. PAPER still does not settle
actual funding payments or simulate liquidation.

The existing spread cap remains in force. Both sides of a public depth snapshot
must contain at least 10,000 USDT within 20 bps of midpoint. Planned order notional
must not exceed 2% of the smaller side. Missing/old snapshots reject entries/adds;
protective exits are never postponed for unavailable liquidity. Public depth can
change before a fill; this gate does not guarantee fillability.

Adverse modeled slippage = base + completed ATR-percent term + half observed
spread + a latency penalty proportional to square-root assumed delay. The delay
(default 500ms) is a configurable assumption, **not measured execution latency**.
Slippage is capped before an explicit cost multiplier (default 1); stress can
multiply the entire model, not only its base. Sizing charges modeled costs against
risk. Gaps and sampled quotes can still exceed the modeled loss budget.

## Protection and monitoring

After two final losing trades: 30-minute global entry/add cooldown, then 60, 90,
and at most 120 minutes for more consecutive losses. Profitable final trades reset
the streak but do not cancel an already scheduled cooldown. Partial losses are not
counted as final trades. This opt-in rule supersedes the earlier no-streak-pause
policy only for OPS sessions.

A 12% decline from sampled peak within one hour, or 18% within two hours, latches
a new-entry/add halt. Open stops/exits continue; it does not submit an invented
liquidation or forcibly close every position. Timestamped samples, latch, cooldown
and warning day survive restart. Flat-only explicit `reset-paper-halt --ack-risk`
resets OPS protection; it does not reset wallet/reserved profits/daily loss floor.
Changing policy on a saved session is refused; use a new directory.

`decisions.jsonl` appends emitted rejection/skip diagnostics with timestamps and
full reasons. Several filter diagnostics can belong to one candidate; counts are
records, not unique trades. `entries.jsonl`, partial/final exit journals and
pyramids preserve actual simulated decisions and fees. Entry/exit event delivery
uses existing crash-recoverable pending-journal semantics.

`telemetry.json` atomically saves sampled equity after estimated exit fees,
unrealized PnL, wallet, margin, reserve, trading capital, daily loss and OPS state.
Run `python -m vortex.cli dashboard` to view localhost:8765. The read-only dashboard
refreshes every five seconds and shows the last exchange observation timestamp,
latest rejection reasons and risk state. An unchanged timestamp means a stopped
or stale feed; the page cannot observe the market itself.

Telegram entry, partial/final exit, pyramid and daily-loss warning notices are
optional (`OPS_TELEGRAM_ALERTS=true`) and require existing token/chat configuration.
Default is **false**. Daily warning begins at 75% of the daily-loss limit, at most
one warning attempt per UTC day. Delivery is best effort, not guaranteed; credentials
are never included in notices. Bounded `research.paper_hour` continues clearing
Telegram credentials to keep PAPER measurement sessions silent.

## Modes

`OPS_PROFILE=aggressive` retains configured Phase2 budgets/caps; it does not exceed
5x actual leverage or 25% aggregate margin. `conservative` additionally caps the
base risk parameter at 8%, positions at two and daily loss at 20%; strong-signal
budget still follows the Phase2 formula with that lower base. Other policy fields
are independently configurable. No signal criteria are weakened by the profile.

`OPS_FOCUS_SYMBOL=BTCUSDT` makes PAPER scan only BTCUSDT and disables Radar discovery;
empty value preserves the configured/Radar universe (24 candidates). It does not
change the historical dataset passed explicitly to replay or manual-card scanning.

All policy fields have matching `OPS_<FIELD>` entries in `.env.example`, including
exits, thresholds, liquidity, funding, modeled costs, protection and notifications.
`OPS_ENABLED=true` activates them; code defaults disabled for frozen baselines.
The example enables them for **new isolated PAPER sessions**. Existing `.env` wins;
copying the example over secret-bearing or active-session settings is unnecessary.

## Replay and stress

Both historical engines implement the same exit/protection policy. When funding
or depth guards are enabled, replay requires as-of `execution_observations`, keyed
by `(symbol, execution_timestamp_ms)`, containing `funding=(observed_ms, rate,
next_funding_ms)`, `bid`, `ask`, and `depth={T,bids,asks}`. Future settled funding
rates cannot be substituted. A completely absent observations collection is an
error, and missing individual observations reject that candidate.

The offline tool uses an explicitly supplied dataset JSON with `symbol`, `filters`
(step/min_qty/min_notional/tick), `small`, `higher`, `macro` (real Binance kline
arrays at 5m/15m/1h, including taker volume when available). It checks continuous
timestamps and hashes the input and source code. It does not download data.

```sh
python -m research.stress_operations --dataset /path/to/real-dataset.json \
  --version COMMIT_OR_VERSION --incomplete-execution-model \
  --output runs/stress-VERSION.json
# Compare a subsequent version on exactly the same source dataset:
python -m research.stress_operations --dataset /path/to/real-dataset.json \
  --version NEXT_VERSION --incomplete-execution-model \
  --compare runs/stress-VERSION.json --output runs/stress-NEXT_VERSION.json
```

`--incomplete-execution-model` explicitly disables unavailable funding/depth gates;
therefore this is **not a full-profile performance test**. Scenarios: baseline,
doubled fees/full modeled slippage, permanent -15% and +15% price gaps with higher
cost/delay, and slower assumed latency. Gap timestamp is the hourly-aligned window
containing the worst observed five-minute return after warm-up; all timeframes
receive the same level shift. This is deliberate retrospective stress selection,
not unseen validation. Reports include open-position status and reserve/PnL and
never overwrite an existing output. Comparisons reject different dataset hashes.
The one-symbol engine omits funding settlement and liquidation; use portfolio
replay with actual funding events/1m data for richer execution evidence.

No real-market OPS performance run has been claimed. Acceptance still requires
pre-registered independent validation of at least three months, PF >=1.2, >=100
validation trades, maximum drawdown <=20%, positive net with doubled costs, then
at least seven days forward PAPER. September/observed October remain development.
More aggressive budgets and more exits can increase costs, premature stop-outs
and drawdown. Technical tests and CI cannot establish edge or future profitability.
