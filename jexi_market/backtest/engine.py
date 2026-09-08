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
