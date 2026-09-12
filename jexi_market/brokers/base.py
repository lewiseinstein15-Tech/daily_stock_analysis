# -*- coding: utf-8 -*-
"""Broker ABC + shared value types.

Every adapter (Alpaca, Paper, Binance, PocketOption, MT5) implements
this interface.  The pipeline only ever talks to :class:`Broker`, which
is what makes JEXI Market portable across venues.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class BrokerUnavailable(RuntimeError):
    """Raised when a broker adapter cannot be used (missing creds/dep)."""


@dataclass
class BrokerAccount:
    """Snapshot of the trading account at the broker."""

    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    positions_value: float = 0.0
    paper: bool = True
    currency: str = "USD"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "buying_power": round(self.buying_power, 2),
            "positions_value": round(self.positions_value, 2),
            "paper": self.paper,
            "currency": self.currency,
        }


@dataclass
class BrokerPosition:
    """One open position at the broker."""

    symbol: str
    qty: float
    side: str                    # "long" | "short"
    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_plpc: float = 0.0
    current_price: float = 0.0

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
class BrokerOrder:
    """An order (submitted or historical) at the broker."""

    id: str
    status: str
    symbol: str
    qty: float
    side: str                    # "buy" | "sell"
    type: str = "market"         # "market" | "limit" | "bracket" ...
    filled_qty: float = 0.0
    filled_avg_price: Optional[float] = None
    created_at: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def filled(self) -> bool:
        return self.status in {"filled", "closed", "win", "loss"} or (
            self.filled_qty > 0 and self.filled_avg_price
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "symbol": self.symbol,
            "qty": self.qty,
            "side": self.side,
            "type": self.type,
            "filled_qty": self.filled_qty,
            "filled_avg_price": self.filled_avg_price,
            "created_at": self.created_at,
        }


class Broker(ABC):
    """Abstract broker interface — the *only* trading surface the
    pipeline is allowed to use."""

    name: str = "abstract"
    supports_bracket_orders: bool = False   # stop/TP placed with the entry

    # -- lifecycle ------------------------------------------------------
    @property
    @abstractmethod
    def configured(self) -> bool:
        """True when the adapter has everything it needs to trade."""

    @property
    def paper(self) -> bool:
        """True when the adapter is not connected to real money."""
        return True

    # -- account / positions ---------------------------------------------
    @abstractmethod
    def get_account(self) -> BrokerAccount: ...

    @abstractmethod
    def get_positions(self) -> List[BrokerPosition]: ...

    # -- orders -----------------------------------------------------------
    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
    ) -> BrokerOrder: ...

    @abstractmethod
    def get_order(self, order_id: str) -> BrokerOrder: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        time_in_force: str = "day",
    ) -> BrokerOrder:
        """Entry order with attached stop-loss / take-profit legs.

        Default implementation: place a plain market order and let the
        caller manage exits locally (the lifecycle manager does this).
        Adapters with native brackets (Alpaca) override it.
        """
        return self.submit_order(symbol, qty, side, time_in_force=time_in_force)

    def close_position(self, symbol: str) -> Optional[BrokerOrder]:
        """Flatten one symbol (market order against the held side)."""
        for pos in self.get_positions():
            if pos.symbol == symbol and pos.qty > 0:
                side = "sell" if pos.side == "long" else "buy"
                return self.submit_order(symbol, pos.qty, side)
        return None

    # -- market data --------------------------------------------------------
    @abstractmethod
    def get_latest_price(self, symbol: str) -> Optional[float]: ...

    def is_market_open(self) -> bool:
        """Default: assume always open (crypto). Equity adapters override."""
        return True

    # -- introspection -----------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Redacted status for /status endpoints and logs."""
        return {
            "broker": self.name,
            "configured": self.configured,
            "paper": self.paper,
            "bracket_orders": self.supports_bracket_orders,
        }
