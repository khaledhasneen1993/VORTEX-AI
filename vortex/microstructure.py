"""Real market depth and aggregated prints: measurable microstructure, no invented whales.

Optional live/paper filter; historical OHLC backtests CANNOT replay these snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class MicroScore:
    bid_depth_usdt: float
    ask_depth_usdt: float
    taker_buy_fraction: float
    spread_bps: float
    accepted: bool
    reason: str


def analyze_microstructure(
    side: str, depth: dict, trades: list[dict], min_side_usdt: float = 25000.0, max_spread_bps: float = 12.0
) -> MicroScore:
    if side not in {"LONG", "SHORT"}:
        raise ValueError("Invalid position side")
    bids = depth.get("bids", [])
    asks = depth.get("asks", [])
    if not bids or not asks or not trades:
        return MicroScore(0, 0, 0, 0, False, "Missing depth/trades")
    try:
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if bid <= 0 or ask < bid:
            raise ValueError("Crossed / empty book")
        bp = (ask - bid) / ((ask + bid) / 2) * 10000
        # Sum top 10 levels on EACH side. Not a measurement of market impact.
        bd = sum(float(p) * float(q) for p, q in bids[:10])
        ad = sum(float(p) * float(q) for p, q in asks[:10])
        # Binance aggTrades 'm' is buyer-is-maker: false means buyer taker.
        buy = sum(float(t["p"]) * float(t["q"]) for t in trades if not t["m"])
        sell = sum(float(t["p"]) * float(t["q"]) for t in trades if t["m"])
        if min(bd, ad) <= 0 or buy + sell <= 0:
            raise ValueError("Insufficient liquidity")
        fraction = buy / (buy + sell)
        if not all(isfinite(v) for v in (bd, ad, bp, fraction)):
            raise ValueError("Nonfinite market data")
        wall = bd if side == "LONG" else ad
        aligned = fraction >= 0.52 if side == "LONG" else fraction <= 0.48
        passed = wall >= min_side_usdt and bp <= max_spread_bps and aligned
        why = "confirmed" if passed else "thin book, spread or adverse taker flow"
        return MicroScore(bd, ad, fraction, bp, passed, why)
    except (TypeError, ValueError, KeyError, IndexError):
        return MicroScore(0, 0, 0, 0, False, "Malformed depth/trades")


def collect_micro(market, symbol: str, side: str, now_ms: int) -> MicroScore:
    depth = market.get("/fapi/v1/depth", {"symbol": symbol, "limit": 20})
    trades = market.get(
        "/fapi/v1/aggTrades",
        {"symbol": symbol, "startTime": now_ms - 15_000, "endTime": now_ms, "limit": 1000},
    )
    return analyze_microstructure(side, depth, trades)
