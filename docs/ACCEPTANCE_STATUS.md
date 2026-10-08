# VORTEX AI — acceptance report (2026-10-09)

This is an engineering acceptance checklist, **NOT** a trading performance claim.
User objective: four reviewed source projects + agreed VORTEX customizations,
with safe automated market scanning, risk, honest simulations and testnet
protective execution. No secrets are stored in this public repository.

## Pass: offline/CI verified against deterministic fixtures

- [x] Four independent votes, TWO-vote agreement, hourly EMA50/200 regime,
      completed 1m Stochastic RSI divergence, ATR stop and 3R terminal target.
- [x] Historical single-market and portfolio UTC daily risk reset based on
      historical timestamps (not development host date).
- [x] Risk halt remains latched after daily loss or five losing completed positions.
- [x] Historical drawdown calculated on marked portfolio equity; open positions
      reported as unrealized and NOT silently booked as closed PnL.
- [x] Indicator warmup includes TEN days of hourly history before EMA200 signals.
- [x] Reject stale, future-dated, missing-timestamp REST bookTicker and
      websocket ticker observations before acting on them.
- [x] Funding and open-interest vote requires monotone exchange-sourced
      timestamps; duplicate, delayed or absent observations ABSTAIN.
- [x] TESTNET guardian rejects unknown conditional orders and halts after a
      partially confirmed emergency flatten; no blind order replay.
- [x] Single POSIX process lock prevents concurrent PAPER writers or signed
      TESTNET watchdog/commissioning processes for one ledger.
- [x] Tests, fatal-code lint, dependency consistency, compilation, and CLI
      smoke gates are in GitHub Actions.

## NOT yet independently proven — no false approval

- [ ] Real Binance Futures TESTNET responses, protection lifecycle,
      partial fills, clock drift, liquidation, rate limits and reconnection.
      Requires actual TESTNET-only API credentials and operator permission.
- [ ] Profitability and drawdown across an independently chosen historical
      sample; user requested to review before simulations.
- [ ] Weeks of forward paper operation, market snapshots and VPS endurance.
      GitHub Actions executes tests, it does **not** run a 24/7 bot.
- [ ] Historical replay of archived live open interest/funding, depth,
      radar constituents and market-impact/fill observations.
      OHLC data alone cannot reproduce these faithfully.
- [ ] 250+ genuine closed-position feature/label examples and validated ML
      model. The repository ships no pretrained 'AI edge'.
- [ ] Literal feature parity with all 18 StrikeChart detectors, LSTM/
      ensemble architectures, and every optional subsystem of the other
      three original projects. Existing integrations are independently
      implemented subsets; unused names are not evidence of functioning.
- [ ] Production signed adapter and independent approval. `RUN_MODE=live`
      deliberately fails closed. There is no real-money readiness claim.

## Exact source and audit

- Source ZIP comparisons: Neko Futures Trader, Professional Quantitative
  Trading Bot, Futures AI Bot, StrikeChart.
- Current code: vortex/strategies.py, vortex/strategy.py, vortex/risk.py,
  vortex/backtest.py, vortex/portfolio.py, vortex/stream.py,
  vortex/binance.py, vortex/testnet_guard.py, vortex/testnet_stages.py,
  vortex/exchange_testnet.py, vortex/locks.py, vortex/ml.py.
- Static/risk tests: tests/test_historical_risk.py,
  tests/test_market_freshness.py, tests/test_single_writer.py,
  tests/test_testnet_stages.py, tests/test_hardening.py.
- Exchange order and REST response formats: Binance official USD-M docs
  https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

This checklist must remain explicit. Passing mocked tests can qualify a release
for controlled simulation, NEVER as proof of profit or production readiness.
