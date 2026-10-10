# Phase 0 — one-minute OHLC barrier-touch study (NOT a trade backtest)

**Observed:** 2026-10-10 UTC. **Code under test:** `4e5a28c06378aeddeda8075571ee630dacc7d8cd`.  
**Job:** [GitHub Actions #38038196755](https://github.com/khaledhasneen1993/VORTEX-AI/actions/runs/38038196755); six symbol jobs successful.  
**Original signals:** [canonical shadow #38037051647](https://github.com/khaledhasneen1993/VORTEX-AI/actions/runs/38037051647).  
**Method:** `research/phase0_exit_paths.py` consumes SHA256-verified original accepted-signal JSONL plus checksum-verified Binance Vision real **1m candles**, on six symbols. Independently annotate each candidate signal's next 1m **open**, preserve the original stop-distance (R), reject a >0.35R entry-price gap, and observe which **static price barrier** was touched first within 240 minutes. Touches in the same 1m candle are labelled ambiguous/stop-first conservatively. No exchange order, fill price, portfolio, slippage, mark price, funding settlement or fees are simulated.

## Verified aggregates

The 30-day sample (Sep 9–Oct 8) is a **subset** of the 90-day sample (Jul 11–Oct 8); the columns are **not independent** out-of-sample trials. Percentages use *all* accepted signals including no-touch observations in denominator.

| Horizon | Accepted independent candidate studies | Exact next-open available and <=0.35R gap | Full 240-minute path |
|---|---:|---:|---:|
| 30 days | 182 | 182 | 182 |
| 90 days | 532 | 532 | 532 |

### 30-day static price barriers

| Target before initial -1R stop | Favorable touch first | Stop touch first | Neither barrier within 240m | Ambiguous same-minute |
|---|---:|---:|---:|---:|
| +1R | 96 (52.75%) | 86 | 0 | 0 |
| +1.5R | 73 (40.11%) | 109 | 0 | 0 |
| +2R | 59 (32.42%) | 119 | 4 | 0 |
| +3R | 43 (23.63%) | 128 | 11 | 0 |

### 90-day static price barriers

| Target before initial -1R stop | Favorable touch first | Stop touch first | Neither barrier within 240m | Ambiguous same-minute |
|---|---:|---:|---:|---:|
| +1R | 291 (54.70%) | 240 | 1 | 0 |
| +1.5R | 221 (41.54%) | 306 | 5 | 0 |
| +2R | 179 (33.65%) | 335 | 18 | 0 |
| +3R | 125 (23.50%) | 375 | 32 | 0 |

### 90-day currency breakdown

| Symbol | Signals | +1R before stop | Stop before +1R | +2R before stop | Stop before +2R | Neither at +2R |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 77 | 37 | 40 | 22 | 52 | 3 |
| ETHUSDT | 111 | 67 | 44 | 40 | 69 | 2 |
| SOLUSDT | 106 | 57 | 48 | 39 | 63 | 4 |
| BNBUSDT | 107 | 61 | 46 | 38 | 64 | 5 |
| XRPUSDT | 71 | 35 | 36 | 21 | 47 | 3 |
| DOGEUSDT | 60 | 34 | 26 | 19 | 40 | 1 |
| **Total** | **532** | **291** | **240** | **179** | **335** | **18** |

**Caveats:** no observed same-minute ambiguity among these particular source signals, but 1m OHLC cannot prove tick-order inside any bar in general. The candidates can overlap across symbols/time; an actual portfolio cannot open all simultaneously. These are *not* win rates, order fills, account returns, nor realized or modelled trading PnL. No causal attribution has been established. The original one-hour directional close study is a different label and must not be conflated with first-barrier touch.

## Source artifacts for independent checking

[Workflow artifact page](https://github.com/khaledhasneen1993/VORTEX-AI/actions/runs/38038196755) retains per-symbol `touch-30d.jsonl`, `touch-90d.jsonl`, their `.summary.json` with SHA256, exact sample source-audit SHA256, and original public archive download log. Artifact IDs: BTC 11665225815; ETH 11664911216; SOL 11665115888; BNB 11665136023; XRP 11665170807; DOGE 11664538872. Six per-symbol jobs passed. CI quality checks succeeded at the corrected source revision.

## What this validates — and does NOT

- **Validates:** integrity of 30/90-day accepted-signal audit, 1m data coverage, descriptive touch ordering against a static -1R barrier, transparent no-touch/entry-gap accounting, deterministic unit-tested methodology.
- **Does not validate:** current 30/30/trailing exit schedule, price break-even, pyramiding, risk capital constraints, actual bid/ask and L2 liquidity capacity, chronological execution with stop updates, settlement funding, liquidations, realistic fill slippage, true net profitability, or ML gains.
- **Practical observation:** +1R price is touched before -1R for about 55% of 90-day candidates, but +3R is touched first in about 24%. It would be methodologically invalid to optimize exits solely on these development-window rates.
- **Next:** acquire real historical as-of L2/order-book, top-of-book, mark/funding/OI data from a verifiable source; run frozen complete-guard chronological 30/90-day **broker** simulations including costs, evaluate three *independent* validation months and 7-day forward PAPER, then consider optional Phase 1 improvements if evidence supports them. No main merge and no strategy/risk change.

A candidate full L2 source may be Binance's special-access futures historical orderbook API, Tardis.dev or Amberdata. Binance Vision's `bookDepth` percent-band CSV **cannot substitute** for a price-level executable order book. Confirm coverage, price and access permissions before using paid data; never silently fabricate quotes/marks.
