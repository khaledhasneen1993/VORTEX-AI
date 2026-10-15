# Current PAPER basket architecture

approved.py → Settings.from_env → bounded session or continuous CLI → BasketLoop.
Only the current smart basket deployment is accepted. Runtime configuration keeps
saved-policy schemas explicit; changing old wallet semantics is refused.

Radar → bounded REST scanner → completed-candle voters → strength ranking →
funding/depth/correlation/risk guards → atomic 2–5-position PAPER basket.
Signal voters are unchanged by adoption. No AI model or signed exchange API.

Basket entries and successful loss adds stage on a shadow broker, then commit
one durable snapshot and an idempotent journal batch. Round decisions persist
before staging so crash recovery cannot repeat an addition. ACTIVE → CLOSING →
CLOSED persists; closure reason latches before individual exits. Only members
with fresh executable quotes can close. No refilling exited basket slots.

flock protects the writer; state files fsync before atomic rename and directory
sync. Journals fsync on append and first creation. Uncertain writes stop all PAPER
execution. Status never writes or replays pending journals. Only writable locked
restarts recover them. Original R anchors do not change when average entry does.

Workers use independent HTTP sessions and bounded pools. They prepare observations
only; the main thread owns broker mutation. Quotes retain exchange timestamps and
four-second freshness. Late/missing data abstains, freezes entry or defers closing.

The background recorder uses bounded queues, compressed append-only JSONL, rotation,
SHA256 manifests, gap records and its own flock. Its failures remain isolated from
trade execution. Sampling is not full market replay. A timed-out shutdown can leave
unsealed data. Health/telemetry expose timestamps and degradation explicitly.

Retained low-level legacy exit/sizing fields support saved schemas and PAPER safety
fixtures; they are not alternate deployment profiles. Removed historical replay,
signed TESTNET, unused WebSocket/microstructure and unrelated launch assets do not
participate in the current release. Runtime dependencies: requests + python-dotenv.

The current target is fixed 0.20 USDT group net. `target_net` reports that same
unit before and after adds/timeouts, and `exit_reason` uses it after protective
exit precedence. Closed groups reset the scan latch when configured so fresh
selection is requested immediately. Existing scanner freshness/deadline bounds
can abstain until the next eligible completed candle. Partial closing
never resets entry permission. New policy fields bind to saved state; absent
historical fields mean disabled rather than silently changing old wallets.

`risk.effective_leverage` is shared by trade sizing and all add margin paths.
The 10x opt-in applies only to PAPER baskets; other paths retain a 5x cap.
Persisted basket policy includes configured leverage, preventing exposure
migration across leverage changes. This does not introduce an exchange gateway.


Opted-in initial basket sizing uses the existing `size_trade` result directly,
bounded above by the requested member margin. Exact-margin/add paths retain the
prior refusal semantics. Adaptive initial entries bypass the historical requested-
margin fill ratio, never exchange minimums or execution guards. Atomic journals
persist requested/actual allocation and sizing mode. The new policy boolean is
saved-state-bound; missing historical values mean false.


Opt-in 913 routes to `IndividualLoop`, sharing bounded scanner/guard/quote/health
helpers but opening and closing independently. Broker policy state binds the 913
net-margin units, leverage/count/capital ceiling; 911 behavior remains the default.
No group is created. Add paths refuse 913. Successful closes use the same durable
state and journal/recovery logic. Recorder union is bounded at 45 in 913 only.
