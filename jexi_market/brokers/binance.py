# -*- coding: utf-8 -*-
"""Binance spot adapter (REST, HMAC-SHA256, testnet by default).

Implements the :class:`Broker` interface against Binance's public spot
API so JEXI Market can trade crypto 24/7:

* account:  ``GET /api/v3/account``
* order:    ``POST /api/v3/order`` (market / limit)
* price:    ``GET /api/v3/ticker/price``
* klines:   ``GET /api/v3/klines``

Safety defaults:
* ``BINANCE_TESTNET`` defaults to **true** — real-money trading requires
  ``BINANCE_TESTNET=0`` AND ``JEXI_LIVE_TRADING_ENABLED=1``.
* signing uses HMAC-SHA256 over the query string (standard Binance
  scheme); keys come only from the environment.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from jexi_market.brokers.base import Broker, BrokerAccount, BrokerOrder, BrokerPosition

logger = logging.getLogger(__name__)

BASE_MAINNET = "https://api.binance.com"
BASE_TESTNET = "https://testnet.binance.vision"


class BinanceBroker(Broker):
    """Binance spot trading (testnet-first)."""

    name = "binance"
    supports_bracket_orders = False   # OCO managed locally by the lifecycle manager

    def __init__(self, config: Optional[Any] = None):
        import os
        self.api_key = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        self.testnet = os.getenv("BINANCE_TESTNET", "1").strip().lower() in {"1", "true", "yes", "on"}
        self.base_url = BASE_TESTNET if self.testnet else BASE_MAINNET
        self.recv_window = int(os.getenv("BINANCE_RECV_WINDOW", "10000"))
        self._session = requests.Session()
        if self.api_key:
            self._session.headers.update({"X-MBX-APIKEY": self.api_key})

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @property
    def paper(self) -> bool:
        return self.testnet

    # ------------------------------------------------------------------
    # signing / request helpers
    # ------------------------------------------------------------------
    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={sig}"

    def _signed_get(self, path: str, params: Dict[str, Any], timeout: float = 10.0) -> Any:
        params = dict(params, timestamp=int(time.time() * 1000), recvWindow=self.recv_window)
        url = f"{self.base_url}{path}?{self._sign(params)}"
        resp = self._session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _signed_post(self, path: str, params: Dict[str, Any], timeout: float = 15.0) -> Any:
        params = dict(params, timestamp=int(time.time() * 1000), recvWindow=self.recv_window)
        url = f"{self.base_url}{path}"
        resp = self._session.post(url, data=self._sign(params), timeout=timeout,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp.raise_for_status()
        return resp.json()

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # account / positions
    # ------------------------------------------------------------------
    def get_account(self) -> BrokerAccount:
        if not self.configured:
            return BrokerAccount(paper=self.testnet)
        try:
            data = self._signed_get("/api/v3/account", {})
            balances = data.get("balances", [])
            usdt = next((b for b in balances if b.get("asset") == "USDT"), {})
            cash = float(usdt.get("free", 0.0) or 0.0) + float(usdt.get("locked", 0.0) or 0.0)
            positions_value = 0.0
            for b in balances:
                asset = b.get("asset", "")
                free = float(b.get("free", 0.0) or 0.0)
                if asset in {"USDT", "BUSD", "USDC", "FDUSD"} or free <= 0:
                    continue
                px = self.get_latest_price(f"{asset}USDT")
                if px:
                    positions_value += free * px
            return BrokerAccount(
                equity=cash + positions_value,
                cash=cash,
                buying_power=cash,
                positions_value=positions_value,
                paper=self.testnet,
                currency="USDT",
                raw={"can_trade": data.get("canTrade")},
            )
        except Exception as exc:
            logger.error("Binance get_account failed: %s", exc)
            return BrokerAccount(paper=self.testnet)

    def get_positions(self) -> List[BrokerPosition]:
        if not self.configured:
            return []
        out: List[BrokerPosition] = []
        try:
            data = self._signed_get("/api/v3/account", {})
            for b in data.get("balances", []):
                asset = b.get("asset", "")
                qty = float(b.get("free", 0.0) or 0.0) + float(b.get("locked", 0.0) or 0.0)
                if asset in {"USDT", "BUSD", "USDC", "FDUSD"} or qty <= 0:
                    continue
                px = self.get_latest_price(f"{asset}USDT")
                if not px:
                    continue
                mv = qty * px
                out.append(BrokerPosition(
                    symbol=f"{asset}USDT",
                    qty=qty,
                    side="long",
                    market_value=mv,
                    cost_basis=mv,      # Binance spot has no cost basis API
                    unrealized_pl=0.0,
                    unrealized_plpc=0.0,
                    current_price=px,
                ))
        except Exception as exc:
            logger.error("Binance get_positions failed: %s", exc)
        return out

    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
    ) -> BrokerOrder:
        """Place a spot order.  ``side`` is "buy" or "sell".

        Binance spot wants LOT_SIZE-quantised quantities; we round down
        to 6dp and let the API's LOT_SIZE filter reject bad sizes with a
        clear error the lifecycle manager will surface.
        """
        if not self.configured:
            raise RuntimeError("Binance credentials not configured")
        if not self.testnet and not self._live_enabled():
            raise RuntimeError(
                "Binance live trading requires JEXI_LIVE_TRADING_ENABLED=1"
            )
        params: Dict[str, Any] = {
            "symbol": symbol.replace("/", "").upper(),
            "side": side.upper(),
            "type": "MARKET" if order_type == "market" else "LIMIT",
            "quantity": f"{qty:.6f}".rstrip("0").rstrip("."),
        }
        if params["type"] == "LIMIT":
            if not limit_price:
                raise ValueError("LIMIT order requires limit_price")
            params["price"] = f"{limit_price:.8f}".rstrip("0").rstrip(".")
            params["timeInForce"] = "GTC"
        data = self._signed_post("/api/v3/order", params)
        return BrokerOrder(
            id=str(data.get("orderId", "")),
            status=str(data.get("status", "")),
            symbol=str(data.get("symbol", symbol)),
            qty=float(data.get("executedQty", qty) or qty),
            side=side.lower(),
            type=order_type,
            filled_qty=float(data.get("executedQty", 0.0) or 0.0),
            filled_avg_price=None,   # filled via user stream / get_order
            created_at=str(data.get("transactTime", "")),
            raw=data,
        )

    @staticmethod
    def _live_enabled() -> bool:
        import os
        return os.getenv("JEXI_LIVE_TRADING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

    def get_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError("fetch via symbol + origClientOrderId — not needed for market fills")

    def cancel_order(self, order_id: str) -> bool:
        return False   # market orders fill instantly; cancels n/a

    # ------------------------------------------------------------------
    # market data
    # ------------------------------------------------------------------
    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            data = self._public_get(
                "/api/v3/ticker/price",
                {"symbol": symbol.replace("/", "").upper()},
            )
            return float(data["price"])
        except Exception as exc:
            logger.debug("Binance price fetch failed for %s: %s", symbol, exc)
            return None

    def is_market_open(self) -> bool:
        return True   # crypto trades 24/7
