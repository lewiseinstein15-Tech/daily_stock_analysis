# -*- coding: utf-8 -*-
"""Backtest subpackage."""

from jexi_market.backtest.engine import (
    BacktestResult,
    BacktestTrade,
    WalkForwardResult,
    compare_strategies,
    compute_correlation_matrix,
    find_correlated_clusters,
    run_backtest,
    run_walk_forward,
)

__all__ = [
    "BacktestResult",
    "BacktestTrade",
    "WalkForwardResult",
    "compare_strategies",
    "compute_correlation_matrix",
    "find_correlated_clusters",
    "run_backtest",
    "run_walk_forward",
]
