# Aggressive PAPER live infrastructure

All infrastructure is opt-in. `OPS_PROFILE=aggressive` alone does not enable the
recorder, health output, resilience, or Phase 2 confirmations. No dependencies,
production order routes, account access or financial caps were added. Existing
TESTNET tools retain their restrictions; automatic TESTNET strategy entry is absent.

## Recorder

`RECORDER_ENABLED=true` starts one daemon worker with its own read-only Market
session and a separate POSIX flock at `DATA_DIR/recorder/recorder.lock`. It follows
Radar candidates plus open positions (bounded to 34 unique symbols), prioritizing
open positions in the next cycle. Each cycle snapshots the universe, exchange
filters, best bid/ask, up to 10 levels per side of REST depth, mark/funding timing,
open interest, and a bounded 15-second aggregate-trade flow summary. Sequential
requests are independent observations, not an atomic synchronized book. Every
response retains its exchange timestamp, post-request exchange clock and freshness
label; missing fields/requests become gap codes. Old readings never become fills.

| Flag | Default | Meaning |
|---|---:|---|
| `RECORDER_ENABLED` | false | Background worker, only from PAPER command |
| `RECORDER_DECISIONS` | false | Nonblocking structured decision queue, drained between requests |
| `RECORDER_INTERVAL_SECONDS` | 60 | Target cycle start cadence; 15..3600 |
| `RECORDER_ROTATE_BYTES` | 8388608 | Rotate before next append; bounded 64KiB..64MiB |
| `RECORDER_ROTATE_SECONDS` | 3600 | Rotate before next append; 60..86400 |
| `RECORDER_DEPTH_LEVELS` | 10 | Stored levels per side; 5..20 |
| `RECORDER_QUEUE_SIZE` | 64 | Maximum queued decisions; 1..1024 |
| `RECORDER_SHUTDOWN_SECONDS` | 15 | Bounded graceful stop wait; 1..25 |
| `RECORDER_FLOW` | true | Flow requests only when recorder master enabled |
| `HEALTH_ENABLED` | false | Best-effort progress/coverage snapshot and health logs |
| `LIVE_RESILIENCE` | false | PAPER REST/WS/scan improvements below |
| `WS_SILENCE_SECONDS` | 30 | Reconnect after no valid WS messages; 10..300 |
| `PAPER_FAST_SCAN` | false | Bounded parallel candidate preparation; new session required |
| `PAPER_SCAN_WORKERS` | 4 | Public HTTP preparation workers; 1..4 |

Data lives in append-only `*.jsonl.gz` segments. Each JSON line is a separate gzip
member with its own CRC, `seq`, local `recorded_ms`, and `kind` (resume, gap,
universe, market or decision). Rotation seals immutable segments in an append-only
`manifest.jsonl` with SHA256, complete-record count, last sequence/timestamp and
valid prefix length. SHA covers all bytes, including a retained damaged suffix.
File appends are flushed/fsynced; new segment directory entries are fsynced.

Startup verifies sealed hashes and recovers unsealed segments by streaming complete
CRC-checked members. It retains torn data/manifest tails, seals the recovered
prefix with explicit integrity status, records `RESTART_GAP`, and creates a new
segment. It never appends into or truncates a prior segment. Hash mismatch/missing
sealed data stops the recorder. A write of uncertain outcome is not retried in the
same worker; recovery requires restart. Manifest recovery remains conservative:
verification reports retained malformed lines and torn suffixes.

`SAMPLING_OVERRUN` records delayed starts; `DECISION_QUEUE_OVERFLOW` records dropped
queue entries. Sampling exceptions become per-field gaps. Disk/lock/manifest or
worker failures set `RECORDER_FAILED`, keep PAPER running, and appear in recorder
health. It does not retry unknown writes or modify execution journals. A duplicate
worker cannot replace an active worker's health file. Shutdown waits up to `RECORDER_SHUTDOWN_SECONDS` (15 by default) for network
work and final queue drain. A timeout reports `STOPPING_TIMEOUT` rather than
pretending data was sealed; interrupted unsealed segments recover on restart.

Verify stopped recordings (read-only, no market requests):

```sh
python -m vortex.recorder "$SESSION/recorder"
```

`pending` identifies unsealed segments, including a running worker's current file.
An integrity error exits nonzero. A torn segment cannot be treated as complete
historical evidence. Rotation is not retention: files accumulate until the operator
archives them; disk exhaustion stops recording rather than PAPER.

## Original R and financial policy

`vortex/r_units.py` supplies the shared definition:

- Signal price R = absolute signal entry minus initial stop.
- Executable entry preserves this initial distance and stores it as `initial_risk`.
- Price thresholds use immutable `anchor_entry` and original distance. Weighted
  cost entry, break-even stops, ATR trailing and pyramids never redefine R.
- Reported net R = cumulative realized net PnL / (original quantity * initial R).
  Partial PAPER rows use cumulative net R even though `stage_net_pnl` is stage-only.
  Final rows in all engines use cumulative trade net. Fees, modeled slippage and
  actual modeled funding events affect net, not the denominator. Pyramids contribute
  net while the original exposure remains the reporting denominator.
- Missing original exposure in legacy reports yields null R; no invented quantity.
  Legacy exit metadata retains the existing original-stop fallback where available.

This is a shared-definition refactor, not a new exit policy or selectable R model.
No flag selects conflicting R definitions. Risk caps are still Phase 1/2 policy:

| Preset | Normal modeled band | Strong modeled band | Base parameter | Positions | Day-loss halt |
|---|---|---|---|---:|---:|
| default | 8–10% | 12–15% | 12% | 4 | 55% |
| aggressive | 8–10% | 12–18% | 12% | 4 | 55% |
| conservative | capped at 8% | 8–10% at 8% base | <=8% | <=2 | <=20% |

Bands are interpolated signal budgets before execution sizing. Normal risk is
capped by `RISK_PER_TRADE`; strong risk scales its band by base / 12% and remains
capped by the configured strong maximum. Thus conservative base 8% gives 8–10%
strong risk with the default 15% maximum; it is not an 8% strong-risk ceiling.
All presets retain actual leverage <=5x, aggregate margin <=25%, per-entry margin
<=6.25%, portfolio modeled stop risk <=30%, reserves and correlation protections.
These are upper budget models, not realized-loss guarantees. PAPER omits funding
settlement and liquidation; no profits or market performance are asserted.

## Stability and health

`LIVE_RESILIENCE=true` uses bounded REST connect/read timeouts (3s/6s), preserving
existing retry/rate-limit backoff. Executable REST quotes are checked against an
exchange clock fetched after their request, preventing acceptance against a
pre-request clock. Individual candle/strategy-data failures skip that candidate;
execution/state/journal errors keep their existing fail-closed recovery handling.
Fresh exits are managed between candidate scans, so a 30-symbol scan does not
force exits to wait until the next whole cycle. Individual blocking requests still
bound response time; this is not a tick-perfect execution engine.

For fixed-symbol WS mode, only fresh quotes are returned when resilience is on.
Fresh positions can exit even if another symbol is missing; missing open-position
quotes still freeze equity/new entries. Old quotes never enter the snapshot. At
snapshot checks, valid-message silence closes the socket to trigger reconnect;
factory errors are caught, caches clear on disconnect, and backoff resets after a
sustained connection. Shutdown closes the socket. No stale-to-REST fallback exists.
Radar and fixed-symbol WS remain mutually exclusive. Socket silence is detected
when PAPER checks a snapshot, not by a separate watchdog thread.

`HEALTH_ENABLED=true` writes `health.json`: stage/progress, completed-cycle time,
missing quote symbols, stream reconnect/error counters, per-symbol flow/funding
reason codes and recorder status. DATA_HEALTH logs distinguish fresh funding,
missing/stale funding, disabled flow, neutral/opposing flow and abstentions.
These labels describe the stated exchange observation timestamp; they are not
continuous assurances that old funding/flow remains fresh. Health write failure
logs a warning without becoming an execution ledger failure.

Dashboard `/api/health` reads process and recorder health; old progress becomes
`STALE_OR_STOPPED` (process: max 30s/two polls; recorder: also respects 1.5 times
sampling cadence). The recorder can therefore be degraded while PAPER is running.
Snapshot/sample ages remain visible. Dashboard journal reads use a bounded 256KiB
tail, so RAM/I/O does not grow with the full append-only history. Recent decision
lists include acceptances; rejection counts exclude accepted records. Decision
counts are diagnostic records, not fills. Optional recorder decisions retain
structured code/flow/regime fields; the execution journals remain authoritative.

## Enable, resume and stop

Use the final command in README, a new isolated directory and identical financial
and signal policy on later resume. Infrastructure flags do not change the saved
financial policy. Stop with Ctrl-C. To disable new infrastructure set
`RECORDER_DECISIONS=false RECORDER_ENABLED=false HEALTH_ENABLED=false
LIVE_RESILIENCE=false`; recording gaps during disabled periods are unavoidable.
No automatic balance reset, old-position migration or mainnet execution is provided.

## Remaining gaps and next steps

The recorder is sampled REST data: no continuous book-event OFI, full depth history,
queue cancellations, complete trade tape, settled funding payments or liquidation
stream. Aggregate flow pages at limit 1000 abstain; windows between cycles are
unobserved. Depth/funding/OI timestamps may be stale or missing. Filter snapshots
come from the recorder session's cached exchange metadata, not guaranteed immediate
rule changes. Public requests share IP rate limits with PAPER despite separate
sessions; reduce symbols/cadence when overrun/gap signals appear. The recorded
schema is not yet an automatic historical replay adapter.

Software verification includes synthetic crash/tamper/rotation cases, failed-data
and bounded-queue cases, stale/partial WS checks, immutable R, and a deterministic
three-hour virtual-clock durability test. It is not a real multi-hour market soak
or economic validation.

1. Run a supervised 3–6 hour PAPER session on the target Termux/Linux device;
   inspect cycle/sample ages, gaps, disk use, reconnections and sealed hashes.
2. Collect at least seven days of forward PAPER and recorder data, with independent
   validation dates fixed in advance; audit funding/depth/flow coverage and costs.
3. Build a small as-of replay adapter and compare default/aggressive settings on
   identical verified observations, including doubled costs and crash/gap stress.


## Corrections after the 10 October device session

The uploaded `VORTEX-stopped-20261010-175611.zip` used commit `ef27451`, virtual
capital 20 USDT, all aggressive confirmations and 30 Radar symbols. Its log shows
882 strategy evaluations, zero entry attempts, 405 chop rejections, 321 stale
signal rejections and eight cycle errors requesting exchange time. For 28 complete
30-symbol scans, the median first-to-last analysis interval was 101.456 seconds;
this is observed log timing, not a benchmark for the corrected code. Recorder
health reported 1617 dropped queued decisions, while the primary decisions.jsonl
remained available. The three sealed segments matched their SHA256 manifests.
The interrupted summary lacked final metrics. This evidence does not show that
capital sizing prevented an entry; no candidate reached that stage.

`PAPER_FAST_SCAN=true` now prepares completed candles, paired derivatives and
optional flow in at most four concurrent jobs. Each job owns its public HTTP
session and each symbol owns its derivative history. Metadata is shared read-only.
The main PAPER thread consumes completed results promptly and alone performs
strategy analysis, broker writes, sizing and exits. Ready results are processed
in completion order (Radar order breaks ties), so this option can change which
candidate gets a position slot. The flag/worker count bind to saved entry policy;
use a new session, including when changing the worker count.

Jobs are bounded to the active universe and the original candle's remaining
signal-age window (never above the existing 90 seconds). Late/unavailable jobs
log explicit skips; pending jobs are cancelled and running read-only requests
finish without being traded. A still-running job cannot be duplicated for the
same symbol. Observation/quote clocks are rechecked at analysis/execution; old
flow still abstains and old funding/quotes/signals still reject. The main thread
polls protective exits while awaiting results. Default sequential behavior is
retained with the flag off. No strategy threshold, risk, universe size or
freshness cap was relaxed. Four workers can still hit shared IP rate limits;
reduce workers to two if backoff/overruns increase. No live speedup or new entry
count is claimed before another device session.

The recorder now drains bounded batches of decisions between individual public
requests, before/after every symbol and during idle periods, then flushes its
remaining queue on graceful stop. It no longer consumes only one decision before
a potentially long whole-universe sampling pass. Slow requests/disk can still
fill its bounded queue; drops remain explicit and the primary journal remains
independent. No automatic unknown-write retry or fabricated recovery of dropped
events was added.

The bounded runner handles Ctrl-C/SIGTERM by signalling the PAPER child gracefully,
waiting at most 30 seconds, then explicitly reporting a forced stop if needed.
Interrupted sessions now save end time, actual duration, counters, final saved
state and `running=false` progress, with `status=interrupted` and
`duration_completed=false`. Timer completion also uses graceful shutdown. Files
are hashed after child shutdown. The complete-run status never substitutes for
an early interruption. No historical dropped decision or old missing summary
is silently reconstructed.

Enable corrected scanning in the README command with
`PAPER_FAST_SCAN=true PAPER_SCAN_WORKERS=4` and a new directory. The recorder and
interrupt fixes apply whenever their existing features run. A supervised repeat
is still needed to measure candidate coverage and recorder gaps on the device.
