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
