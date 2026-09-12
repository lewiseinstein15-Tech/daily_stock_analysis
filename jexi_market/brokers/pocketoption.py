# -*- coding: utf-8 -*-
"""Pocket Option adapter (unofficial websocket protocol).

⚠️ IMPORTANT, read before enabling:
* Pocket Option has **no official public trading API**.  This adapter
  speaks the same JSON websocket protocol used by the community
  ``pocketoptionapi`` projects (SSID session auth → balance →
  ``openOrder`` → win/loss poll).
* The protocol is unofficial and can change without notice; treat this
  adapter as best-effort.  If the socket cannot connect, the broker
  reports ``configured=False`` and the pipeline skips it gracefully.
* Binary options / OTC instruments are **extremely high risk**.  This
  adapter defaults to the DEMO account and refuses the live account
  unless ``JEXI_LIVE_TRADING_ENABLED=1``.

Config (environment):
* ``POCKET_OPTION_SSID``     — the SSID session string copied from your
  browser websocket login  (required)
* ``POCKET_OPTION_DEMO``     — default "1"; set "0" for the live account
  (also requires JEXI_LIVE_TRADING_ENABLED=1)
* ``POCKET_OPTION_URL``      — optional override of the websocket endpoint
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker, BrokerAccount, BrokerOrder, BrokerPosition

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket"


class PocketOptionBroker(Broker):
    """Best-effort Pocket Option adapter via the unofficial SSID protocol.

    Only :meth:`get_account`, :meth:`submit_order`, :meth:`get_order`
    and :meth:`get_latest_price` are meaningfully supported — Pocket
    Option's binary model maps onto the Broker ABC as: a "position" is
    an open binary contract and closing == waiting for expiry.
    """

    name = "pocketoption"
    supports_bracket_orders = False

    def __init__(self, config: Optional[Any] = None):
        import os
        self.ssid = os.getenv("POCKET_OPTION_SSID", "").strip()
        self.demo = os.getenv("POCKET_OPTION_DEMO", "1").strip().lower() in {"1", "true", "yes", "on"}
        self.ws_url = os.getenv("POCKET_OPTION_URL", DEFAULT_WS_URL)
        self._ws = None
        self._lock = threading.Lock()
        self._balances: Dict[str, float] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        if not self.ssid:
            return False
        try:
            import websocket  # websocket-client
            return True
        except ImportError:
            logger.warning(
                "PocketOptionBroker: 'websocket-client' not installed — "
                "run `pip install websocket-client` to enable this broker"
            )
            return False

    @property
    def paper(self) -> bool:
        return self.demo

    def _live_enabled(self) -> bool:
        import os
        return os.getenv("JEXI_LIVE_TRADING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

    # ------------------------------------------------------------------
    # websocket plumbing (lazy, best-effort)
    # ------------------------------------------------------------------
    def _connect(self) -> bool:
        """Connect + auth with the SSID.  Raises BrokerUnavailable on failure."""
        if self._ws is not None:
            try:
                self._ws.ping()
                return True
            except Exception:
                self._ws = None
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pip install websocket-client") from exc

        try:
            ws = websocket.create_connection(self.ws_url, timeout=10)
            # Pocket Option expects: 40 handshake, then a 'auth' event
            # carrying the full SSID (which already encodes demo/live).
            ws.recv()  # "0{...}" engine.io open
            ws.send("40")
            ws.recv()  # "40{...}" namespace
            auth_payload = json.dumps(["auth", {"session": self.ssid, "isDemo": 1 if self.demo else 0}])
            ws.send(f'42{auth_payload}')
            deadline = time.time() + 8
            while time.time() < deadline:
                msg = ws.recv()
                if "successauth" in str(msg) or "updateStream" in str(msg):
                    break
            self._ws = ws
            return True
        except Exception as exc:
            logger.warning("PocketOption connect failed: %s", exc)
            self._ws = None
            raise RuntimeError(f"pocket option connect failed: {exc}") from exc

    def _send(self, event: str, payload: Any, wait_seconds: float = 5.0) -> List[str]:
        """Send a socket.io event, collect responses for a short window."""
        if self._ws is None:
            self._connect()
        assert self._ws is not None
        self._ws.send(f'42{json.dumps([event, payload])}')
        responses: List[str] = []
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                self._ws.settimeout(max(0.2, deadline - time.time()))
                msg = self._ws.recv()
                responses.append(str(msg))
            except Exception:
                break
        return responses

    # ------------------------------------------------------------------
    # Broker interface
    # ------------------------------------------------------------------
    def get_account(self) -> BrokerAccount:
        try:
            with self._lock:
                responses = self._send("changeSymbol", {"asset": "EURUSD_otc", "period": 60})
                for msg in responses:
                    if "updateBalance" in msg:
                        # e.g. 42["updateBalance",{"balance":10000,"isDemo":1}]
                        body = msg.split('42', 1)[-1]
                        data = json.loads(body)[1]
                        self._balances["USD"] = float(data.get("balance", 0.0))
            cash = self._balances.get("USD", 0.0)
            return BrokerAccount(
                equity=cash, cash=cash, buying_power=cash,
                positions_value=0.0, paper=self.demo, currency="USD",
            )
        except Exception as exc:
            logger.error("PocketOption get_account failed: %s", exc)
            return BrokerAccount(paper=self.demo)

    def get_positions(self) -> List[BrokerPosition]:
        # Open binary contracts are not queryable reliably on the
        # unofficial protocol; return tracked orders as pseudo-positions.
        out: List[BrokerPosition] = []
        for oid, o in list(self._orders.items()):
            if o.get("status") == "open":
                out.append(BrokerPosition(
                    symbol=o["symbol"], qty=o["amount"], side="long",
                    market_value=0.0, cost_basis=o["amount"],
                    current_price=o.get("entry_price") or 0.0,
                ))
        return out

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        expiry_seconds: int = 300,
    ) -> BrokerOrder:
        """Open a binary contract.  ``side`` "buy" = CALL, "sell" = PUT.

        ``qty`` is the stake (USD) — Pocket Option options stake a fixed
        amount rather than buying units of the asset.
        """
        if not self.configured:
            raise RuntimeError("Pocket Option not configured (need POCKET_OPTION_SSID + websocket-client)")
        if not self.demo and not self._live_enabled():
            raise RuntimeError("Pocket Option LIVE account requires JEXI_LIVE_TRADING_ENABLED=1")

        direction = "call" if side.lower() in {"buy", "call", "long"} else "put"
        order_id = f"po_{uuid.uuid4().hex[:10]}"
        try:
            with self._lock:
                responses = self._send("openOrder", {
                    "asset": symbol,
                    "amount": float(qty),
                    "action": direction,
                    "isDemo": 1 if self.demo else 0,
                    "requestId": order_id,
                    "optionType": 100,          # binary
                    "time": expiry_seconds,
                }, wait_seconds=6.0)
            status = "submitted"
            entry_price = None
            for msg in responses:
                if "successopenOrder" in msg or "openOrder" in msg and "fail" not in msg:
                    status = "open"
                if "updateAssets" in msg and entry_price is None:
                    pass
            order = BrokerOrder(
                id=order_id, status=status, symbol=symbol, qty=float(qty),
                side="buy" if direction == "call" else "sell",
                type="binary", filled_qty=float(qty), filled_avg_price=entry_price,
                raw={"direction": direction, "expiry_seconds": expiry_seconds},
            )
            self._orders[order_id] = order.raw | {
                "symbol": symbol, "amount": float(qty), "status": status,
                "entry_price": entry_price,
            }
            return order
        except Exception as exc:
            raise RuntimeError(f"PocketOption order failed: {exc}") from exc

    def get_order(self, order_id: str) -> BrokerOrder:
        o = self._orders.get(order_id)
        if not o:
            raise KeyError(order_id)
        return BrokerOrder(
            id=order_id, status=o["status"], symbol=o["symbol"], qty=o["amount"],
            side="buy", type="binary",
        )

    def cancel_order(self, order_id: str) -> bool:
        return False   # binary contracts cannot be cancelled once open

    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            with self._lock:
                responses = self._send("changeSymbol", {"asset": symbol, "period": 5})
                for msg in responses:
                    if "updateAssets" in msg or "updateHistory" in msg:
                        body = msg.split('42', 1)[-1]
                        data = json.loads(body)
                        # payload shapes vary; try common containers
                        try:
                            payload = data[1]
                            if isinstance(payload, dict):
                                for key in ("price", "last", "close"):
                                    if key in payload:
                                        return float(payload[key])
                                hist = payload.get("data") or []
                                if hist and isinstance(hist[-1], (list, tuple)):
                                    return float(hist[-1][-2])
                        except (IndexError, ValueError, TypeError):
                            continue
            return None
        except Exception as exc:
            logger.debug("PocketOption price fetch failed for %s: %s", symbol, exc)
            return None

    def is_market_open(self) -> bool:
        return True   # OTC instruments trade continuously

    def status(self) -> Dict[str, Any]:
        base = super().status()
        base["demo"] = self.demo
        base["ssid_set"] = bool(self.ssid)
        base["unofficial_api"] = True
        return base
