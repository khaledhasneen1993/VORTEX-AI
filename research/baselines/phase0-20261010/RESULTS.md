# Phase 0: verified candles, economic replay blocked

Run 38002042147 (2026-10-09 22:58–23:26 UTC) downloaded and checksum-verified 2,400 daily OHLCV CSV archives (six USD-M symbols, four intervals, 100 UTC days including warmup). Coverage 2,400/2,400; missing 0.

The single-symbol and portfolio 90-day full-guard backtests both exited with code 1 at `require_history`: historical as-of funding/depth observations were not supplied. The workflow's green status confirms source acquisition and artifact upload, **not** a successful economic backtest. Neither 30-day replay was attempted in this run. No trade count, PnL, PF, win rate, average R or validated baseline exists.

Evidence: [workflow run 38002042147](https://github.com/khaledhasneen1993/VORTEX-AI/actions/runs/38002042147), artifact `phase0-90day-source-and-full-guard-attempt` (SHA256 `f61f454e14dae34a958795d0d9e203e21219e1a5696fa7e3e8d14eee86cad0bd`). It contains `coverage.json`, `download.log`, `single.log`, `portfolio.log`, `replay-returncodes.txt` and `NOTICE.txt`. No full OHLCV dataset was uploaded as an artifact; source hashes and URLs were recorded.

Still missing: timestamped historical bid/ask and near-price order-book depth; as-of funding/OI observations and funding marks/forecasts; historical contract filter validity. A current filter snapshot cannot establish historical correctness. Do not use realized future funding as an entry-time observation. Keep Phase 1–5 blocked and `main` unchanged.
