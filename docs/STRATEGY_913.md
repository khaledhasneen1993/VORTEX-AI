# Strategy 913 — independent PAPER positions

913 is an explicit alternative to preserved strategy 911. It is disabled by
default (`STRATEGY_913_ENABLED=false`). The `strategy-911` Git branch retains
commit 7f359ed unchanged; the normal `run_paper.sh` still selects 911.

## Contract

- Default virtual wallet: 100 USDT. Public Binance data, no authentication or orders.
- Same completed-candle capture voters, Radar up to 30, strength ranking, bounded
  scanning and execution guards as 911. No new indicator or trading signal.
- Up to **15 independent distinct symbols**; no minimum group count. Fill available
  slots using strongest eligible fresh signals; do not wait for all positions to close.
- Same **10x** leverage and **up to 10% of current marked equity as entry margin**,
  reduced by existing risk, available capital and exchange lot/minimum constraints.
  At a 100-USDT wallet this requests up to about 10 USDT margin per position.
- Each position closes completely at **net PnL >= +1% of its actual posted margin**,
  or **net PnL <= -5% of its actual posted margin**. Include entry fee, modeled exit
  slippage and exit fee. At 10-USDT margin the thresholds are +0.10 / -0.50 USDT.
  These are leveraged margin returns, not 1% / 5% underlying-price moves.
- No basket target, collective exit, group timer, averaging, pyramiding or partial
  profit-taking. One position exiting does not close the others. Individual prices
  and initial R are anchored when opened; exit triggers recompute net costs at each
  fresh poll. Stop/target thresholds are triggers, not guaranteed fill amounts.
- Same 60% aggregate margin ceiling, trade/portfolio risk, daily loss, rolling
  drawdown, 25% account floor, spread/depth/funding/correlation, freshness and cooldown
  controls. Available cash is not borrowed beyond leverage. Original 911's group
  -10-USDT close and 10% member-price stop are replaced by independent -5%-margin exits.

**15 is a maximum, not a promised simultaneous fill count.** With 100 USDT and
about 10 USDT per member the 60% margin cap funds about six full-sized positions,
with fees/reserve and smaller lots changing actual capacity. Fifteen 10-USDT margins
require 150 USDT of margin; neither the count cap nor 10x creates that cash.

No entry may round upward across risk to meet exchange minimums. New costs must
also leave used margin inside the capital ceiling. High modeled costs that consume
the 5% stop budget refuse entry. Winners/losses are polled, not continuously streamed;
missing fresh held quotes freezes entries while fresh eligible exits can still run.

## Run on Termux/Linux

Stop the prior engine, update/install, then start a new isolated 913 session:

```bash
cd ~/VORTEX-20M
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e .
STARTING_EQUITY=100 bash run_913.sh 3600
```

The launcher explicitly selects 913 regardless of an old .env, writes the latest
run path, enables a wake lock when available, and saves summary/logs/journals.
For continuous operation with a new isolated wallet:

```bash
python -m vortex.configure --strategy 913 --equity 100
python -m vortex.cli paper
```

Return to 911 with `bash run_paper.sh 3600`, or configure a new continuous wallet
using `python -m vortex.configure --strategy 911 --equity 100`.
Do not change saved-wallet policies or mix sessions. 913 target/stop units,
leverage, count and margin cap are persisted and reject mismatched recovery.
The timer saves any open positions; it never fabricates closure at the deadline.
Recorder supports a bounded union of 30 Radar + 15 held symbols in this mode.

## Validation boundary

Deterministic tests cover LONG/SHORT fee-aware +1%/-5% boundaries, independent
closure/reselection, no additions, maximum count/cash limits, execution refusals,
recording bounds, recovery/policy isolation and preservation of default 911.
Existing journal/flock/uncertain-write/stale-data tests remain. No live 913 result
exists yet; previous 911 session results do not establish 913 performance.
Funding cashflows and liquidation remain unmodeled. No new dependencies.

Execution batch routing fix: the initial 913 live attempt accepted signals but
the shared guard worker rejected independent mode with "Execution batches require
PAPER baskets". Guard batching now explicitly allows PAPER 913 as well as 911,
retaining its 0..10s deadline, bounded workers and original timestamps. A regression
runs the real guard batch through the 913 loop into a virtual entry; parallelism,
stale funding and expiration tests cover both modes. No filter or risk was relaxed.


Critical-quote routing fix: 913 now opts into fifteen critical symbols in the
public Market gateway; the historical/default gateway remains limited to six.
Final entry snapshots prioritize held symbols, then the strongest candidate slots,
never more than fifteen recovery names even with thirty accepted Radar signals.
Bulk quotes may supply additional fresh candidates. Recovery still makes at most
six depth requests plus one bulk refresh per quote call. All observations retain
original timestamps and the same freshness bound; missing held prices freeze entries.
CLI regressions use real guard/Market quote code with 1/7/15/30 candidates, and
freshness/bounded-recovery tests cover fifteen held quote names. These are synthetic
software checks, not completed live performance results.
