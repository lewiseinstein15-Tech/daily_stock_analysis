# -*- coding: utf-8 -*-
"""Tests for the backtesting engine."""

import pandas as pd

from jexi_market.backtest import run_backtest
from jexi_market.strategies import get_strategy, list_strategies


def _make_ohlcv(rows: int = 200, drift: float = 0.001, seed: int = 0) -> pd.DataFrame:
    import random
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1.0 + drift + rng.gauss(0, 0.012)))
    return pd.DataFrame({
        "date": [f"2024-01-{(i % 28) + 1:02d}" if i < 28 else f"2024-{(i // 28) + 2:02d}-{(i % 28) + 1:02d}" for i in range(rows)],
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000 + i * 1000 for i in range(rows)],
    })


def test_list_strategies_returns_builtin_set():
    names = list_strategies()
    for expected in ("trend_following", "momentum", "mean_reversion", "breakout", "factor_value"):
        assert expected in names


def test_backtest_runs_and_returns_metrics():
    df = _make_ohlcv(rows=200, drift=0.002)
    strategy = get_strategy("trend_following")
    result = run_backtest(df, strategy, symbol="TEST")
    assert result.strategy_name == "trend_following"
    assert result.symbol == "TEST"
    assert result.n_trades >= 0
    # Must have computed metrics
    assert "total_return" in result.to_dict()
    assert "sharpe" in result.to_dict()
    assert "max_drawdown" in result.to_dict()


def test_backtest_handles_empty_df():
    df = pd.DataFrame()
    strategy = get_strategy("momentum")
    result = run_backtest(df, strategy, symbol="EMPTY")
    assert result.n_trades == 0
    assert result.total_return == 0.0


def test_backtest_handles_short_df():
    df = _make_ohlcv(rows=15)
    strategy = get_strategy("trend_following")
    result = run_backtest(df, strategy, symbol="SHORT")
    assert result.n_trades == 0


def test_backtest_bull_drift_produces_trades():
    df = _make_ohlcv(rows=250, drift=0.003, seed=1)
    strategy = get_strategy("trend_following")
    result = run_backtest(df, strategy, symbol="BULL")
    # In a clear bull drift, trend-following should fire at least once
    assert result.n_trades > 0


def test_backtest_metrics_consistency():
    df = _make_ohlcv(rows=250, drift=0.002, seed=2)
    strategy = get_strategy("momentum")
    result = run_backtest(df, strategy, symbol="MOM")
    payload = result.to_dict()
    # Win rate should be between 0 and 1 (or 0 if no trades)
    assert 0.0 <= payload["win_rate"] <= 1.0
    # Profit factor is positive when there are wins
    if payload["n_winning"] > 0:
        assert payload["profit_factor"] > 0
    # Sharpe is a real number
    assert isinstance(payload["sharpe"], float)
    # Max drawdown non-negative
    assert payload["max_drawdown"] >= 0


def test_backtest_transaction_costs_reduced_return():
    """Higher transaction costs should reduce total return (or at least not increase it)."""
    df = _make_ohlcv(rows=200, drift=0.002, seed=3)
    strategy = get_strategy("momentum")
    cheap = run_backtest(df, strategy, symbol="X", transaction_cost_bps=1.0, slippage_bps=1.0)
    expensive = run_backtest(df, strategy, symbol="X", transaction_cost_bps=20.0, slippage_bps=20.0)
    # Either both have no trades, or expensive return <= cheap return
    if cheap.n_trades > 0 and expensive.n_trades > 0:
        assert expensive.total_return <= cheap.total_return + 0.001  # tolerance


def test_backtest_alpha_against_benchmark():
    df = _make_ohlcv(rows=200, drift=0.001, seed=4)
    strategy = get_strategy("trend_following")
    result = run_backtest(df, strategy, symbol="ALPHA")
    payload = result.to_dict()
    assert "alpha" in payload
    assert "benchmark_return" in payload
    # Alpha = total_return - benchmark_return
    assert abs(payload["alpha"] - (payload["total_return"] - payload["benchmark_return"])) < 0.001


def test_all_strategies_run_without_error():
    """Every registered strategy must produce a result without raising."""
    df = _make_ohlcv(rows=200, drift=0.002)
    for name in list_strategies():
        strategy = get_strategy(name)
        result = run_backtest(df, strategy, symbol=name)
        assert result is not None
        assert result.strategy_name == name
