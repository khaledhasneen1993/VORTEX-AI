"""Explicitly armed single-entry TESTNET commissioning (never production).

No background run and no automatic order retry; must inspect fill and guards before
any subsequent experimental trade. Only TESTNET credentials are accepted.
"""
from __future__ import annotations
import os
from pathlib import Path
from .binance import Market, TESTNET
from .config import Settings
from .exchange_testnet import TestnetGateway
from .testnet_guard import TestnetSupervisor
from .risk import size_trade
from .strategy import analyze
from dataclasses import replace


def prepare(cfg: Settings, *, armed: bool = False):
    api = TestnetGateway.from_env(armed=armed)
    api.sync_clock()
    api.usdt_balance()  # signed Testnet-only authentication challenge; invalid keys rejected
    guard = TestnetSupervisor(api, cfg.data_dir / "testnet_intent.json")
    return api, guard


def doctor(cfg: Settings) -> dict:
    api, guard = prepare(cfg)
    if guard.state["phase"] == "IDLE":
        guard.start_check()
        return {"ok": True, "mode": "TESTNET ONLY", "state": "IDLE",
                "wallet_usdt": api.usdt_balance()}
    return guard.audit()


def once(cfg: Settings, symbol: str, *, acknowledge: bool) -> dict:
    from .locks import ProcessLock
    with ProcessLock(cfg.data_dir / "testnet.lock"):
        return _once_locked(cfg, symbol, acknowledge=acknowledge)


def _once_locked(cfg: Settings, symbol: str, *, acknowledge: bool) -> dict:
    if not acknowledge or os.getenv("VORTEX_TESTNET_ARM") != "TESTNET_ONLY":
        raise PermissionError("Testnet order requires --ack-testnet AND VORTEX_TESTNET_ARM=TESTNET_ONLY")
    if symbol not in cfg.symbols:
        raise ValueError("Symbol must be part of configured trading universe")
    api, guard = prepare(cfg, armed=True)
    if guard.state["phase"] != "IDLE":
        return guard.audit()
    if guard.state.get("ever_entered"):
        raise PermissionError("Testnet single-entry commissioning already performed")
    guard.start_check()
    market = Market(base=TESTNET)
    now = market.server_ms()
    candles = market.candles(symbol, cfg.timeframe, 220, now)
    higher = market.candles(symbol, "15m", 120, now)
    macro = market.candles(symbol, "1h", 260, now)
    minute = market.candles(symbol, "1m", 120, now)
    sig = analyze(symbol, candles, higher, cfg.min_score, macro=macro, minute=minute,
                  strict_votes=cfg.strict_votes, min_strong_score=cfg.min_strong_score)
    if not sig or now - candles[-1].close_ts > 90_000:
        return {"ok": False, "reason": "No fresh qualified setup; no order sent"}
    if os.getenv("USE_CLAUDE", "false").lower() == "true":
        from dataclasses import replace
        from .ml import feature_snapshot
        from .claude_review import confirm, ReviewUnavailable
        sig = replace(sig, features=feature_snapshot(candles, sig))
        try:
            approved, confidence, explanation = confirm(sig)
        except ReviewUnavailable:
            return {"ok": False, "reason": "Claude signal confirmation unavailable"}
        if not approved:
            return {"ok": False, "reason": f"Claude veto: {explanation[:60]}"}
    quotes = market.quotes(now_ms=now)
    if symbol not in quotes:
        return {"ok": False, "reason": "No valid TESTNET book"}
    bid, ask = quotes[symbol]
    if (ask - bid) / ((ask + bid) / 2) * 10000 > cfg.max_spread_bps:
        return {"ok": False, "reason": "TESTNET spread too wide"}
    entry = ask if sig.side == "LONG" else bid
    if abs(entry - sig.entry) >= abs(sig.entry - sig.stop) * .35:
        return {"ok": False, "reason": "Signal stale versus executable quote"}
    # Adjust protective distances to executable side of spread.
    sign = 1 if sig.side == "LONG" else -1
    # Keep the strategy's votes, ATR and indicators when moving the theoretical
    # entry to the executable TESTNET book side. Otherwise trailing loses ATR.
    adjusted = replace(sig, entry=entry,
                       stop=entry - sign * abs(sig.entry - sig.stop),
                       target=entry + sign * abs(sig.target - sig.entry))
    balance = api.usdt_balance()
    filt = market.symbol_filters(symbol)
    sized = size_trade(adjusted, balance, cfg, filt)
    if not sized:
        return {"ok": False, "reason": "Risk budget below exchange minimum"}
    qty, _margin = sized
    # Persistent latch prevents firing another entry even after a successful close.
    guard.persist(ever_entered=True)
    return guard.enter(adjusted, qty, filt, min(cfg.max_leverage, 5))
