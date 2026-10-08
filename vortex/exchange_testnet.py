"""Binance USD-M TESTNET-only signed gateway.

No production URL; no silent retries for mutating requests. A network timeout
after POST is AMBIGUOUS: caller must query exchange state, never replay entry.
See Binance USDT-M new algo orders: POST /fapi/v1/algoOrder.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode
from decimal import Decimal
import requests

TESTNET_URL = "https://testnet.binancefuture.com"
READ_PATHS = {
    "/fapi/v1/time", "/fapi/v1/exchangeInfo",
    "/fapi/v1/positionSide/dual", "/fapi/v3/positionRisk",
    "/fapi/v2/balance", "/fapi/v1/order", "/fapi/v1/openAlgoOrders",
    "/fapi/v1/algoOrder", "/fapi/v1/openOrders",
    "/fapi/v1/symbolConfig",
}
WRITE_PATHS = {"/fapi/v1/order", "/fapi/v1/algoOrder", "/fapi/v1/leverage"}
DELETE_PATHS = {"/fapi/v1/algoOrder"}


class ExchangeUncertain(RuntimeError):
    """A request may have executed: NEVER retry blindly."""


class ExchangeRejected(RuntimeError):
    pass


def decimal_text(value: float) -> str:
    d = Decimal(str(value))
    if not d.is_finite() or d <= 0:
        raise ValueError("price/quantity must be positive")
    return format(d.normalize(), "f")


class TestnetGateway:
    def __init__(self, key: str, secret: str, session=None, *,
                 armed: bool = False, clock=None):
        if not key or not secret:
            raise ValueError("TESTNET credentials missing")
        self.session = session or requests.Session()
        self.key = key
        self.secret = secret.encode("utf-8")
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.armed = armed
        self._clock_offset = 0

    @classmethod
    def from_env(cls, *, armed: bool = False):
        # Credentials cannot be typed as mainnet vs testnet by their shape.
        # Refuse any configured mainnet aliases; the signed TESTNET challenge
        # in prepare() rejects keys which do not authenticate on Testnet.
        if any(os.getenv(name, "").strip() for name in
               ("BINANCE_API_KEY", "BINANCE_API_SECRET",
                "BINANCE_KEY", "BINANCE_SECRET")):
            raise PermissionError("Production Binance key variables are forbidden for TESTNET")
        return cls(os.getenv("VORTEX_TESTNET_KEY", ""),
                   os.getenv("VORTEX_TESTNET_SECRET", ""), armed=armed)

    def sync_clock(self) -> None:
        response = self.session.get(TESTNET_URL + "/fapi/v1/time", timeout=10)
        response.raise_for_status()
        self._clock_offset = int(response.json()["serverTime"]) - self.clock()
        if abs(self._clock_offset) > 60_000:
            raise ExchangeRejected("Local clock differs by >60 seconds")

    def request(self, method: str, path: str, params: dict | None = None):
        method = method.upper()
        allowed = (READ_PATHS if method == "GET" else WRITE_PATHS if method == "POST"
                   else DELETE_PATHS if method == "DELETE" else set())
        if path not in allowed:
            raise ValueError("Endpoint not allowlisted")
        if method in ("POST", "DELETE") and not self.armed:
            raise PermissionError("TESTNET orders must be explicitly armed")
        values = dict(params or {})
        values["timestamp"] = self.clock() + self._clock_offset
        values["recvWindow"] = 5000
        query = urlencode(values)
        signature = hmac.new(self.secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": self.key, "Content-Type": "application/x-www-form-urlencoded"}
        try:
            # HTTP verb / hostname pinned; server never sees credentials in repo.
            result = self.session.request(
                method, TESTNET_URL + path,
                params=query + "&signature=" + signature if method in {"GET", "DELETE"} else None,
                data=query + "&signature=" + signature if method == "POST" else None,
                headers=headers, timeout=12)
        except requests.RequestException as exc:
            if method in {"POST", "DELETE"}:
                raise ExchangeUncertain("Ambiguous testnet write; reconcile exchange before another write") from exc
            raise ExchangeRejected("Testnet read unavailable") from exc
        if result.status_code >= 400:
            try:
                msg = result.json()
            except ValueError:
                msg = {"status": result.status_code}
            if method in {"POST", "DELETE"} and result.status_code >= 500:
                raise ExchangeUncertain("Testnet write response unknown; reconcile by client id")
            raise ExchangeRejected(f"Testnet API rejected request: {msg}")
        return result.json()

    def one_way(self) -> bool:
        return self.request("GET", "/fapi/v1/positionSide/dual")["dualSidePosition"] is False

    def positions(self) -> list[dict]:
        return self.request("GET", "/fapi/v3/positionRisk")

    def position(self, symbol: str) -> float:
        result = [x for x in self.positions() if x["symbol"] == symbol
                  and x.get("positionSide", "BOTH") == "BOTH"]
        if not result:
            # Binance omits some zero-size position rows; this is not an error
            # after an independently confirmed exchange-flat state. Reject
            # duplicates rather than inferring a position quantity.
            return 0.0
        if len(result) != 1:
            raise ExchangeRejected(f"Ambiguous position rows for {symbol}")
        return float(result[0]["positionAmt"])

    def open_algos(self, symbol: str) -> list[dict]:
        return self.request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})

    def symbol_config(self, symbol: str) -> dict:
        matches = [s for s in self.request("GET", "/fapi/v1/symbolConfig",
                                           {"symbol": symbol}) if s["symbol"] == symbol]
        if len(matches) != 1:
            raise ExchangeRejected("Missing symbol configuration")
        return matches[0]

    def usdt_balance(self) -> float:
        matches = [x for x in self.request("GET", "/fapi/v2/balance") if x["asset"] == "USDT"]
        if len(matches) != 1:
            raise ExchangeRejected("Missing isolated USDT wallet")
        return float(matches[0]["availableBalance"])

    def set_leverage(self, symbol: str, leverage: int) -> None:
        if not 1 <= leverage <= 10:
            raise ValueError("Leverage outside bot policy")
        response = self.request("POST", "/fapi/v1/leverage",
                                {"symbol": symbol, "leverage": leverage})
        if int(response.get("leverage", -1)) != leverage:
            raise ExchangeUncertain("Unable to verify leverage")

    def market_order(self, symbol: str, side: str, qty: float, client_id: str,
                     *, reduce_only: bool = False) -> dict:
        if not client_id.startswith("vx") or len(client_id) > 36:
            raise ValueError("Invalid deterministic client ID")
        if side not in ("BUY", "SELL"):
            raise ValueError("Invalid order side")
        params = {"symbol": symbol, "side": side, "type": "MARKET",
                  "quantity": decimal_text(qty), "newClientOrderId": client_id,
                  "newOrderRespType": "RESULT"}
        if reduce_only:
            params["reduceOnly"] = "true"
        return self.request("POST", "/fapi/v1/order", params)

    def query_order(self, symbol: str, client_id: str) -> dict:
        return self.request("GET", "/fapi/v1/order",
                            {"symbol": symbol, "origClientOrderId": client_id})

    def protective(self, symbol: str, side: str, kind: str, trigger: float,
                   client_id: str) -> dict:
        if kind not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise ValueError("Invalid protective order type")
        if side not in ("BUY", "SELL"):
            raise ValueError("Invalid protective order side")
        params = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side,
                  "type": kind, "triggerPrice": decimal_text(trigger),
                  "workingType": "MARK_PRICE", "closePosition": "true",
                  "clientAlgoId": client_id, "positionSide": "BOTH"}
        # Close-all explicitly forbids quantity and reduceOnly.
        return self.request("POST", "/fapi/v1/algoOrder", params)

    def query_algo(self, symbol: str, client_id: str) -> dict:
        return self.request("GET", "/fapi/v1/algoOrder",
                            {"symbol": symbol, "clientAlgoId": client_id})


    def cancel_algo(self, client_id: str) -> dict:
        """Only by recorded deterministic ID. Never broad-cancel all guards."""
        if not client_id.startswith("vx") or len(client_id) > 36:
            raise ValueError("Refusing to cancel unknown protective order")
        return self.request("DELETE", "/fapi/v1/algoOrder", {"clientAlgoId": client_id})
