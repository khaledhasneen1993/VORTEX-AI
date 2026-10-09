# Termux PAPER observation and diagnostics

User supplied summary and complete session log for commit
`891d761452d67c2683654c1c4ae62ad7fc6c14e2`.
2026-10-09 10:29:32–10:49:32 UTC; elapsed 1200.552 seconds.
51 successful polls, 5 radar selections, 0 cycle errors, 0 entries,
0 closed trades, 0 final positions; starting/final marked equity 1000 USDT.
Source session.log SHA256 reported by user:
`1f7f5483330bcbecb873d870a83bf6da14938639cd6575503a8972fcfabf70cf`.
Original artifacts remain on user's phone; this note does not claim archival
or independent hash verification of those artifacts.

The old signal_evaluations counter counted SIGNAL broker attempts, not calls to
analyze. No ACCEPT, SIGNAL, warning or error appeared in the supplied full log.
Early history/volatility returns and vote rejects were unobservable at INFO;
there is insufficient evidence to attribute zero entries to a specific gate.

Next measurement: same PAPER strategy, same financial settings, new 1200-second
session with --diagnostics and a fresh output directory. Log each analyze call,
all early strategy rejection reasons, individual votes, no-consensus rejection,
empty candle inputs, missing quotes and stale signals. Counter schema v2 counts
actual analyze calls separately from entry attempts. Verbose strategy logging
is opt-in; it does not enable HTTP debug logging. No thresholds changed, no
optimization trials added, no acceptance or profitability claim. Research
automation remains paused. Existing results must not be overwritten.

## Second user-supplied measurement

Commit `700164c8255eba9a61effbef71758bcb1e811bf9`, 10:58:30–11:18:31 UTC:
1200.669 seconds, 50 polls, 5 radar selections, 60 analyses, 60 strategy
rejections, 240 vote records, 0 entry attempts, 0 entries, 0 errors, equity
1000. User-reported session.log hash:
`8b8af6125c5de5a51c98ee2a1ad7f7ee5b1082c3b6c014069e59cea4f7ba99ad`.
Only the final 100 log lines were supplied, not the complete artifact.
The last radar batch had zero breakout votes, relative volume 0.30–1.00x,
and single trend votes for KAIAUSDT (long) and 龙虾USDT (short).
All funding votes in this supplied batch abstained as missing/stale.

Clock audit found cycle-start time reused for derivative timestamps fetched
after sequential candle/API requests. Such observations can be rejected as
future relative to that old clock. This is a code defect; it has not been
proven to explain every funding abstention in the supplied session.

Correction: obtain exchange server time after both derivative responses;
keep the original 15-second freshness and 1-second future tolerance, OI interval
60 seconds–30 minutes, and first-observation/duplicate abstention. Use that
post-response time for live strategy freshness and stale-entry age, while
candle inputs remain cut off at the original cycle time. Log exact derivative
abstention reasons and valid observed funding/OI values. No invented data or
threshold relaxation. Preregistered next measurement: fresh 1200-second PAPER
session with identical financial and voting settings plus diagnostics; examine
valid derivative counts and rejection reasons, not just whether trades occur.

## Corrected-clock observation and three-hour follow-up

User supplied summary for `f2c358f2255962c282e7b8bff5b5b4bf335783bb`:
11:29:46–11:49:47 UTC, 1200.447 seconds, 50 successful polls, 60 analyses,
55 strategy rejections, 5 entry attempts, 2 entries, 0 cycle errors.
SKLUSDT closed with recorded total net PnL +55.50641786; KAIAUSDT remained
open. Wallet 1055.17356085 and last marked equity 1037.95 from initial 1000.
Funding/OI VALID records and funding votes appeared in the supplied log.
Reported session.log hash:
`46fe13947118727091f0b63c8bdca04e2772f8818ef0be07cacdc7886e3089ec`.
This short, different market period does not establish causal PnL improvement
or profitability. PAPER funding payments remain excluded.

User authorized a fresh 3-hour PAPER session starting with 150 USDT, same risk
and voting settings, on Termux in background. Wrapper now supports 10800
seconds and explicit finite-positive --starting-equity. Use a new output/state
directory; do not carry the old KAIA position into this independent account.
Original saved KAIA state/results remain preserved and stopped. Record both
realized wallet and final marked equity/open positions; no forced invented
closing fill, strategy selection, or acceptance based on this session.
