# Current PAPER basket architecture

approved.py → Settings.from_env → bounded session or continuous CLI → BasketLoop.
Only the current smart basket deployment is accepted. Runtime configuration keeps
saved-policy schemas explicit; changing old wallet semantics is refused.

Radar → bounded REST scanner → completed-candle voters → strength ranking →
funding/depth/correlation/risk guards → atomic five-position PAPER basket.
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
