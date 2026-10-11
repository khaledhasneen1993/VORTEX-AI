# Adopted system architecture

`approved.py` supplies deployment defaults; `Settings.from_env()` validates them.
The bounded `vortex.session` runner applies the canonical flags, preflights public
market data and supervises the PAPER child. Its run evidence includes effective
configuration, version, source hashes and completed/interrupted/forced status.
The CLI exposes PAPER, status, dashboard and acknowledged PAPER halt reset.

Radar → bounded REST scan → completed-history strategy voters → sizing and
execution guards → PAPER broker. Public derivatives/trades may abstain when
incomplete. `signal_features` records the same entry features formerly packaged
with the unused learner; it does not make predictions. Manual and AI deployment
modules have been removed. Internal historical and TESTNET safety helpers are
retained to verify isolation, no look-ahead and protective-state contracts.

Critical held-position and candidate quotes can be recovered from limited public
depth when bulk quotes omit them. The same exchange-timestamp, 4-second age,
future tolerance, finite-price and book-validity checks apply. Old quotes are
revalidated after recovery; cached prices are never restamped. Resilient scan
bucket handling avoids repeatedly scanning the same completed candle on error.

The broker keeps flock, atomic state writes, order journals and uncertain-write
halts. Persisted policy checks protect wallets from silently changed semantics.
Original R is shared through `r_units.py`; capture margin targets use their own
explicit units.

The bounded background recorder samples active-symbol best bid/ask, limited
depth, funding, mark, OI and basic taker flow. It uses append-only compressed JSONL,
rotation, SHA256 manifests, flock, crash recovery and gap records. A bounded queue
and shutdown budget protect RAM and the live loop; recorder failures fail soft.
Decision hooks join trading observations to recorder evidence.

This is sampled REST data, not a full tick tape or an exchange matching-engine
model. Recorder gaps, stale derivatives, truncated flow, time endpoint failures,
order-filter rejections and missing quotes remain visible operational limits.
