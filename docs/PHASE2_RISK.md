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

## Phase 1 aggressive strong-risk option

Old defaults remain 8–10% normal and 12–15% strong modeled risk.
`PHASE2_AGGRESSIVE_STRONG_RISK=true` permits `PHASE2_STRONG_MAX` up to 0.18;
when the maximum is absent the enabled option supplies 0.18. Without that flag,
a maximum above 0.15 is rejected. `OPS_PROFILE=aggressive` supplies the flag and
0.18 unless explicitly overridden. Signal strength still interpolates the budget;
18% is a ceiling, not a flat allocation. A signal must be strong-qualified and
meet `MIN_STRONG_SCORE`; normal risk is unchanged. Existing lower base risk,
actual leverage <=5x, aggregate margin <=25%, per-entry/portfolio limits,
correlation, reserves and pyramiding protections remain enforced.

No new performance numbers or economic acceptance are asserted. Use a new state
directory for changed entry/risk/protection policies; matching old default sessions
can resume with missing opt-in fields interpreted as disabled.

## Shared original R

`vortex/r_units.py` is the common definition for initial stop distance, immutable
exit anchor and cumulative net R reporting in PAPER and both replay engines.
Fees affect net PnL, not R; pyramids keep the original exposure denominator.
See [LIVE_INFRASTRUCTURE.md](LIVE_INFRASTRUCTURE.md) for formulas, all three preset
budgets, legacy missing-value handling and live limitations.
