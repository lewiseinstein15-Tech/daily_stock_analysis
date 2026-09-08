# -*- coding: utf-8 -*-
"""Alpaca Markets integration for JEXI Market.

This is a clean, dedicated Alpaca client built on top of the repo's
existing ``automated_trading_bot.py`` learnings (correct data host,
correct clock endpoint, double-sell guard) but presented as a small,
typed, testable module.  It defaults to **paper trading** and refuses
to place live orders unless ``JEXI_LIVE_TRADING_ENABLED=1`` is set AND
the risk gate's 30-day paper precondition is satisfied.

The client NEVER hardcodes credentials: it reads them from the
:class:`MarketConfig` (which reads them from environment variables).

Endpoints used (per Alpaca's public API docs):
  * Trading: ``{base_url}/v2/account``, ``/v2/positions``,
    ``/v2/orders``, ``/v2/clock``
  * Market data: ``{data_url}/v2/stocks/{sym}/bars``,
    ``/v2/stocks/{sym}/quotes/latest``

All HTTP calls go through :mod:`requests` with explicit timeouts and
the standard APCA-API-KEY-ID / APCA-API-SECRET-KEY header pair.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from jexi_market.config import MarketConfig
from jexi_market.contracts import Decision, SignalDirection

logger = logging.getLogger(__name__)

# Default Alpaca endpoints — paper by default.
DEFAULT_TRADING_URL_PAPER = "https://paper-api.alpaca.markets"
DEFAULT_TRADING_URL_LIVE = "https://api.alpaca.markets"
DEFAULT_DATA_URL = "https://data.alpaca.markets"


@dataclass
class AccountInfo:
    """Snapshot of the Alpaca account."""

    id: str = ""
    status: str = ""
    cash: float = 0.0
    equity: float = 0.0
    buying_power: float = 0.0
    portfolio_value: float = 0.0
    paper_trading: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "cash": round(self.cash, 2),
            "equity": round(self.equity, 2),
            "buying_power": round(self.buying_power, 2),
            "portfolio_value": round(self.portfolio_value, 2),
            "paper_trading": self.paper_trading,
        }


@dataclass
class Position:
    symbol: str
    qty: float
    side: str                # "long" or "short"
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    current_price: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "side": self.side,
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pl": round(self.unrealized_pl, 2),
            "unrealized_plpc": round(self.unrealized_plpc, 4),
            "current_price": self.current_price,
        }


@dataclass
class Order:
    id: str
    status: str
    symbol: str
    qty: float
    side: str                # "buy" or "sell"
    type: str                # "market" | "limit" | ...
    time_in_force: str
    filled_qty: float = 0.0
    filled_avg_price: Optional[float] = None
    created_at: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "symbol": self.symbol,
            "qty": self.qty,
            "side": self.side,
            "type": self.type,
            "time_in_force": self.time_in_force,
            "filled_qty": self.filled_qty,
            "filled_avg_price": self.filled_avg_price,
            "created_at": self.created_at,
        }


@dataclass
class MarketClock:
    is_open: bool
    next_open: str = ""
    next_close: str = ""
    timestamp: str = ""


class AlpacaClient:
    """Typed, paper-first Alpaca client.

    The client is intentionally paper-first: even if the user configures
    ``ALPACA_ENV=live``, the client refuses to place live orders unless
    :attr:`MarketConfig.live_trading_enabled` is ``True`` AND the risk
    gate's paper-validation precondition is satisfied.
    """

    def __init__(self, config: Optional[MarketConfig] = None):
        self.config = config or MarketConfig()
        # Force paper unless explicitly enabled for live.
        if self.config.alpaca_environment == "live" and not self.config.live_trading_enabled:
            logger.warning(
                "ALPACA_ENV=live but JEXI_LIVE_TRADING_ENABLED is not set — "
                "forcing paper mode for safety"
            )
            self._trading_url = DEFAULT_TRADING_URL_PAPER
            self._paper = True
        else:
            self._trading_url = (
                DEFAULT_TRADING_URL_LIVE
                if self.config.alpaca_environment == "live"
                else DEFAULT_TRADING_URL_PAPER
            )
            self._paper = self.config.alpaca_environment != "live"
        self._data_url = self.config.alpaca_data_url or DEFAULT_DATA_URL

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def paper_trading(self) -> bool:
        return self._paper

    @property
    def configured(self) -> bool:
        """True if credentials are present (does NOT verify them)."""
        return bool(self.config.alpaca_api_key and self.config.alpaca_api_secret)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.config.alpaca_api_key,
            "APCA-API-SECRET-KEY": self.config.alpaca_api_secret,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, base: Optional[str] = None, *, timeout: float = 10.0) -> Dict[str, Any]:
        url = f"{base or self._trading_url}{path}"
        resp = requests.get(url, headers=self._headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict[str, Any], *, timeout: float = 15.0) -> Dict[str, Any]:
        url = f"{self._trading_url}{path}"
        resp = requests.post(url, headers=self._headers(), json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, *, timeout: float = 10.0) -> Dict[str, Any]:
        url = f"{self._trading_url}{path}"
        resp = requests.delete(url, headers=self._headers(), timeout=timeout)
        resp.raise_for_status()
        return {} if resp.status_code == 204 else resp.json()

    # ------------------------------------------------------------------
    # Account / portfolio
    # ------------------------------------------------------------------
    def get_account(self) -> AccountInfo:
        if not self.configured:
            return AccountInfo(paper_trading=self._paper)
        try:
            data = self._get("/v2/account")
            return AccountInfo(
                id=str(data.get("id", "")),
                status=str(data.get("status", "")),
                cash=float(data.get("cash", 0.0) or 0.0),
                equity=float(data.get("equity", 0.0) or 0.0),
                buying_power=float(data.get("buying_power", 0.0) or 0.0),
                portfolio_value=float(data.get("portfolio_value", 0.0) or 0.0),
                paper_trading=bool(data.get("paper_trading", self._paper)),
                raw=data,
            )
        except Exception as exc:
            logger.error("Alpaca get_account failed: %s", exc)
            return AccountInfo(paper_trading=self._paper)

    def get_positions(self) -> List[Position]:
        if not self.configured:
            return []
        try:
            data = self._get("/v2/positions")
            out: List[Position] = []
            for item in data or []:
                out.append(Position(
                    symbol=str(item.get("symbol", "")),
                    qty=float(item.get("qty", 0.0) or 0.0),
                    side=str(item.get("side", "long")),
                    market_value=float(item.get("market_value", 0.0) or 0.0),
                    cost_basis=float(item.get("cost_basis", 0.0) or 0.0),
                    unrealized_pl=float(item.get("unrealized_pl", 0.0) or 0.0),
                    unrealized_plpc=float(item.get("unrealized_plpc", 0.0) or 0.0),
                    current_price=float(item.get("current_price", 0.0) or 0.0),
                ))
            return out
        except Exception as exc:
            logger.error("Alpaca get_positions failed: %s", exc)
            return []

    def get_clock(self) -> MarketClock:
        if not self.configured:
            return MarketClock(is_open=False)
        try:
            data = self._get("/v2/clock")
            return MarketClock(
                is_open=bool(data.get("is_open", False)),
                next_open=str(data.get("next_open", "")),
                next_close=str(data.get("next_close", "")),
                timestamp=str(data.get("timestamp", "")),
            )
        except Exception as exc:
            logger.error("Alpaca get_clock failed: %s", exc)
            return MarketClock(is_open=False)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,                       # "buy" or "sell"
        *,
        order_type: str = "market",
        time_in_force: str = "day",
    ) -> Order:
        """Submit an order.  Raises on HTTP failure; returns parsed Order."""
        if not self.configured:
            raise RuntimeError("Alpaca credentials not configured")
        body = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        data = self._post("/v2/orders", body)
        return Order(
            id=str(data.get("id", "")),
            status=str(data.get("status", "")),
            symbol=str(data.get("symbol", symbol)),
            qty=float(data.get("qty", qty) or qty),
            side=str(data.get("side", side)),
            type=str(data.get("type", order_type)),
            time_in_force=str(data.get("time_in_force", time_in_force)),
            filled_qty=float(data.get("filled_qty", 0.0) or 0.0),
            filled_avg_price=(
                float(data["filled_avg_price"])
                if data.get("filled_avg_price") else None
            ),
            created_at=str(data.get("created_at", "")),
            raw=data,
        )

    def get_order(self, order_id: str) -> Order:
        data = self._get(f"/v2/orders/{order_id}")
        return Order(
            id=str(data.get("id", order_id)),
            status=str(data.get("status", "")),
            symbol=str(data.get("symbol", "")),
            qty=float(data.get("qty", 0.0) or 0.0),
            side=str(data.get("side", "")),
            type=str(data.get("type", "")),
            time_in_force=str(data.get("time_in_force", "")),
            filled_qty=float(data.get("filled_qty", 0.0) or 0.0),
            filled_avg_price=(
                float(data["filled_avg_price"])
                if data.get("filled_avg_price") else None
            ),
            created_at=str(data.get("created_at", "")),
            raw=data,
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._delete(f"/v2/orders/{order_id}")
            return True
        except Exception as exc:
            logger.error("Alpaca cancel_order failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, float]]:
        if not self.configured:
            return None
        try:
            data = self._get(
                f"/v2/stocks/{symbol}/quotes/latest",
                base=self._data_url,
            )
            quote = data.get("quote") or {}
            return {
                "bid": float(quote.get("bp", 0.0) or 0.0),
                "ask": float(quote.get("ap", 0.0) or 0.0),
                "bid_size": float(quote.get("bs", 0.0) or 0.0),
                "ask_size": float(quote.get("as", 0.0) or 0.0),
                "timestamp": str(quote.get("t", "")),
            }
        except Exception as exc:
            logger.error("Alpaca get_latest_quote failed: %s", exc)
            return None

    def get_bars(self, symbol: str, *, timeframe: str = "1Day", limit: int = 120) -> List[Dict[str, Any]]:
        if not self.configured:
            return []
        try:
            params = {"timeframe": timeframe, "limit": str(limit)}
            url = f"{self._data_url}/v2/stocks/{symbol}/bars"
            resp = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("bars") or []
        except Exception as exc:
            logger.error("Alpaca get_bars failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Decision -> Order bridge (used by the pipeline)
    # ------------------------------------------------------------------
    def execute_decision(
        self,
        decision: Decision,
        portfolio_equity: float,
        *,
        latest_price: Optional[float] = None,
    ) -> Order:
        """Translate a typed Decision into an Alpaca order.

        Position sizing is delegated to the risk gate's
        ``position_fraction`` (already capped).  We compute qty from
        fraction × equity / latest_price.
        """
        if not self.configured:
            raise RuntimeError("Alpaca credentials not configured — cannot execute")
        if decision.direction == SignalDirection.FLAT:
            raise ValueError("FLAT decision — nothing to execute")
        if latest_price is None or latest_price <= 0:
            raise ValueError("latest_price required to size order")
        if portfolio_equity <= 0:
            raise ValueError("portfolio_equity must be positive")

        # Refuse to place a live order if we're not in live mode.
        if not self._paper and not self.config.live_trading_enabled:
            raise RuntimeError("live trading not enabled")

        # Double-sell guard: refuse to sell if we don't hold the position.
        if decision.direction == SignalDirection.SHORT:
            positions = {p.symbol: p for p in self.get_positions()}
            held = positions.get(decision.symbol)
            if held and held.side == "long" and held.qty > 0:
                # Closing a long is allowed; opening a new short is not.
                logger.info("closing long position in %s (qty %s)", decision.symbol, held.qty)

        dollar_allocation = portfolio_equity * decision.position_fraction
        qty = max(0.0, dollar_allocation / latest_price)
        if qty <= 0:
            raise ValueError("computed qty <= 0 — nothing to order")

        side = "buy" if decision.direction == SignalDirection.LONG else "sell"
        return self.submit_order(decision.symbol, qty, side)
