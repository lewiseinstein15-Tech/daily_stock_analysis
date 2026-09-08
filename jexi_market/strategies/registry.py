# -*- coding: utf-8 -*-
"""Strategy framework for JEXI Market.

A strategy in JEXI Market is a deterministic, parameterisable function
that consumes a :class:`FactorSnapshot` and produces a directional
signal + position-sizing hint.  Strategies are NOT agents — they're
pluggable building blocks the Strategy Agent (and the backtester) use
to compare multiple edges on the same data.

The framework supports multiple strategy families (trend, momentum,
mean-reversion, breakout, factor-based) and a registry so new
strategies can be added with a single decorator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jexi_market.contracts import SignalDirection
from jexi_market.indicators import FactorSnapshot


@dataclass
class StrategyResult:
    """Output of a single strategy pass."""

    direction: SignalDirection = SignalDirection.FLAT
    score: float = 0.0           # -1..1, conviction
    stop_pct: float = 0.05
    target_pct: float = 0.10
    rationale: str = ""
    params_used: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction.value,
            "score": round(self.score, 4),
            "stop_pct": round(self.stop_pct, 4),
            "target_pct": round(self.target_pct, 4),
            "rationale": self.rationale,
            "params_used": self.params_used,
        }


@dataclass
class Strategy:
    """Base strategy description (metadata + entry/exit/risk model)."""

    name: str
    description: str
    regime: str = "any"          # bull / bear / sideways / volatile / any
    required_data: str = "ohlcv"
    parameters: Dict[str, Any] = field(default_factory=dict)
    benchmark: str = "SPY"
    validation_status: str = "unvalidated"

    # The actual signal function — set by the concrete subclass or
    # by the registry decorator.
    fn: Callable[[FactorSnapshot, Dict[str, Any]], StrategyResult] = field(
        default=lambda factors, params: StrategyResult()
    )

    def run(self, factors: FactorSnapshot) -> StrategyResult:
        try:
            return self.fn(factors, dict(self.parameters))
        except Exception as exc:
            return StrategyResult(
                direction=SignalDirection.FLAT,
                rationale=f"strategy error: {exc}",
                params_used=dict(self.parameters),
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "regime": self.regime,
            "required_data": self.required_data,
            "parameters": self.parameters,
            "benchmark": self.benchmark,
            "validation_status": self.validation_status,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_STRATEGY_REGISTRY: Dict[str, Strategy] = {}


def register_strategy(strategy: Strategy) -> Strategy:
    if strategy.name in _STRATEGY_REGISTRY:
        raise ValueError(f"duplicate strategy: {strategy.name}")
    _STRATEGY_REGISTRY[strategy.name] = strategy
    return strategy


def get_strategy(name: str) -> Optional[Strategy]:
    return _STRATEGY_REGISTRY.get(name)


def list_strategies() -> List[str]:
    return list(_STRATEGY_REGISTRY.keys())


def all_strategies() -> Dict[str, Strategy]:
    return dict(_STRATEGY_REGISTRY)


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------


def _trend_following(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Trend following: long when price > SMA50 > SMA200 (or shorter analogues)."""
    if factors.rows < 50:
        return StrategyResult(rationale="insufficient history")
    score = 0.0
    if factors.sma_20 and factors.sma_50:
        if factors.latest_close > factors.sma_20 > factors.sma_50:
            score += 0.5
        elif factors.latest_close < factors.sma_20 < factors.sma_50:
            score -= 0.5
    if factors.momentum_20d > 0.05:
        score += 0.2
    elif factors.momentum_20d < -0.05:
        score -= 0.2
    direction = SignalDirection.LONG if score >= 0.4 else (SignalDirection.SHORT if score <= -0.4 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.06,
        target_pct=0.12,
        rationale=f"trend-following score {score:+.2f}",
        params_used=params,
    )


def _momentum(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Momentum: blended 3d/10d/20d return + volume confirmation."""
    if factors.rows < 30:
        return StrategyResult(rationale="insufficient history")
    mom = 0.5 * factors.momentum_3d + 0.3 * factors.momentum_10d + 0.2 * factors.momentum_20d
    score = mom * 5.0  # scale up
    if factors.volume_ratio_5_20 > 1.3:
        score *= 1.2
    elif factors.volume_ratio_5_20 < 0.7:
        score *= 0.8
    direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.05,
        target_pct=0.10,
        rationale=f"momentum score {score:+.2f} (vol ratio {factors.volume_ratio_5_20:.2f})",
        params_used=params,
    )


def _mean_reversion(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Mean reversion: Bollinger band extremes + RSI confirmation."""
    if factors.rows < 30 or not factors.bb_upper or not factors.bb_lower:
        return StrategyResult(rationale="insufficient history for bands")
    width = factors.bb_upper - factors.bb_lower
    if width <= 0:
        return StrategyResult(rationale="zero band width")
    pos = (factors.latest_close - factors.bb_lower) / width  # 0..1
    score = 0.0
    if pos < 0.2:
        score += 0.4
    elif pos > 0.8:
        score -= 0.4
    if factors.rsi_14 is not None:
        if factors.rsi_14 < 30:
            score += 0.2
        elif factors.rsi_14 > 70:
            score -= 0.2
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.04,
        target_pct=0.06,
        rationale=f"mean-reversion score {score:+.2f} (bb pos {pos:.2f})",
        params_used=params,
    )


def _breakout(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Breakout: close above 20-day high → long; below 20-day low → short."""
    if factors.rows < 25:
        return StrategyResult(rationale="insufficient history")
    # We don't have the high/low series here directly; approximate with ATR.
    if not factors.atr_14 or not factors.latest_close:
        return StrategyResult(rationale="no ATR data")
    upper = factors.latest_close + factors.atr_14
    lower = factors.latest_close - factors.atr_14
    # Use momentum as a proxy for breakout direction
    score = 0.0
    if factors.momentum_3d > 0.02 and factors.volume_ratio_5_20 > 1.2:
        score += 0.5
    elif factors.momentum_3d < -0.02 and factors.volume_ratio_5_20 > 1.2:
        score -= 0.5
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.05,
        target_pct=0.15,
        rationale=f"breakout score {score:+.2f} (ATR {factors.atr_14:.2f})",
        params_used=params,
    )


def _factor_value(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Factor-based: low-volatility + RSI undervaluation."""
    if factors.rows < 50:
        return StrategyResult(rationale="insufficient history")
    score = 0.0
    if factors.annualised_vol < 0.25:
        score += 0.2
    if factors.rsi_14 is not None and factors.rsi_14 < 40:
        score += 0.2
    if factors.drawdown > 0.1:
        score += 0.1  # bought at a discount
    direction = SignalDirection.LONG if score >= 0.3 else SignalDirection.FLAT
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.05,
        target_pct=0.08,
        rationale=f"factor-value score {score:+.2f} (vol {factors.annualised_vol:.0%})",
        params_used=params,
    )


# Register built-in strategies at import time.
register_strategy(Strategy(
    name="trend_following",
    description="Long when price > SMA20 > SMA50 with positive 20d momentum",
    regime="bull",
    parameters={},
    benchmark="SPY",
    validation_status="unvalidated",
    fn=_trend_following,
))

register_strategy(Strategy(
    name="momentum",
    description="Blended 3d/10d/20d momentum with volume confirmation",
    regime="bull",
    parameters={},
    benchmark="QQQ",
    validation_status="unvalidated",
    fn=_momentum,
))

register_strategy(Strategy(
    name="mean_reversion",
    description="Bollinger band extremes with RSI confirmation",
    regime="sideways",
    parameters={},
    benchmark="SPY",
    validation_status="unvalidated",
    fn=_mean_reversion,
))

register_strategy(Strategy(
    name="breakout",
    description="ATR-based breakout with volume confirmation",
    regime="volatile",
    parameters={},
    benchmark="QQQ",
    validation_status="unvalidated",
    fn=_breakout,
))

register_strategy(Strategy(
    name="factor_value",
    description="Low-volatility + RSI undervaluation + drawdown discount",
    regime="bear",
    parameters={},
    benchmark="SPY",
    validation_status="unvalidated",
    fn=_factor_value,
))
