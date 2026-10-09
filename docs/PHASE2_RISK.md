# Current account risk policy

Dynamic normal modeled risk is 8–10%; strong modeled risk is 12–15%, with
`RISK_PER_TRADE=0.12` as the strong-budget base. This is an upper loss-budget model,
not an assurance of realized loss: gaps, fees, liquidation and execution can differ.

Defaults: four positions, actual leverage <=5x, aggregate margin <=25%, per-entry
margin <=6.25%, portfolio modeled stop risk <=30%, daily loss halt 55% and trailing
ATR multiplier 0.8. `OPS_PROFILE=conservative` further caps base risk at 8%, positions
at two and daily loss at 20%. Explicit lower financial parameters remain respected.

Half of positive realized net exit/funding stages is reserved by default; unrealized
profits do not enlarge trading capital. Reserves survive restart and are not released
automatically to recover losses. Correlation uses aligned completed returns and
exposure direction, rejecting missing/stale histories or excessive same-risk exposure.

Pyramiding defaults to one add after staged protection and +2 original R, at most
25% original quantity and 2% trading-capital modeled stop risk. It never averages
down, never moves the stop farther away, and must preserve positive modeled net at
the unchanged stop including costs. Financial, liquidity, funding and protection
gates still apply. Original R stays immutable despite weighted-average entry.

Configuration uses `PHASE2_*`, `RISK_PER_TRADE`, `MAX_POSITIONS`, `MAX_DAILY_LOSS`
and `TRAILING_ATR_MULT` in `.env.example`. The current policy is always selected by
runtime configuration; a disabled `PHASE2_ENABLED` flag is refused. Use a new state
directory when changing the saved policy. Automatic Testnet portfolio entry is not
implemented; PAPER/BACKTEST are the supported strategy execution engines.
