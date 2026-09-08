# -*- coding: utf-8 -*-
"""Pure-Python indicator engine for JEXI Market specialists.

This module computes the shared factor set (momentum, trend, RSI, MACD,
Bollinger, ATR, volatility, volume profile, etc.) that every specialist
agent reads from.  Keeping it in one place means:

1. No two agents ever compute RSI differently.
2. The output is fully deterministic given the same OHLCV frame —
   tests are reproducible.
3. The cost is one pass per symbol, even when 6 agents consume it.

The math here is deliberately standard (Wilder's RSI, standard MACD,
Bollinger with 2σ bands, annualised volatility from daily returns).
Where the repo's ``src/jexi/specialist.py`` already implements a factor
score, we reuse those formulas to stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Per-series helpers (operate on plain Python lists for portability)
# ---------------------------------------------------------------------------


def sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def ema(values: List[float], window: int) -> Optional[float]:
    """Standard EMA over the whole series, return the latest value."""
    if not values or window <= 0:
        return None
    if len(values) < window:
        return sum(values) / len(values)
    alpha = 2.0 / (window + 1.0)
    ema_prev = sum(values[:window]) / window
    for v in values[window:]:
        ema_prev = alpha * v + (1.0 - alpha) * ema_prev
    return ema_prev


def rsi_wilder(closes: List[float], window: int = 14) -> Optional[float]:
    if len(closes) <= window:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram) or None triple."""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast_series: List[float] = []
    ema_slow_series: List[float] = []
    alpha_fast = 2.0 / (fast + 1.0)
    alpha_slow = 2.0 / (slow + 1.0)
    ef = sum(closes[:fast]) / fast
    es = sum(closes[:slow]) / slow
    for i, v in enumerate(closes):
        if i >= fast - 1:
            ef = alpha_fast * v + (1.0 - alpha_fast) * ef
            ema_fast_series.append(ef)
        if i >= slow - 1:
            es = alpha_slow * v + (1.0 - alpha_slow) * es
            ema_slow_series.append(es)
    n = min(len(ema_fast_series), len(ema_slow_series))
    macd_series = [ema_fast_series[-n + i] - ema_slow_series[-n + i] for i in range(n)]
    signal_series: List[float] = []
    alpha_sig = 2.0 / (signal + 1.0)
    if len(macd_series) < signal:
        return macd_series[-1] if macd_series else None, None, None
    sig = sum(macd_series[:signal]) / signal
    for v in macd_series[signal:]:
        sig = alpha_sig * v + (1.0 - alpha_sig) * sig
        signal_series.append(sig)
    if not signal_series:
        return macd_series[-1], None, None
    return macd_series[-1], signal_series[-1], macd_series[-1] - signal_series[-1]


def bollinger(closes: List[float], window: int = 20, num_std: float = 2.0):
    """Return (upper, middle, lower) Bollinger bands or None triple."""
    if len(closes) < window:
        return None, None, None
    window_slice = closes[-window:]
    middle = sum(window_slice) / window
    variance = sum((v - middle) ** 2 for v in window_slice) / window
    sd = variance ** 0.5
    return middle + num_std * sd, middle, middle - num_std * sd


def atr(highs: List[float], lows: List[float], closes: List[float], window: int = 14) -> Optional[float]:
    """Average True Range (Wilder)."""
    if len(closes) <= window:
        return None
    trs: List[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < window:
        return sum(trs) / len(trs) if trs else None
    atr_prev = sum(trs[:window]) / window
    for i in range(window, len(trs)):
        atr_prev = (atr_prev * (window - 1) + trs[i]) / window
    return atr_prev


def annualised_volatility(closes: List[float]) -> float:
    if len(closes) < 2:
        return 0.0
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            rets.append(closes[i] / closes[i - 1] - 1.0)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return (var ** 0.5) * (252 ** 0.5)


def drawdown(closes: List[float]) -> float:
    """Current drawdown from the running peak (fraction, 0..1)."""
    if not closes:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def max_drawdown(closes: List[float]) -> float:
    """Peak-to-trough maximum drawdown over the series."""
    return drawdown(closes)


def sharpe_ratio(returns: List[float], risk_free: float = 0.0, periods: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns) - risk_free / periods
    var = sum((r - (sum(returns) / len(returns))) ** 2 for r in returns) / max(1, len(returns) - 1)
    sd = var ** 0.5
    if sd == 0:
        return 0.0
    return (mean / sd) * (periods ** 0.5)


def sortino_ratio(returns: List[float], risk_free: float = 0.0, periods: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns) - risk_free / periods
    downside = [r for r in returns if r < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    var_down = sum(r ** 2 for r in downside) / len(downside)
    sd_down = var_down ** 0.5
    if sd_down == 0:
        return 0.0
    return (mean / sd_down) * (periods ** 0.5)


# ---------------------------------------------------------------------------
# Factor snapshot
# ---------------------------------------------------------------------------


@dataclass
class FactorSnapshot:
    """All indicators a specialist agent needs, pre-computed once."""

    symbol: str
    rows: int = 0
    latest_close: float = 0.0
    sma_5: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    atr_14: Optional[float] = None
    annualised_vol: float = 0.0
    drawdown: float = 0.0
    momentum_3d: float = 0.0
    momentum_10d: float = 0.0
    momentum_20d: float = 0.0
    volume_ratio_5_20: float = 1.0
    up_day_volume_dominance: float = 0.5

    def to_dict(self) -> Dict[str, float]:
        out: Dict[str, float] = {"rows": float(self.rows), "latest_close": self.latest_close}
        for k, v in self.__dict__.items():
            if k in {"symbol", "rows", "latest_close"}:
                continue
            if v is None:
                continue
            try:
                out[k] = round(float(v), 4)
            except (TypeError, ValueError):
                continue
        return out


def compute_factors(df: Optional[pd.DataFrame], symbol: str = "") -> FactorSnapshot:
    """Compute a full :class:`FactorSnapshot` from a daily OHLCV frame.

    Expected columns: ``date, open, high, low, close, volume``.  Missing
    columns degrade gracefully to ``None`` / defaults — the snapshot is
    still returned, just with fewer populated fields.
    """
    snap = FactorSnapshot(symbol=symbol)
    if df is None or df.empty:
        return snap

    closes: List[float] = [float(x) for x in df["close"].dropna().tolist()] if "close" in df.columns else []
    highs: List[float] = [float(x) for x in df["high"].dropna().tolist()] if "high" in df.columns else closes
    lows: List[float] = [float(x) for x in df["low"].dropna().tolist()] if "low" in df.columns else closes
    volumes: List[float] = [float(x) for x in df["volume"].dropna().tolist()] if "volume" in df.columns else []

    snap.rows = len(closes)
    if not closes:
        return snap
    snap.latest_close = closes[-1]

    snap.sma_5 = sma(closes, 5)
    snap.sma_20 = sma(closes, 20)
    snap.sma_50 = sma(closes, 50)
    snap.sma_200 = sma(closes, 200)
    snap.rsi_14 = rsi_wilder(closes, 14)
    m_line, s_line, h = macd(closes)
    snap.macd_line = m_line
    snap.macd_signal = s_line
    snap.macd_hist = h
    bb = bollinger(closes)
    if bb and bb[0] is not None:
        snap.bb_upper, snap.bb_middle, snap.bb_lower = bb
    snap.atr_14 = atr(highs, lows, closes, 14)
    snap.annualised_vol = annualised_volatility(closes)
    snap.drawdown = drawdown(closes)

    def pct_return(n: int) -> float:
        if len(closes) <= n or closes[-1 - n] == 0:
            return 0.0
        return closes[-1] / closes[-1 - n] - 1.0

    snap.momentum_3d = pct_return(3)
    snap.momentum_10d = pct_return(10)
    snap.momentum_20d = pct_return(20)

    if len(volumes) >= 20:
        recent = sum(volumes[-5:]) / 5
        older = sum(volumes[-20:]) / 20
        snap.volume_ratio_5_20 = (recent / older) if older else 1.0
    if len(closes) >= 6 and len(volumes) >= 6:
        up_vol = 0.0
        total_vol = 0.0
        for i in range(max(1, len(closes) - 5), len(closes)):
            if closes[i] >= closes[i - 1]:
                up_vol += volumes[i]
            total_vol += volumes[i]
        snap.up_day_volume_dominance = (up_vol / total_vol) if total_vol else 0.5

    return snap
