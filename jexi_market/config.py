# -*- coding: utf-8 -*-
"""Configuration for JEXI Market.

All configuration is read from environment variables.  Nothing in this
module performs any I/O at import time; the only side effect is reading
``os.environ``.  This makes the config cheap to construct in tests and
deterministic given the environment.

Sensitive values (Alpaca keys, ntfy tokens) are NEVER logged by this
module; only a redacted view is exposed through :meth:`MarketConfig.summary`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class MarketConfig:
    """All JEXI Market runtime configuration."""

    # --- Alpaca (paper trading by default) -------------------------------
    alpaca_api_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    alpaca_api_secret: str = field(default_factory=lambda: os.getenv("ALPACA_API_SECRET", ""))
    # "paper" (default) or "live" — live requires explicit env enable.
    alpaca_environment: str = field(default_factory=lambda: os.getenv("ALPACA_ENV", "paper").lower())
    alpaca_base_url: str = field(
        default_factory=lambda: os.getenv(
            "ALPACA_BASE_URL",
            "https://paper-api.alpaca.markets",
        )
    )
    alpaca_data_url: str = field(
        default_factory=lambda: os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")
    )

    # --- ntfy notifications ------------------------------------------------
    ntfy_url: str = field(default_factory=lambda: os.getenv("NTFY_URL", ""))
    ntfy_token: str = field(default_factory=lambda: os.getenv("NTFY_TOKEN", ""))
    jexi_ntfy_topic: str = field(
        default_factory=lambda: os.getenv("JEXI_MARKET_NTFY_TOPIC", "jexi_market_reports")
    )
    # Default priority levels — see notifications/reporter.py for the map.
    ntfy_default_priority: str = field(default_factory=lambda: os.getenv("NTFY_DEFAULT_PRIORITY", "default"))

    # --- Risk envelope -----------------------------------------------------
    # These override the RiskEnvelope defaults when set.
    max_risk_per_trade: float = field(default_factory=lambda: _env_float("JEXI_MAX_RISK_PER_TRADE", 0.02))
    max_position_fraction: float = field(default_factory=lambda: _env_float("JEXI_MAX_POSITION_FRACTION", 0.25))
    max_portfolio_exposure: float = field(default_factory=lambda: _env_float("JEXI_MAX_PORTFOLIO_EXPOSURE", 1.0))
    daily_loss_limit: float = field(default_factory=lambda: _env_float("JEXI_DAILY_LOSS_LIMIT", 0.04))
    drawdown_halt_threshold: float = field(default_factory=lambda: _env_float("JEXI_DRAWDOWN_HALT", 0.10))

    # --- Live trading gate -------------------------------------------------
    # Both must be true to ever place a live order:
    #   JEXI_LIVE_TRADING_ENABLED=1 AND
    #   paper-validation counter >= min_30d_paper_validation
    live_trading_enabled: bool = field(default_factory=lambda: _env_bool("JEXI_LIVE_TRADING_ENABLED", False))
    paper_validation_days: int = field(default_factory=lambda: _env_int("JEXI_PAPER_VALIDATION_DAYS", 30))

    # --- Performance memory -----------------------------------------------
    memory_db_path: str = field(
        default_factory=lambda: os.getenv("JEXI_MEMORY_DB", "data/jexi_market/memory.sqlite")
    )

    # --- Research backend --------------------------------------------------
    # Reuses src.jexi.research infrastructure: "auto" | "opencode_cli" |
    # "litellm" | "off".  Default "off" keeps the pilot deterministic.
    research_backend: str = field(default_factory=lambda: os.getenv("JEXI_RESEARCH_BACKEND", "off"))

    # --- Scanner -----------------------------------------------------------
    scanner_universe: str = field(
        default_factory=lambda: os.getenv(
            "JEXI_SCANNER_UNIVERSE",
            "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,SPY,QQQ",
        )
    )
    scanner_lookback_days: int = field(default_factory=lambda: _env_int("JEXI_SCANNER_LOOKBACK_DAYS", 120))

    # --- Default tickers for `jexi-market once` ---------------------------
    default_symbols: str = field(default_factory=lambda: os.getenv("JEXI_DEFAULT_SYMBOLS", "AAPL,MSFT,NVDA"))

    # --- MCP ---------------------------------------------------------------
    mcp_enabled: bool = field(default_factory=lambda: _env_bool("JEXI_MCP_ENABLED", False))
    mcp_servers_json: str = field(default_factory=lambda: os.getenv("JEXI_MCP_SERVERS", ""))

    # --- Misc --------------------------------------------------------------
    log_level: str = field(default_factory=lambda: os.getenv("JEXI_LOG_LEVEL", "INFO"))
    timezone: str = field(default_factory=lambda: os.getenv("JEXI_TIMEZONE", "Africa/Nairobi"))

    # --- Convenience -------------------------------------------------------
    @property
    def risk_envelope_kwargs(self) -> Dict[str, Any]:
        return {
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_position_fraction": self.max_position_fraction,
            "max_portfolio_exposure": self.max_portfolio_exposure,
            "daily_loss_limit": self.daily_loss_limit,
            "drawdown_halt_threshold": self.drawdown_halt_threshold,
            "min_30d_paper_validation": self.paper_validation_days,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def scanner_symbols(self) -> list:
        return [s.strip() for s in self.scanner_universe.split(",") if s.strip()]

    @property
    def default_symbol_list(self) -> list:
        return [s.strip() for s in self.default_symbols.split(",") if s.strip()]

    def summary(self) -> Dict[str, Any]:
        """A redacted view suitable for logging / status commands."""
        return {
            "alpaca_environment": self.alpaca_environment,
            "alpaca_api_key_set": bool(self.alpaca_api_key),
            "alpaca_api_secret_set": bool(self.alpaca_api_secret),
            "ntfy_url_set": bool(self.ntfy_url),
            "ntfy_topic": self.jexi_ntfy_topic,
            "live_trading_enabled": self.live_trading_enabled,
            "paper_validation_days": self.paper_validation_days,
            "research_backend": self.research_backend,
            "mcp_enabled": self.mcp_enabled,
            "scanner_universe_size": len(self.scanner_symbols),
            "memory_db_path": self.memory_db_path,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_position_fraction": self.max_position_fraction,
            "drawdown_halt_threshold": self.drawdown_halt_threshold,
        }


_singleton: Optional[MarketConfig] = None


def get_config() -> MarketConfig:
    """Module-level cached config (matches the repo's accessor convention)."""
    global _singleton
    if _singleton is None:
        _singleton = MarketConfig()
    return _singleton


def reset_config() -> None:
    """Reset the cached config — used by tests that mutate ``os.environ``."""
    global _singleton
    _singleton = None
