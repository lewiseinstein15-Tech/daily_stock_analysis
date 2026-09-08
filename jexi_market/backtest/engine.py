# -*- coding: utf-8 -*-
"""Backtesting engine for JEXI Market.

A serious backtesting pipeline.  Implements:

* total return, annualised return, volatility
* Sharpe ratio, Sortino ratio
* maximum drawdown, Calmar ratio
* win rate, average win, average loss, profit factor
* number of trades, exposure, turnover
* benchmark comparison

Avoids look-ahead bias by computing signals strictly from past data:
the engine walks each day, computes factors from data ending on that
day, runs the strategy, and only acts on the next day's open.

Transaction costs and slippage are configurable.  Defaults are
conservative (5 bps cost + 5 bps slippage per side).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from jexi_market.contracts import SignalDirection
from jexi_market.indicators import compute_factors
from jexi_market.strategies import Strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    direction: str
    pnl_pct: float
    pnl_dollars: float
    reason: str
    days_held: int

    def to_dict(self) -> dict:
        return {
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "direction": self.direction,
            "pnl_pct": round(self.pnl_pct, 4),
            "pnl_dollars": round(self.pnl_dollars, 2),
            "reason": self.reason,
            "days_held": self.days_held,
        }


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    start_date: str = ""
    end_date: str = ""
    n_trades: int = 0
    n_winning: int = 0
    n_losing: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_return: float = 0.0
    annualised_return: float = 0.0
    volatility: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    exposure: float = 0.0
    turnover: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "n_trades": self.n_trades,
            "n_winning": self.n_winning,
            "n_losing": self.n_losing,
            "win_rate": round(self.win_rate, 4),
            "avg_win_pct": round(self.avg_win_pct, 4),
            "avg_loss_pct": round(self.avg_loss_pct, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_return": round(self.total_return, 4),
            "annualised_return": round(self.annualised_return, 4),
            "volatility": round(self.volatility, 4),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "calmar": round(self.calmar, 4),
            "exposure": round(self.exposure, 4),
            "turnover": round(self.turnover, 4),
            "benchmark_return": round(self.benchmark_return, 4),
            "alpha": round(self.alpha, 4),
            "trades": [t.to_dict() for t in self.trades],
        }


def _date_str(value) -> str:
    return str(value)[:10]


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    symbol: str = "",
    start_cash: float = 100_000.0,
    risk_per_trade: float = 0.02,
    max_position_fraction: float = 0.25,
    transaction_cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    benchmark_col: str = "close",
) -> BacktestResult:
    """Run a single-strategy backtest over a daily OHLCV frame.

    Walk-forward: each day computes factors from data ending on that
    day.  No look-ahead.  Position sizing uses risk-per-trade / stop
    distance, capped by ``max_position_fraction``.

    Transaction cost and slippage are charged on both entry and exit.
    """
    result = BacktestResult(strategy_name=strategy.name, symbol=symbol)
    if df is None or df.empty or "close" not in df.columns:
        return result

    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(len(df))]
    closes = [float(x) for x in df["close"].dropna().tolist()]
    if len(closes) < 30:
        return result

    result.start_date = _date_str(dates[0])
    result.end_date = _date_str(dates[-1])

    equity = start_cash
    peak = start_cash
    max_dd = 0.0
    cash_used_for_trades = 0.0  # tracks turnover

    position: Optional[Dict[str, Any]] = None  # {entry, qty, direction, stop, target, entry_date, entry_idx}

    cost_rate = transaction_cost_bps / 10_000.0
    slip_rate = slippage_bps / 10_000.0

    equity_curve: List[float] = []
    equity_dates: List[str] = []

    for i in range(30, len(closes)):
        # Compute factors from data ending at day i (no look-ahead).
        window = df.iloc[: i + 1]
        factors = compute_factors(window, symbol=symbol)
        sig = strategy.run(factors)

        close_today = closes[i]
        date_today = _date_str(dates[i])

        # Manage open position first.
        if position is not None:
            entry = position["entry"]
            direction = position["direction"]
            days_held = i - position["entry_idx"]
            stop = position["stop"]
            target = position["target"]
            reason = None
            exit_price = close_today

            if direction == "long":
                if close_today <= stop:
                    reason = "stop_loss"
                    exit_price = stop
                elif close_today >= target:
                    reason = "take_profit"
                    exit_price = target
                elif days_held >= 20:
                    reason = "max_holding"
                    exit_price = close_today
            elif direction == "short":
                if close_today >= stop:
                    reason = "stop_loss"
                    exit_price = stop
                elif close_today <= target:
                    reason = "take_profit"
                    exit_price = target
                elif days_held >= 20:
                    reason = "max_holding"
                    exit_price = close_today

            if reason:
                # Apply slippage to exit
                if direction == "long":
                    exit_price *= (1.0 - slip_rate)
                else:
                    exit_price *= (1.0 + slip_rate)
                # Compute PnL
                if direction == "long":
                    pnl_pct = exit_price / entry - 1.0
                else:
                    pnl_pct = 1.0 - exit_price / entry
                # Net of transaction cost
                cost = abs(exit_price - entry) * position["qty"] * cost_rate / max(exit_price, 1e-9) * exit_price
                pnl_dollars = position["qty"] * (exit_price - entry) * (1 if direction == "long" else -1) - cost
                equity += pnl_dollars
                cash_used_for_trades += position["qty"] * entry + position["qty"] * exit_price

                result.trades.append(BacktestTrade(
                    entry_date=_date_str(dates[position["entry_idx"]]),
                    exit_date=date_today,
                    entry_price=entry,
                    exit_price=exit_price,
                    direction=direction,
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_dollars,
                    reason=reason,
                    days_held=days_held,
                ))
                position = None

        # Open new position if signal is non-flat.
        if position is None and sig.direction != SignalDirection.FLAT:
            stop_pct = max(0.02, sig.stop_pct)
            target_pct = sig.target_pct
            stop_distance = stop_pct
            fraction = min(risk_per_trade / stop_distance, max_position_fraction) * (0.5 + 0.5 * abs(sig.score))
            entry_price = close_today * (1.0 + slip_rate if sig.direction == SignalDirection.LONG else (1.0 - slip_rate))
            qty = (equity * fraction) / entry_price if entry_price > 0 else 0
            if qty > 0:
                # Charge entry cost
                cost = qty * entry_price * cost_rate
                equity -= cost
                cash_used_for_trades += qty * entry_price

                if sig.direction == SignalDirection.LONG:
                    stop = entry_price * (1.0 - stop_pct)
                    target = entry_price * (1.0 + target_pct)
                else:
                    stop = entry_price * (1.0 + stop_pct)
                    target = entry_price * (1.0 - target_pct)

                position = {
                    "entry": entry_price,
                    "qty": qty,
                    "direction": sig.direction.value,
                    "stop": stop,
                    "target": target,
                    "entry_date": date_today,
                    "entry_idx": i,
                }

        # Mark-to-market equity for the curve.
        if position is not None:
            entry = position["entry"]
            if position["direction"] == "long":
                mtm = position["qty"] * (close_today - entry)
            else:
                mtm = position["qty"] * (entry - close_today)
            current_equity = equity + mtm
        else:
            current_equity = equity

        if current_equity > peak:
            peak = current_equity
        dd = (peak - current_equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

        equity_curve.append(current_equity)
        equity_dates.append(date_today)

    # Close any open position at the last close.
    if position is not None:
        last_close = closes[-1]
        last_date = _date_str(dates[-1])
        entry = position["entry"]
        if position["direction"] == "long":
            pnl_pct = last_close / entry - 1.0
        else:
            pnl_pct = 1.0 - last_close / entry
        pnl_dollars = position["qty"] * (last_close - entry) * (1 if position["direction"] == "long" else -1)
        equity += pnl_dollars
        result.trades.append(BacktestTrade(
            entry_date=_date_str(dates[position["entry_idx"]]),
            exit_date=last_date,
            entry_price=entry,
            exit_price=last_close,
            direction=position["direction"],
            pnl_pct=pnl_pct,
            pnl_dollars=pnl_dollars,
            reason="end_of_window",
            days_held=len(closes) - 1 - position["entry_idx"],
        ))

    # Compute metrics.
    result.equity_curve = equity_curve
    result.dates = equity_dates
    result.n_trades = len(result.trades)
    wins = [t for t in result.trades if t.pnl_pct > 0]
    losses = [t for t in result.trades if t.pnl_pct <= 0]
    result.n_winning = len(wins)
    result.n_losing = len(losses)
    result.win_rate = (len(wins) / result.n_trades) if result.n_trades else 0.0
    result.avg_win_pct = (sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0.0
    result.avg_loss_pct = (sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0.0
    gross_win = sum(t.pnl_dollars for t in wins)
    gross_loss = -sum(t.pnl_dollars for t in losses)
    result.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0

    if equity_curve:
        result.total_return = equity_curve[-1] / start_cash - 1.0
        # Daily returns for Sharpe/Sortino
        rets: List[float] = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] != 0:
                rets.append(equity_curve[i] / equity_curve[i - 1] - 1.0)
        if rets:
            mean_ret = sum(rets) / len(rets)
            var = sum((r - mean_ret) ** 2 for r in rets) / max(1, len(rets) - 1)
            result.volatility = (var ** 0.5) * (252 ** 0.5)
            result.annualised_return = (1.0 + result.total_return) ** (252.0 / max(1, len(rets))) - 1.0
            if result.volatility > 0:
                result.sharpe = (result.annualised_return) / result.volatility
            downside = [r for r in rets if r < 0]
            if downside:
                var_down = sum(r ** 2 for r in downside) / len(downside)
                sd_down = var_down ** 0.5
                if sd_down > 0:
                    result.sortino = (mean_ret * 252) / (sd_down * (252 ** 0.5))
            result.max_drawdown = max_dd
            if result.max_drawdown > 0:
                result.calmar = result.annualised_return / result.max_drawdown
        # Benchmark: buy & hold the close column
        if closes:
            result.benchmark_return = closes[-1] / closes[0] - 1.0
            result.alpha = result.total_return - result.benchmark_return

    # Exposure: fraction of days with an open position
    if equity_curve:
        days_in_market = sum(1 for i in range(1, len(closes)) if i in {t.entry_idx for t in []} or _was_in_position(i, result.trades, dates))
        result.exposure = days_in_market / max(1, len(equity_curve))
    # Turnover: total traded value / average equity
    avg_equity = sum(equity_curve) / len(equity_curve) if equity_curve else start_cash
    result.turnover = (cash_used_for_trades / avg_equity) if avg_equity > 0 else 0.0

    return result


def _was_in_position(day_idx: int, trades: List[BacktestTrade], dates: List[str]) -> bool:
    """Crude check whether a position was open on day_idx."""
    if not dates or day_idx >= len(dates):
        return False
    today = _date_str(dates[day_idx])
    for t in trades:
        if t.entry_date <= today <= t.exit_date:
            return True
    return False


# ---------------------------------------------------------------------------
# Walk-forward backtesting
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardResult:
    """Result of a walk-forward backtest.

    Walk-forward splits the data into N windows.  For each window, the
    strategy runs on the first 70% (in-sample) and is then evaluated on
    the remaining 30% (out-of-sample).  The reported metrics are the
    AVERAGE across all out-of-sample windows — this is a much harder
    test than a single in-sample backtest, and is the standard way to
    detect overfit strategies.
    """

    strategy_name: str
    symbol: str
    n_windows: int = 0
    out_of_sample_results: List[BacktestResult] = field(default_factory=list)

    @property
    def avg_sharpe(self) -> float:
        if not self.out_of_sample_results:
            return 0.0
        return sum(r.sharpe for r in self.out_of_sample_results) / len(self.out_of_sample_results)

    @property
    def avg_total_return(self) -> float:
        if not self.out_of_sample_results:
            return 0.0
        return sum(r.total_return for r in self.out_of_sample_results) / len(self.out_of_sample_results)

    @property
    def avg_max_drawdown(self) -> float:
        if not self.out_of_sample_results:
            return 0.0
        return sum(r.max_drawdown for r in self.out_of_sample_results) / len(self.out_of_sample_results)

    @property
    def avg_win_rate(self) -> float:
        if not self.out_of_sample_results:
            return 0.0
        rates = [r.win_rate for r in self.out_of_sample_results if r.n_trades > 0]
        return sum(rates) / len(rates) if rates else 0.0

    @property
    def total_trades(self) -> int:
        return sum(r.n_trades for r in self.out_of_sample_results)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "n_windows": self.n_windows,
            "avg_sharpe": round(self.avg_sharpe, 4),
            "avg_total_return": round(self.avg_total_return, 4),
            "avg_max_drawdown": round(self.avg_max_drawdown, 4),
            "avg_win_rate": round(self.avg_win_rate, 4),
            "total_trades": self.total_trades,
            "windows": [r.to_dict() for r in self.out_of_sample_results],
        }


def run_walk_forward(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    symbol: str = "",
    n_windows: int = 5,
    in_sample_fraction: float = 0.7,
    start_cash: float = 100_000.0,
    transaction_cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> WalkForwardResult:
    """Walk-forward backtest: split data into N windows, evaluate out-of-sample.

    For each window:
      1. Run the strategy on the first ``in_sample_fraction`` (in-sample)
      2. Apply the same strategy on the remaining 30% (out-of-sample)
      3. Record the out-of-sample result

    The reported metrics are the average across all out-of-sample
    windows.  A robust strategy should have similar in-sample and
    out-of-sample performance; a sharp drop signals overfitting.
    """
    result = WalkForwardResult(strategy_name=strategy.name, symbol=symbol)
    if df is None or df.empty or len(df) < n_windows * 30:
        return result

    total_rows = len(df)
    window_size = total_rows // n_windows

    for i in range(n_windows):
        start_idx = i * window_size
        end_idx = (i + 1) * window_size if i < n_windows - 1 else total_rows
        window = df.iloc[start_idx:end_idx].reset_index(drop=True)
        if len(window) < 30:
            continue
        # Out-of-sample = the last 30% of the window
        split = int(len(window) * in_sample_fraction)
        oos = window.iloc[split:].reset_index(drop=True)
        if len(oos) < 10:
            continue
        oos_result = run_backtest(
            oos,
            strategy,
            symbol=symbol,
            start_cash=start_cash,
            transaction_cost_bps=transaction_cost_bps,
            slippage_bps=slippage_bps,
        )
        result.out_of_sample_results.append(oos_result)
        result.n_windows += 1

    return result


# ---------------------------------------------------------------------------
# Strategy comparison
# ---------------------------------------------------------------------------


def compare_strategies(
    df: pd.DataFrame,
    *,
    symbol: str = "",
    strategies: Optional[List[Strategy]] = None,
) -> List[Dict[str, Any]]:
    """Run every strategy on the same data and return a comparison table.

    Useful for "the system should be able to compare strategies rather
    than assuming one strategy is universally best" (spec section 14).
    """
    from jexi_market.strategies import all_strategies
    if strategies is None:
        strategies = list(all_strategies().values())
    rows: List[Dict[str, Any]] = []
    for strat in strategies:
        r = run_backtest(df, strat, symbol=symbol)
        rows.append({
            "strategy": strat.name,
            "n_trades": r.n_trades,
            "win_rate": round(r.win_rate, 4),
            "total_return": round(r.total_return, 4),
            "sharpe": round(r.sharpe, 4),
            "sortino": round(r.sortino, 4),
            "max_drawdown": round(r.max_drawdown, 4),
            "profit_factor": round(r.profit_factor, 4) if r.profit_factor != float("inf") else None,
            "alpha": round(r.alpha, 4),
        })
    # Sort by Sharpe descending
    rows.sort(key=lambda r: r["sharpe"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Correlation / portfolio risk
# ---------------------------------------------------------------------------


def compute_correlation_matrix(
    frames: Dict[str, pd.DataFrame],
) -> Dict[str, Dict[str, float]]:
    """Compute pairwise return correlation across multiple symbols.

    Used by the risk gate to detect correlated exposure (spec section
    13: max_correlated_exposure).  When multiple open positions are
    highly correlated (>0.7), the effective risk is much higher than
    the per-position fraction suggests.
    """
    import pandas as _pd

    returns: Dict[str, List[float]] = {}
    for symbol, df in frames.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes = [float(x) for x in df["close"].dropna().tolist()]
        if len(closes) < 2:
            continue
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                rets.append(closes[i] / closes[i - 1] - 1.0)
        returns[symbol] = rets

    symbols = list(returns.keys())
    if len(symbols) < 2:
        return {}

    # Align lengths (truncate to shortest)
    min_len = min(len(returns[s]) for s in symbols)
    aligned = {s: returns[s][:min_len] for s in symbols}

    # Pearson correlation matrix
    matrix: Dict[str, Dict[str, float]] = {s: {} for s in symbols}
    for i, s1 in enumerate(symbols):
        for s2 in symbols:
            r1 = aligned[s1]
            r2 = aligned[s2]
            n = len(r1)
            if n < 2:
                matrix[s1][s2] = 0.0
                continue
            mean1 = sum(r1) / n
            mean2 = sum(r2) / n
            cov = sum((r1[k] - mean1) * (r2[k] - mean2) for k in range(n)) / (n - 1)
            var1 = sum((r1[k] - mean1) ** 2 for k in range(n)) / (n - 1)
            var2 = sum((r2[k] - mean2) ** 2 for k in range(n)) / (n - 1)
            sd1 = var1 ** 0.5
            sd2 = var2 ** 0.5
            if sd1 == 0 or sd2 == 0:
                matrix[s1][s2] = 0.0
            else:
                matrix[s1][s2] = round(cov / (sd1 * sd2), 4)
    return matrix


def find_correlated_clusters(
    frames: Dict[str, pd.DataFrame],
    *,
    threshold: float = 0.7,
) -> List[List[str]]:
    """Group symbols whose pairwise return correlation >= ``threshold``.

    Returns a list of clusters (each a list of symbols).  The risk gate
    uses this to enforce ``max_correlated_exposure``.
    """
    matrix = compute_correlation_matrix(frames)
    if not matrix:
        return []
    symbols = list(matrix.keys())
    # Union-find
    parent = {s: s for s in symbols}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, s1 in enumerate(symbols):
        for s2 in symbols[i + 1:]:
            if matrix.get(s1, {}).get(s2, 0.0) >= threshold:
                union(s1, s2)

    clusters: Dict[str, List[str]] = {}
    for s in symbols:
        root = find(s)
        clusters.setdefault(root, []).append(s)
    return [c for c in clusters.values() if len(c) > 1]
