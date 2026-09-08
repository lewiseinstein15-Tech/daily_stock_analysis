# -*- coding: utf-8 -*-
"""Tests for the indicator engine."""

import math
import pandas as pd

from jexi_market.indicators import (
    atr,
    bollinger,
    compute_factors,
    drawdown,
    ema,
    macd,
    max_drawdown,
    rsi_wilder,
    sharpe_ratio,
    sma,
    sortino_ratio,
)


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 3) == 4.0  # avg of last 3 = (3+4+5)/3
    assert sma([1, 2], 5) is None  # not enough data


def test_ema_basic():
    values = [10, 11, 12, 13, 14, 15]
    result = ema(values, 3)
    assert result is not None
    assert 13 < result < 15  # somewhere between SMA and latest


def test_rsi_wilder_neutral():
    # Flat series -> no losses -> RSI = 100 (Wilder's convention)
    closes = [100.0] * 30
    rsi = rsi_wilder(closes, 14)
    assert rsi is not None
    assert rsi == 100.0  # no down-moves => RSI maximum


def test_rsi_wilder_overbought():
    # Rising series -> RSI high
    closes = [100.0 + i for i in range(50)]
    rsi = rsi_wilder(closes, 14)
    assert rsi is not None
    assert rsi > 80


def test_rsi_wilder_oversold():
    # Falling series -> RSI low
    closes = [100.0 - i for i in range(50)]
    rsi = rsi_wilder(closes, 14)
    assert rsi is not None
    assert rsi < 20


def test_macd_returns_tuple():
    closes = [100.0 + i * 0.5 for i in range(60)]
    m, s, h = macd(closes)
    assert m is not None
    assert s is not None
    assert h is not None


def test_bollinger_bands():
    closes = [100.0 + (i % 5 - 2) * 0.5 for i in range(30)]
    upper, middle, lower = bollinger(closes, 20, 2.0)
    assert upper is not None and middle is not None and lower is not None
    assert upper > middle > lower


def test_atr_positive():
    highs = [105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120]
    lows = [95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
    closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115]
    result = atr(highs, lows, closes, 14)
    assert result is not None
    assert result > 0


def test_drawdown_basic():
    # Peak at 100, then drop to 80 -> 20% drawdown
    closes = [100, 95, 90, 80, 85]
    dd = drawdown(closes)
    assert 0.19 < dd < 0.21


def test_max_drawdown():
    closes = [100, 110, 90, 95, 105]
    md = max_drawdown(closes)
    # Peak 110, trough 90 -> ~18% drawdown
    assert 0.16 < md < 0.19


def test_sharpe_zero_when_no_returns():
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([0.0]) == 0.0


def test_sharpe_positive_for_positive_returns():
    # Use varied positive returns so variance is non-zero
    import random
    rng = random.Random(0)
    rets = [rng.uniform(0.0005, 0.0015) for _ in range(100)]
    s = sharpe_ratio(rets)
    assert s > 0


def test_sortino_handles_no_downside():
    rets = [0.01] * 50  # all positive
    s = sortino_ratio(rets)
    assert s == float("inf")


def test_compute_factors_returns_snapshot():
    df = pd.DataFrame({
        "date": [f"2024-01-{i:02d}" for i in range(1, 31)],
        "open": [100.0] * 30,
        "high": [105.0] * 30,
        "low": [95.0] * 30,
        "close": [100.0 + i * 0.5 for i in range(30)],
        "volume": [1_000_000] * 30,
    })
    snap = compute_factors(df, symbol="TEST")
    assert snap.symbol == "TEST"
    assert snap.rows == 30
    assert snap.latest_close > 100
    assert snap.sma_5 is not None
    assert snap.rsi_14 is not None
    assert snap.annualised_vol >= 0


def test_compute_factors_handles_empty_df():
    snap = compute_factors(None, symbol="EMPTY")
    assert snap.rows == 0
    assert snap.latest_close == 0.0


def test_compute_factors_handles_short_df():
    df = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "close": [100.0, 101.0],
        "volume": [1_000, 2_000],
    })
    snap = compute_factors(df, symbol="SHORT")
    assert snap.rows == 2
    assert snap.sma_200 is None  # not enough data
