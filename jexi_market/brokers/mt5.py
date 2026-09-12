# -*- coding: utf-8 -*-
"""MetaTrader 5 adapter (optional ``MetaTrader5`` package).

Bridges JEXI Market to any MT5 broker (forex, CFDs, indices, crypto
CFDs) through the official Python integration.  The package only works
on Windows/macOS-Wine with a running MT5 terminal, so every import is
guarded and the adapter degrades to ``configured=False`` with a clear
message when unavailable.

Config (environment):
* ``MT5_LOGIN``      — account number (required)
* ``MT5_PASSWORD``   — account password (required)
* ``MT5_SERVER``     — broker server name, e.g. ``ICMarketsSC-Demo`` (required)
* ``MT5_PATH``       — optional explicit path to terminal64.exe
"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

from jexi_market.brokers.base import Broker, BrokerAccount, BrokerOrder, BrokerPosition

logger = logging.getLogger(__name__)


class MT5Broker(Broker):
    """MetaTrader 5 desktop-terminal bridge."""

    name = "mt5"
    supports_bracket_orders = True   # MT5 orders take sl/tp natively

    def __init__(self, config: Optional[Any] = None):
        import os
        self.login = os.getenv("MT5_LOGIN", "")
        self.password = os.getenv("MT5_PASSWORD", "")
        self.server = os.getenv("MT5_SERVER", "")
        self.path = os.getenv("MT5_PATH", "") or None
        self._lock = threading.Lock()
        self._initialized = False
        self._mt5 = None

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        if not (self.login and self.password and self.server):
            return False
        try:
            import MetaTrader5  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "MT5Broker: 'MetaTrader5' package not installed — "
                "run `pip install MetaTrader5` (Windows) to enable"
            )
            return False

    @property
    def paper(self) -> bool:
        # MT5 demo accounts are indistinguishable by API; assume live
        # (the risk gate's live precondition still applies separately).
        return False

    def _ensure(self):
        if self._initialized:
            return self._mt5
        import MetaTrader5 as mt5
        kwargs: dict = {
            "login": int(self.login),
            "password": self.password,
            "server": self.server,
        }
        if self.path:
            kwargs["path"] = self.path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._mt5 = mt5
        self._initialized = True
        return mt5

    # ------------------------------------------------------------------
    def get_account(self) -> BrokerAccount:
        try:
            with self._lock:
                mt5 = self._ensure()
                info = mt5.account_info()
            if info is None:
                return BrokerAccount(paper=False)
            return BrokerAccount(
                equity=float(info.equity),
                cash=float(info.balance),
                buying_power=float(info.margin_free),
                positions_value=float(info.equity - info.balance),
                paper=info.trade_mode != 0,   # 0=real, 1=demo usually
                currency=info.currency,
            )
        except Exception as exc:
            logger.error("MT5 get_account failed: %s", exc)
            return BrokerAccount(paper=False)

    def get_positions(self) -> List[BrokerPosition]:
        try:
            with self._lock:
                mt5 = self._ensure()
                positions = mt5.positions_get() or []
            out = []
            for p in positions:
                out.append(BrokerPosition(
                    symbol=p.symbol,
                    qty=float(p.volume),
                    side="long" if p.type == 0 else "short",
                    market_value=float(p.price_current * p.volume),
                    cost_basis=float(p.price_open * p.volume),
                    unrealized_pl=float(p.profit),
                    unrealized_plpc=(p.profit / (p.price_open * p.volume)) if p.volume else 0.0,
                    current_price=float(p.price_current),
                ))
            return out
        except Exception as exc:
            logger.error("MT5 get_positions failed: %s", exc)
            return []

    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> BrokerOrder:
        with self._lock:
            mt5 = self._ensure()
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise RuntimeError(f"MT5 unknown symbol: {symbol}")
            price = tick.ask if side == "buy" else tick.bid
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(qty),
                "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
                "price": float(price),
                "deviation": 20,
                "magic": 20260912,
                "comment": "jexi-market",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            if stop_loss:
                request["sl"] = float(stop_loss)
            if take_profit:
                request["tp"] = float(take_profit)
            result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(result, "retcode", "None")
            raise RuntimeError(f"MT5 order_send failed: retcode={code}")
        return BrokerOrder(
            id=str(result.order), status="filled", symbol=symbol,
            qty=float(qty), side=side, type="market",
            filled_qty=float(qty), filled_avg_price=float(result.price or price),
        )

    def get_order(self, order_id: str) -> BrokerOrder:
        with self._lock:
            mt5 = self._ensure()
            orders = mt5.orders_get(ticket=int(order_id)) or []
        if not orders:
            raise KeyError(order_id)
        o = orders[0]
        return BrokerOrder(id=str(o.ticket), status="open", symbol=o.symbol,
                           qty=float(o.volume_current), side="buy" if o.type == 0 else "sell")

    def cancel_order(self, order_id: str) -> bool:
        return False

    def close_position(self, symbol: str) -> Optional[BrokerOrder]:
        try:
            with self._lock:
                mt5 = self._ensure()
                positions = [p for p in (mt5.positions_get(symbol=symbol) or [])]
                tick = mt5.symbol_info_tick(symbol)
            if not positions or tick is None:
                return None
            p = positions[0]
            is_long = p.type == 0
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(p.volume),
                "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
                "position": p.ticket,
                "price": float(tick.bid if is_long else tick.ask),
                "deviation": 20,
                "magic": 20260912,
                "comment": "jexi-market-close",
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                return None
            return BrokerOrder(id=str(result.order), status="filled", symbol=symbol,
                               qty=float(p.volume), side="sell" if is_long else "buy",
                               filled_avg_price=float(result.price or 0.0))
        except Exception as exc:
            logger.error("MT5 close_position failed: %s", exc)
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            with self._lock:
                mt5 = self._ensure()
                tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            return float((tick.bid + tick.ask) / 2.0)
        except Exception as exc:
            logger.debug("MT5 price fetch failed for %s: %s", symbol, exc)
            return None

    def is_market_open(self) -> bool:
        return True   # venue hours vary; runner checks per-asset-class too
