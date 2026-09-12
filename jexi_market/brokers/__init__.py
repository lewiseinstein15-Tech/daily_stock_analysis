# -*- coding: utf-8 -*-
"""Unified broker abstraction for JEXI Market (v0.3).

Every broker adapter implements :class:`Broker`, so the pipeline,
runner and risk layers are broker-agnostic:

    from jexi_market.brokers import build_broker
    broker = build_broker(config)          # env-driven
    broker.get_account(); broker.submit_order(...)

Adapters included:

* ``alpaca``        — US equities/crypto, paper + live (the default).
* ``paper``         — fully offline, SQLite-persisted simulator with
                      local stop-loss / take-profit management.
* ``binance``       — Binance spot (testnet by default), HMAC-signed REST.
* ``pocketoption``  — Pocket Option via the community SSID websocket
                      protocol (unofficial — may break; demo account by
                      default; binary options are high risk).
* ``mt5``           — MetaTrader 5 desktop bridge (optional package).

Safety rules inherited by every adapter:
* credentials only from environment / MarketConfig — never hardcoded;
* live trading requires the explicit ``JEXI_LIVE_TRADING_ENABLED`` flag
  (checked again at order time, not just at construction);
* adapters degrade to ``configured=False`` instead of raising when their
  dependency or credentials are missing.
"""

from jexi_market.brokers.base import (
    Broker,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    BrokerUnavailable,
)
from jexi_market.brokers.factory import build_broker, available_brokers

__all__ = [
    "Broker",
    "BrokerAccount",
    "BrokerOrder",
    "BrokerPosition",
    "BrokerUnavailable",
    "build_broker",
    "available_brokers",
]
