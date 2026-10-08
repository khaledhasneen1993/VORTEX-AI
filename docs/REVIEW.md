# VORTEX AI — reviewer acceptance checklist

Status: **PRE-SIMULATION CODE REVIEW**. No production trading is authorized.

## Implemented modules
- [x] Four independent strategy voters, TWO-vote confluence, completed hourly EMA50/EMA200 macro
- [x] Funding/OI vote requires real, timestamped and time-separated public derivatives
- [x] Liquidity/momentum candidate radar with opt-in compatibility gate
- [x] Paper quarter TP1/TP2 + inward-only trailing, mirrored in OHLC replay. Entry stop 1.5 ATR and terminal target 4.5 ATR (3R).
- [x] Paper position entry features + one completed-roundtrip ML training label
- [x] Fixed Binance 2026 /public/stream bookTicker route and added real exchange event-time freshness/order checks
- [x] Python package, CLI, CI test suite
- [x] Optional Binance WebSocket bid/ask with staleness rejection
- [x] Optional real depth/aggregate trade flow filter; no invented whale classifications
- [x] Multi-symbol synchronized OHLC portfolio backtest with stop-first fills
- [x] Crash-recoverable paper trade journal, deduplicated events
- [x] 1% per-trade risk, 5% daily halt, five-loss circuit breaker
- [x] TESTNET-only HMAC gateway, deterministic client IDs, no POST retries
- [x] TESTNET close-all STOP_MARKET/TAKE_PROFIT_MARKET via Binance Algo Orders
- [x] Reconciliation and emergency reduce-only close when explicitly armed
- [x] Local-only status UI and optional Telegram alerting
- [x] ML trainer with chronological purged holdout; invalid models cannot trade
- [x] Mock tests for missing stops, ambiguous writes, quote delays and journal interruption

## Acceptance gates still open
- [ ] Verify the four-voter signal frequency and parameter robustness on observed historical candles (no simulation performed yet)
- [ ] Archive historical funding and open-interest data to include vote #4 in backtests; current OHLC replay omits vote #4
- [ ] Real-time integration validation for dynamic radar and WebSocket on actual Binance public streams
- [x] Implement Testnet-only TP1/TP2, guarded reduce-only fills and replacement stop create-verify-before-cancel **in code/mocks only**; genuine TESTNET order validation remains a separate gate
- [ ] Model historical opportunity ranking and microstructure with honest archived depth/trades (currently unavailable)
- [ ] Genuine TESTNET signed API/order integration with testnet-only keys
- [ ] Exchange partial-fill, timeout and liquidation edge cases on a running testnet account
- [ ] Real 30-day multi-symbol backtest with fees/funding sensitivity
- [ ] Multiple-week realtime paper trial, crash/restart drills and reconciled trade logs
- [ ] Real labeled trade dataset and independently validated ML model
- [ ] Hosted long-lived runtime, real alert delivery and connectivity checks
- [ ] Independent security/financial risk review before building a separately gated production adapter

## Exact Binance API assumptions

Official USD-M Futures REST reference:
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

Conditional TP/SL: POST /fapi/v1/algoOrder with algoType=CONDITIONAL and triggerPrice. For close-all do NOT combine closePosition=true with quantity or reduceOnly. Read current protections with GET /fapi/v1/openAlgoOrders. Read the real position with GET /fapi/v3/positionRisk. A regular order acknowledgement is not proof of protection.

## Code reviewer focus
1. Verify signed requests only target testnet.binancefuture.com, never production.
2. Verify STOP and TAKE_PROFIT are actually present, both correctly sided and triggered at intended tick prices.
3. Inspect halt behavior for lost connectivity, ambiguous POST, missing stop, hedge mode or unexpected account positions.
4. Ensure no production trading path and no withdrawal permissions exist.
5. Verify paper event journal recovery after a simulated crash and assess unresolved edge cases.
6. Confirm that ML is inactive until genuinely validated and that risk always has the final say.
7. Distinguish historical OHLC assumptions from real execution (slippage, depth, funding, queue, liquidation).

Approval of this PR means the code may proceed to simulation and testnet integration—not that profitable live trading has been proven.
