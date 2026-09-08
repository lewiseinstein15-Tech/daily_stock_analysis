# -*- coding: utf-8 -*-
"""Market scanner for JEXI Market.

Identifies trade candidates by running configurable criteria across a
universe of symbols.  The scanner does NOT predict the market — it
identifies candidates for deeper analysis by the agent pipeline.

Default criteria (configurable via :class:`ScanConfig`):
  * unusual volume (5d avg > 1.3x 20d avg)
  * momentum (|3d return| > 2%)
  * volatility expansion (ATR / close > 3%)
  * RSI extremes (RSI < 30 or > 70)
  * drawdown from peak > 10%

The scanner uses the :class:`MarketDataClient` so it inherits the same
fallback behaviour (repo fetcher -> yfinance -> error).  It produces
typed :class:`ScanCandidate` records that the orchestrator feeds into
the agent pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from jexi_market.data import MarketDataClient, MarketSnapshot
from jexi_market.indicators import FactorSnapshot, compute_factors

logger = logging.getLogger(__name__)


@dataclass
class ScanConfig:
    """Configurable scan criteria thresholds."""

    min_volume_ratio: float = 1.3
    min_abs_momentum: float = 0.02
    min_atr_pct: float = 0.03
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    min_drawdown: float = 0.10
    max_results: int = 20


@dataclass
class ScanCandidate:
    """A symbol that triggered one or more scan criteria."""

    symbol: str
    score: float = 0.0
    triggered: List[str] = field(default_factory=list)
    factors: Optional[FactorSnapshot] = None
    snapshot: Optional[MarketSnapshot] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 4),
            "triggered": self.triggered,
            "factors": self.factors.to_dict() if self.factors else None,
            "latest_price": self.factors.latest_close if self.factors else None,
        }


class MarketScanner:
    """Scan a universe of symbols for trade candidates."""

    def __init__(self, client: Optional[MarketDataClient] = None, config: Optional[ScanConfig] = None):
        self.client = client or MarketDataClient()
        self.config = config or ScanConfig()

    def scan(self, symbols: List[str], *, days: int = 120) -> List[ScanCandidate]:
        candidates: List[ScanCandidate] = []
        for symbol in symbols:
            snapshot = self.client.get_daily(symbol, days=days)
            if not snapshot.ok:
                continue
            factors = compute_factors(snapshot.df, symbol=symbol)
            triggered: List[str] = []
            score = 0.0

            if factors.volume_ratio_5_20 > self.config.min_volume_ratio:
                triggered.append("unusual_volume")
                score += 0.2
            if abs(factors.momentum_3d) > self.config.min_abs_momentum:
                triggered.append("momentum")
                score += 0.2
            if factors.atr_14 and factors.latest_close:
                atr_pct = factors.atr_14 / factors.latest_close
                if atr_pct > self.config.min_atr_pct:
                    triggered.append("volatility_expansion")
                    score += 0.15
            if factors.rsi_14 is not None:
                if factors.rsi_14 < self.config.rsi_oversold:
                    triggered.append("rsi_oversold")
                    score += 0.2
                elif factors.rsi_14 > self.config.rsi_overbought:
                    triggered.append("rsi_overbought")
                    score += 0.2
            if factors.drawdown > self.config.min_drawdown:
                triggered.append("drawdown")
                score += 0.15

            if triggered:
                candidates.append(ScanCandidate(
                    symbol=symbol,
                    score=score,
                    triggered=triggered,
                    factors=factors,
                    snapshot=snapshot,
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[: self.config.max_results]
