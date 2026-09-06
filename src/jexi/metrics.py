# -*- coding: utf-8 -*-
"""Performance metrics for the J.E.X.I. self-improvement loop.

``win rate``, ``Sharpe ratio``, ``max drawdown`` and ``total return`` are the
four targets Jexi optimises against (see ``scripts/jexi_cli.py --target-*``).
Metrics are computed from an equity curve (per-day portfolio value) plus a list
of closed trade dicts (``{"pnl_pct": float}``).
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

TRADING_DAYS_PER_YEAR = 252.0


def compute_sharpe(daily_returns: Sequence[float], risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio from a sequence of daily returns."""
    if not daily_returns:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    if len(daily_returns) < 2:
        return 0.0
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    # Guard float-stable flat series (variance ~1e-34 noise) to avoid 1e16 Sharpe.
    if variance <= 1e-12:
        return 0.0
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean - risk_free_rate / TRADING_DAYS_PER_YEAR) / std * math.sqrt(
        TRADING_DAYS_PER_YEAR
    )


def compute_max_drawdown(equity_series: Sequence[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction (0.0-1.0)."""
    peak = -math.inf
    max_dd = 0.0
    for value in equity_series:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def win_rate(trades: Sequence[dict]) -> float:
    """Fraction of closed trades with positive pnl_pct (0.0-1.0)."""
    closed = [t for t in trades if t.get("pnl_pct") is not None]
    if not closed:
        return 0.0
    return sum(1 for t in closed if t["pnl_pct"] > 0) / len(closed)


def total_return(equity_series: Sequence[float]) -> float:
    """Net return (fraction) between first and last equity value."""
    if len(equity_series) < 2 or equity_series[0] == 0:
        return 0.0
    return equity_series[-1] / equity_series[0] - 1.0


def scenario_metrics_snapshot(
    equity_series: Sequence[float],
    trades: Sequence[dict],
    daily_returns: Optional[Sequence[float]] = None,
) -> Dict[str, float]:
    """Package the four target metrics into one dict for journaling/reporting."""
    returns = daily_returns
    if returns is None and len(equity_series) >= 2:
        returns = [
            (equity_series[i] - equity_series[i - 1]) / equity_series[i - 1]
            for i in range(1, len(equity_series))
            if equity_series[i - 1] != 0
        ]
    return {
        "win_rate": round(win_rate(trades), 4),
        "sharpe": round(compute_sharpe(list(returns or [])), 4),
        "max_drawdown": round(compute_max_drawdown(equity_series), 4),
        "total_return": round(total_return(equity_series), 4),
        "n_trades": len([t for t in trades if t.get("pnl_pct") is not None]),
    }
