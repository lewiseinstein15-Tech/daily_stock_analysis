# -*- coding: utf-8 -*-
"""Alpaca adapter — wraps the repo's hardened :class:`AlpacaClient`."""

from __future__ import annotations

import logging
from typing import List, Optional

from jexi_market.brokers.base import Broker, BrokerAccount, BrokerOrder, BrokerPosition
from jexi_market.config import MarketConfig
from jexi_market.execution import AlpacaClient

logger = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    """US equities + crypto via Alpaca (paper by default, live gated)."""

    name = "alpaca"
    supports_bracket_orders = True   # Alpaca native bracket (entry+stop+TP)

    def __init__(self, config: Optional[MarketConfig] = None):
        self.config = config or MarketConfig()
        self._client = AlpacaClient(self.config)

    @property
    def configured(self) -> bool:
        return self._client.configured

    @property
    def paper(self) -> bool:
        return self._client.paper_trading

    def get_account(self) -> BrokerAccount:
        acct = self._client.get_account()
        return BrokerAccount(
            equity=acct.equity,
            cash=acct.cash,
            buying_power=acct.buying_power,
            positions_value=acct.portfolio_value - acct.cash if acct.portfolio_value else 0.0,
            paper=acct.paper_trading,
            raw=acct.raw,
        )

    def get_positions(self) -> List[BrokerPosition]:
        return [
            BrokerPosition(
                symbol=p.symbol,
                qty=p.qty,
                side=p.side,
                market_value=p.market_value,
                cost_basis=p.cost_basis,
                unrealized_pl=p.unrealized_pl,
                unrealized_plpc=p.unrealized_plpc,
                current_price=p.current_price,
            )
            for p in self._client.get_positions()
        ]

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
        o = self._client.submit_order(
            symbol, qty, side,
            order_type=order_type,
            time_in_force=time_in_force,
            limit_price=limit_price,
        )
        return BrokerOrder(
            id=o.id, status=o.status, symbol=o.symbol, qty=o.qty, side=o.side,
            type=o.type, filled_qty=o.filled_qty, filled_avg_price=o.filled_avg_price,
            created_at=o.created_at, raw=o.raw,
        )

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
        """Alpaca native bracket: entry market order with stop/limit legs.

        Falls back to a plain order (exits managed locally by the
        lifecycle manager) when no legs are provided or the API rejects
        the bracket payload.
        """
        if not (stop_loss and take_profit) or not self.configured:
            return self.submit_order(symbol, qty, side, time_in_force=time_in_force)
        body = {
            "symbol": symbol,
            "qty": self._client_fmt_qty(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day" if time_in_force == "day" else time_in_force,
            "order_class": "bracket",
            "order_type": "market",
            "stop_loss": {"stop_price": f"{round(stop_loss, 2)}"},
            "take_profit": {"limit_price": f"{round(take_profit, 2)}"},
        }
        try:
            data = self._client._post("/v2/orders", body)
            return BrokerOrder(
                id=str(data.get("id", "")),
                status=str(data.get("status", "")),
                symbol=str(data.get("symbol", symbol)),
                qty=float(data.get("qty", qty) or qty),
                side=str(data.get("side", side)),
                type="bracket",
                filled_qty=float(data.get("filled_qty", 0.0) or 0.0),
                filled_avg_price=(
                    float(data["filled_avg_price"]) if data.get("filled_avg_price") else None
                ),
                created_at=str(data.get("created_at", "")),
                raw=data,
            )
        except Exception as exc:
            logger.warning("bracket order rejected for %s (%s) — falling back to plain order", symbol, exc)
            return self.submit_order(symbol, qty, side, time_in_force=time_in_force)

    @staticmethod
    def _client_fmt_qty(qty: float) -> str:
        from jexi_market.execution.alpaca import _format_qty
        return _format_qty(qty)

    def get_order(self, order_id: str) -> BrokerOrder:
        o = self._client.get_order(order_id)
        return BrokerOrder(
            id=o.id, status=o.status, symbol=o.symbol, qty=o.qty, side=o.side,
            type=o.type, filled_qty=o.filled_qty, filled_avg_price=o.filled_avg_price,
            created_at=o.created_at, raw=o.raw,
        )

    def cancel_order(self, order_id: str) -> bool:
        return self._client.cancel_order(order_id)

    def get_latest_price(self, symbol: str) -> Optional[float]:
        quote = self._client.get_latest_quote(symbol)
        if not quote:
            return None
        mid = 0.0
        if quote.get("bid") and quote.get("ask"):
            mid = (quote["bid"] + quote["ask"]) / 2.0
        return mid or None

    def is_market_open(self) -> bool:
        return self._client.get_clock().is_open

    def status(self):
        base = super().status()
        base["endpoints"] = {
            "paper": self._client._trading_url,
        }
        return base
