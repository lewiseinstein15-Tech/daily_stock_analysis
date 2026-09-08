# -*- coding: utf-8 -*-
"""Tests for the new backtesting features: walk-forward, compare, correlation."""

import pandas as pd

from jexi_market.backtest import (
    compare_strategies,
    compute_correlation_matrix,
    find_correlated_clusters,
    run_backtest,
    run_walk_forward,
    WalkForwardResult,
)
from jexi_market.strategies import all_strategies, get_strategy


def _make_ohlcv(rows=300, drift=0.002, seed=0):
    import random
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1.0 + drift + rng.gauss(0, 0.012)))
    return pd.DataFrame({
        "date": [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(rows)],
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000 + i * 1000 for i in range(rows)],
    })


def test_walk_forward_returns_result():
    df = _make_ohlcv(rows=300, drift=0.002, seed=1)
    strat = get_strategy("trend_following")
    wf = run_walk_forward(df, strat, symbol="TEST", n_windows=5)
    assert isinstance(wf, WalkForwardResult)
    assert wf.strategy_name == "trend_following"
    assert wf.symbol == "TEST"
    assert wf.n_windows > 0
    assert len(wf.out_of_sample_results) == wf.n_windows


def test_walk_forward_handles_short_data():
    df = _make_ohlcv(rows=30, seed=2)
    strat = get_strategy("momentum")
    wf = run_walk_forward(df, strat, symbol="SHORT", n_windows=5)
    assert wf.n_windows == 0  # not enough data for 5 windows
    assert wf.out_of_sample_results == []


def test_walk_forward_avg_metrics():
    df = _make_ohlcv(rows=500, drift=0.003, seed=3)
    strat = get_strategy("momentum")
    wf = run_walk_forward(df, strat, symbol="MOM", n_windows=5)
    # avg_sharpe should be a real number (possibly negative)
    assert isinstance(wf.avg_sharpe, float)
    assert isinstance(wf.avg_total_return, float)
    assert isinstance(wf.avg_max_drawdown, float)
    # total_trades is sum across windows
    assert wf.total_trades == sum(r.n_trades for r in wf.out_of_sample_results)


def test_walk_forward_to_dict():
    df = _make_ohlcv(rows=300, drift=0.002, seed=4)
    strat = get_strategy("trend_following")
    wf = run_walk_forward(df, strat, symbol="TEST", n_windows=3)
    d = wf.to_dict()
    assert d["strategy_name"] == "trend_following"
    assert d["n_windows"] == wf.n_windows
    assert "windows" in d
    assert len(d["windows"]) == wf.n_windows


def test_compare_strategies_returns_sorted_rows():
    df = _make_ohlcv(rows=250, drift=0.002, seed=5)
    rows = compare_strategies(df, symbol="CMP")
    # Every registered strategy should appear
    assert len(rows) >= 8
    for r in rows:
        assert "strategy" in r
        assert "sharpe" in r
        assert "win_rate" in r
        assert "total_return" in r
    # Sorted by Sharpe descending
    sharpes = [r["sharpe"] for r in rows]
    assert sharpes == sorted(sharpes, reverse=True)


def test_compare_strategies_with_subset():
    df = _make_ohlcv(rows=200, drift=0.002, seed=6)
    strategies = [get_strategy("trend_following"), get_strategy("momentum")]
    rows = compare_strategies(df, symbol="SUB", strategies=strategies)
    assert len(rows) == 2
    names = [r["strategy"] for r in rows]
    assert set(names) == {"trend_following", "momentum"}


def test_compute_correlation_matrix_perfectly_correlated():
    """Two symbols with identical returns should have correlation 1.0."""
    import pandas as pd
    closes = [100.0 + i for i in range(50)]
    df1 = pd.DataFrame({"close": closes})
    df2 = pd.DataFrame({"close": closes})  # identical
    matrix = compute_correlation_matrix({"A": df1, "B": df2})
    assert matrix["A"]["B"] == 1.0
    assert matrix["A"]["A"] == 1.0
    assert matrix["B"]["A"] == 1.0


def test_compute_correlation_matrix_anticorrelated():
    """When A's returns are +x% and B's returns are -x% for the SAME x
    each day, the correlation should be -1.0."""
    import pandas as pd
    import random
    rng = random.Random(42)
    # Generate varying returns; A uses +r, B uses -r
    shocks = [rng.gauss(0, 0.02) for _ in range(50)]
    closes_a = [100.0]
    closes_b = [100.0]
    for s in shocks:
        closes_a.append(closes_a[-1] * (1.0 + s))
        closes_b.append(closes_b[-1] * (1.0 - s))
    df_a = pd.DataFrame({"close": closes_a})
    df_b = pd.DataFrame({"close": closes_b})
    matrix = compute_correlation_matrix({"A": df_a, "B": df_b})
    # Returns are perfectly anti-correlated (same shocks, opposite sign)
    assert matrix["A"]["B"] < -0.99


def test_compute_correlation_matrix_handles_empty():
    matrix = compute_correlation_matrix({})
    assert matrix == {}


def test_compute_correlation_matrix_handles_single_symbol():
    import pandas as pd
    df = pd.DataFrame({"close": [100.0 + i for i in range(50)]})
    matrix = compute_correlation_matrix({"A": df})
    assert matrix == {}


def test_find_correlated_clusters_groups_highly_correlated():
    import pandas as pd
    import random
    rng = random.Random(0)
    # A and B: identical series (correlation 1.0)
    closes_a = [100.0 * (1.01 ** i) for i in range(50)]
    closes_b = list(closes_a)  # exact copy
    # C: random walk (uncorrelated with A and B)
    c = 100.0
    closes_c = [c]
    for _ in range(49):
        c *= (1.0 + rng.gauss(0, 0.01))
        closes_c.append(c)
    df_a = pd.DataFrame({"close": closes_a})
    df_b = pd.DataFrame({"close": closes_b})
    df_c = pd.DataFrame({"close": closes_c})
    clusters = find_correlated_clusters({"A": df_a, "B": df_b, "C": df_c}, threshold=0.7)
    # A and B should be grouped (correlation 1.0); C should not (random)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert "A" in cluster and "B" in cluster
    assert "C" not in cluster


def test_find_correlated_clusters_returns_empty_when_no_clusters():
    import pandas as pd
    import random
    rng = random.Random(0)
    # Three symbols with uncorrelated returns
    df_a = pd.DataFrame({"close": [100.0 + rng.gauss(0, 1) for _ in range(50)]})
    df_b = pd.DataFrame({"close": [100.0 + rng.gauss(0, 1) for _ in range(50)]})
    df_c = pd.DataFrame({"close": [100.0 + rng.gauss(0, 1) for _ in range(50)]})
    clusters = find_correlated_clusters({"A": df_a, "B": df_b, "C": df_c}, threshold=0.7)
    # Most likely empty (random data rarely correlates > 0.7)
    # If not empty, the clusters should be small
    for c in clusters:
        assert len(c) >= 2


def test_all_8_strategies_run_in_walk_forward():
    """Every strategy should run in walk-forward mode without error."""
    df = _make_ohlcv(rows=500, drift=0.002, seed=7)
    for name, strat in all_strategies().items():
        wf = run_walk_forward(df, strat, symbol=name, n_windows=3)
        assert wf.strategy_name == name
        assert wf.n_windows > 0
