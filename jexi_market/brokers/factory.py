# -*- coding: utf-8 -*-
"""Broker factory — env-driven adapter selection.

``JEXI_BROKER`` picks the venue.  **Default is ``auto``**: JEXI looks at
whatever credentials are present in the environment (GitHub Actions
secrets, .env, docker env, ...) and picks the best broker it finds — so
the same image runs against ANY market without code changes:

======================  ==============================================
JEXI_BROKER             Adapter
======================  ==============================================
``auto`` (default)      detect from env (first match below)
``alpaca``              Alpaca paper/live (ALPACA_API_KEY/SECRET)
``paper``               Offline SQLite simulator (no credentials)
``binance``             Binance spot (BINANCE_API_KEY/SECRET)
``pocketoption``        Pocket Option (POCKET_OPTION_SSID)
``mt5``                 MetaTrader 5 (MT5_LOGIN/PASSWORD/SERVER)
======================  ==============================================

Auto-detection order matches credential specificity: Alpaca → Binance
→ Pocket Option → MT5 → paper simulator.  Explicit ``JEXI_BROKER``
always wins over auto-detection.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker
from jexi_market.config import MarketConfig

logger = logging.getLogger(__name__)


def available_brokers() -> List[str]:
    return ["auto", "alpaca", "paper", "binance", "pocketoption", "mt5"]


# (broker name, [(env var, env var), ...]) — all vars in a group must be
# non-empty for that broker to be considered configured.
_BROKER_ENV_SIGNATURES = [
    ("alpaca", ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_SECRET_KEY")),
    ("binance", ("BINANCE_API_KEY", "BINANCE_API_SECRET")),
    ("pocketoption", ("POCKET_OPTION_SSID",)),
    ("mt5", ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER")),
]


def detect_configured_broker(env: Optional[Dict[str, str]] = None) -> tuple:
    """Return (broker_name, reason) for the first broker whose credentials
    are present in the environment.  Falls back to ('paper', ...).

    Groups use OR within a group for fallback aliases (e.g. ALPACA_SECRET
    is accepted for ALPACA_API_SECRET) and AND across the group's
    *distinct* credential slots.
    """
    environ = env if env is not None else os.environ

    def _has(name: str) -> bool:
        return bool((environ.get(name) or "").strip())

    # Alpaca: key + (secret under either name)
    if _has("ALPACA_API_KEY") and (_has("ALPACA_API_SECRET") or _has("ALPACA_SECRET_KEY")):
        return "alpaca", "ALPACA_API_KEY and secret found in environment"
    if _has("BINANCE_API_KEY") and _has("BINANCE_API_SECRET"):
        return "binance", "BINANCE_API_KEY and BINANCE_API_SECRET found in environment"
    if _has("POCKET_OPTION_SSID"):
        return "pocketoption", "POCKET_OPTION_SSID found in environment"
    if _has("MT5_LOGIN") and _has("MT5_PASSWORD") and _has("MT5_SERVER"):
        return "mt5", "MT5_LOGIN/PASSWORD/SERVER found in environment"
    return "paper", "no broker credentials found in environment — using offline paper simulator"


def _resolve_broker_name(explicit: str, env: Optional[Dict[str, str]] = None) -> tuple:
    chosen = (explicit or "auto").strip().lower()
    if chosen == "auto" or not chosen:
        name, reason = detect_configured_broker(env)
        logger.info("JEXI_BROKER=auto -> %s (%s)", name, reason)
        return name, reason
    if chosen not in available_brokers():
        logger.warning("unknown JEXI_BROKER %r — using 'alpaca'", chosen)
        return "alpaca", f"unknown broker {chosen!r} requested — fell back to alpaca"
    return chosen, f"explicitly selected via JEXI_BROKER"


def build_broker(config: Optional[MarketConfig] = None, *, name: str = "") -> Broker:
    """Construct the broker named by ``JEXI_BROKER`` (or ``name``).

    ``auto`` (the default) detects whichever broker's credentials are in
    the environment, so dropping API keys into GitHub secrets / .env is
    enough to point JEXI at a new market.  Unknown names fall back to
    ``alpaca`` with a warning so a typo can never take the whole 24/7
    runner down.
    """
    cfg = config or MarketConfig()
    import os as _os
    chosen, _reason = _resolve_broker_name(
        name or _os.getenv("JEXI_BROKER", "auto"), None)

    if chosen == "paper":
        from jexi_market.brokers.paper import PaperBroker
        return PaperBroker(
            _os.getenv("JEXI_PAPER_BROKER_DB", "data/jexi_market/paper_broker.sqlite"),
            starting_cash=float(_os.getenv("JEXI_PAPER_STARTING_CASH", "100000")),
            price_provider=_os.getenv("JEXI_PAPER_PRICE_PROVIDER", "") or None,
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
        if name == "auto":
            detected, reason = detect_configured_broker()
            out[name] = {"broker": "auto", "detected": detected, "reason": reason}
            continue
        try:
            b = build_broker(config, name=name)
            out[name] = b.status()
        except Exception as exc:
            out[name] = {"broker": name, "error": str(exc)}
    return out
