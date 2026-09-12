# -*- coding: utf-8 -*-
"""Strategies subpackage."""

from jexi_market.strategies.registry import (
    Strategy,
    StrategyResult,
    all_strategies,
    get_strategy,
    list_strategies,
    register_strategy,
)

# v0.3: auto-register the expanded strategy families (squeeze, triple-MA,
# supertrend, momentum-12-1, williams, vwap-reversion, ensemble) whenever
# the package is imported.  Failure here must never break imports.
try:
    import jexi_market.strategies.extra as _extra  # noqa: F401
except Exception as _exc:  # pragma: no cover
    import logging
    logging.getLogger(__name__).warning("extra strategies not registered: %s", _exc)

__all__ = [
    "Strategy",
    "StrategyResult",
    "all_strategies",
    "get_strategy",
    "list_strategies",
    "register_strategy",
]
