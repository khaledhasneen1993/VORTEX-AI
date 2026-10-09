"""TESTNET-only auditing; automatic strategy entry is not implemented.

No background run and no automatic order retry; must inspect fill and guards before
any subsequent experimental trade. Only TESTNET credentials are accepted.
"""

from __future__ import annotations

from .config import Settings
from .exchange_testnet import TestnetGateway
from .testnet_guard import TestnetSupervisor


def prepare(cfg: Settings, *, armed: bool = False):
    api = TestnetGateway.from_env(armed=armed)
    api.sync_clock()
    api.usdt_balance()
    guard = TestnetSupervisor(api, cfg.data_dir / "testnet_intent.json")
    return (api, guard)


def doctor(cfg: Settings) -> dict:
    api, guard = prepare(cfg)
    if guard.state["phase"] == "IDLE":
        guard.start_check()
        return {"ok": True, "mode": "TESTNET ONLY", "state": "IDLE", "wallet_usdt": api.usdt_balance()}
    return guard.audit()


def once(cfg: Settings, symbol: str, *, acknowledge: bool) -> dict:
    from .locks import ProcessLock

    with ProcessLock(cfg.data_dir / "testnet.lock"):
        return _once_locked(cfg, symbol, acknowledge=acknowledge)


def _once_locked(cfg, symbol, *, acknowledge):
    return {
        "ok": False,
        "reason": "Current release is PAPER/BACKTEST only; automatic Testnet entry is not implemented",
    }
