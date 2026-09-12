# -*- coding: utf-8 -*-
"""Broker factory — env-driven adapter selection.

``JEXI_BROKER`` picks the venue (default ``alpaca``):

======================  ==============================================
JEXI_BROKER             Adapter
======================  ==============================================
``alpaca``              Alpaca paper/live (needs ALPACA_API_KEY/SECRET)
``paper``               Offline SQLite simulator (no credentials)
``binance``             Binance spot (testnet by default)
``pocketoption``        Pocket Option (unofficial SSID websocket)
``mt5``                 MetaTrader 5 desktop bridge
======================  ==============================================
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker
from jexi_market.config import MarketConfig

logger = logging.getLogger(__name__)


def available_brokers() -> List[str]:
    return ["alpaca", "paper", "binance", "pocketoption", "mt5"]


def build_broker(config: Optional[MarketConfig] = None, *, name: str = "") -> Broker:
    """Construct the broker named by ``JEXI_BROKER`` (or ``name``).

    Unknown names fall back to ``alpaca`` with a warning so a typo can
    never take the whole 24/7 runner down.
    """
    cfg = config or MarketConfig()
    import os
    chosen = (name or os.getenv("JEXI_BROKER", "alpaca")).strip().lower()
    if chosen not in available_brokers():
        logger.warning("unknown JEXI_BROKER %r — using 'alpaca'", chosen)
        chosen = "alpaca"

    if chosen == "paper":
        from jexi_market.brokers.paper import PaperBroker
        return PaperBroker(
            os.getenv("JEXI_PAPER_BROKER_DB", "data/jexi_market/paper_broker.sqlite"),
            starting_cash=float(os.getenv("JEXI_PAPER_STARTING_CASH", "100000")),
            price_provider=os.getenv("JEXI_PAPER_PRICE_PROVIDER", "") or None,
        )
    if chosen == "binance":
        from jexi_market.brokers.binance import BinanceBroker
        return BinanceBroker(cfg)
    if chosen == "pocketoption":
        from jexi_market.brokers.pocketoption import PocketOptionBroker
        return PocketOptionBroker(cfg)
    if chosen == "mt5":
        from jexi_market.brokers.mt5 import MT5Broker
        return MT5Broker(cfg)
    # default: alpaca
    from jexi_market.brokers.alpaca_broker import AlpacaBroker
    return AlpacaBroker(cfg)


def broker_status(config: Optional[MarketConfig] = None) -> Dict[str, Any]:
    """Build a status dict for every adapter (for `jexi-market brokers`)."""
    out: Dict[str, Any] = {}
    for name in available_brokers():
        try:
            b = build_broker(config, name=name)
            out[name] = b.status()
        except Exception as exc:
            out[name] = {"broker": name, "error": str(exc)}
    return out
