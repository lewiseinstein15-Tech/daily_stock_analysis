# -*- coding: utf-8 -*-
"""Bridge between the JEXI runner and the user's Jexi app account.

The Jexi app is the single home for everything:

* Broker + AI keys are saved by the user in the app (Settings -> Keys),
  encrypted on the Jexi server.  The runner pulls them at start time with
  the shared agent secret — nothing sensitive is stored in GitHub.
* The account's mode (paper / live) is decided in the app too.  When the
  user flips to live with Alpaca-live keys, the runner is allowed to trade
  live; otherwise it stays on paper.
* Every report the runner produces is pushed into the app's notification
  feed (see :mod:`jexi_market.notifications.app`) — no ntfy, no external
  app needed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def app_configured(config) -> bool:
    """True when the runner is wired to a Jexi app account."""
    server = (getattr(config, "jexi_app_server", "") or "").strip()
    secret = (getattr(config, "jexi_app_agent_secret", "") or "").strip()
    email = (getattr(config, "jexi_app_email", "") or "").strip()
    return bool(server and secret and email)


def _server(config) -> str:
    return (config.jexi_app_server or "").strip().rstrip("/")


def _headers(config) -> Dict[str, str]:
    return {"x-agent-secret": (config.jexi_app_agent_secret or "").strip()}


def fetch_account(config) -> Optional[Dict[str, Any]]:
    """Pull the account payload (keys + mode) for the configured email."""
    if not app_configured(config):
        return None
    email = (config.jexi_app_email or "").strip()
    try:
        resp = requests.get(
            f"{_server(config)}/api/agent/keys",
            params={"email": email},
            headers=_headers(config),
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("jexi app: key fetch failed with HTTP %s", resp.status_code)
            return None
        return resp.json()
    except requests.exceptions.RequestException as exc:
        logger.warning("jexi app: key fetch error %s", type(exc).__name__)
        return None


def apply_account_keys(config) -> bool:
    """Load the user's saved broker + AI keys into the runtime config.

    Returns True when the app was reachable (keys loaded, or the account
    simply has none yet).  False means "not configured / unreachable" and
    the runner falls back to plain environment credentials.
    """
    data = fetch_account(config)
    if data is None:
        return False

    if data.get("set"):
        broker = (data.get("brokerName") or "").strip().lower()
        key = (data.get("brokerKey") or "").strip()
        secret = (data.get("brokerSecret") or "").strip()

        if broker.startswith("alpaca") and key:
            config.alpaca_api_key = key
            config.alpaca_api_secret = secret
            live = broker == "alpaca-live"
            config.alpaca_environment = "live" if live else "paper"
            config.alpaca_base_url = (
                "https://api.alpaca.markets" if live else "https://paper-api.alpaca.markets"
            )
            if (config.broker or "auto") == "auto":
                config.broker = "alpaca"
        elif broker == "binance" and key:
            os.environ.setdefault("BINANCE_API_KEY", key)
            os.environ.setdefault("BINANCE_API_SECRET", secret)
            if (config.broker or "auto") == "auto":
                config.broker = "binance"
        elif broker == "paper":
            if (config.broker or "auto") == "auto":
                config.broker = "paper"

        ai_provider = (data.get("aiProvider") or "").strip().lower()
        ai_key = (data.get("aiKey") or "").strip()
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        env_name = env_map.get(ai_provider)
        if env_name and ai_key:
            os.environ.setdefault(env_name, ai_key)

    # The app decides paper vs live.  Live is only honoured when the saved
    # broker keys really point at the live Alpaca endpoint — practice keys
    # always stay paper no matter what the switch says.
    mode = (data.get("mode") or "paper").strip().lower()
    config.app_account_mode = "live" if mode == "live" else "paper"
    if config.app_account_mode == "live":
        broker = (data.get("brokerName") or "").strip().lower()
        if broker == "alpaca-live":
            config.live_trading_enabled = True
        else:
            logger.info(
                "jexi app: account is in live mode but broker keys are '%s' — runner stays on the practice endpoint",
                broker or "unset",
            )

    logger.info(
        "jexi app: account %s loaded (mode=%s, broker=%s)",
        config.jexi_app_email,
        config.app_account_mode,
        config.broker,
    )
    return True


def push_notification(
    config,
    message: str,
    *,
    kind: str = "info",
    title: str = "",
    timeout_seconds: float = 12.0,
) -> bool:
    """Push one plain-English notification into the user's Jexi app feed."""
    if not app_configured(config):
        return False
    payload = {
        "email": (config.jexi_app_email or "").strip(),
        "kind": kind,
        "message": message,
    }
    if title:
        payload["title"] = title
    try:
        resp = requests.post(
            f"{_server(config)}/api/agent/notify",
            json=payload,
            headers={**_headers(config), "Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("jexi app: notify failed with HTTP %s", resp.status_code)
        return False
    except requests.exceptions.RequestException as exc:
        logger.warning("jexi app: notify error %s", type(exc).__name__)
        return False
