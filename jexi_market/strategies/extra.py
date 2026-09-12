# -*- coding: utf-8 -*-
"""v0.3 strategy expansion — seven new deterministic families + ensemble.

Importing this module registers the strategies in the central registry
(the CLI imports it lazily so ``compare-strategies`` sees them):

* ``donchian_breakout``      — alias of the fixed registry breakout
* ``bollinger_squeeze``     — trade the expansion after a volatility squeeze
* ``triple_ma_cross``       — SMA 9/21/50 alignment (trend rider)
* ``supertrend``            — ATR-banded trend state (simplified)
* ``momentum_12_1``         — 12-month momentum skipping the last month
                              (academic cross-sectional momentum, proxied
                              on daily bars)
* ``williams_reversal``     — Williams %R extreme + trend filter
* ``vwap_reversion``        — rolling VWAP mean-reversion
* ``ensemble_consensus``    — meta-strategy: weighted vote across every
                              registered strategy; the weight of each
                              strategy is its own |score|, so strong
                              convictions dominate weak ones.

All strategies consume only the shared :class:`FactorSnapshot` — no LLM,
no network, fully deterministic and backtestable.
"""

from __future__ import annotations

from typing import Any, Dict, List

from jexi_market.contracts import SignalDirection
from jexi_market.indicators import FactorSnapshot
from jexi_market.strategies import Strategy, StrategyResult, all_strategies, register_strategy


def _bollinger_squeeze(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Trade the break after a squeeze (bandwidth at a local minimum).

    Bandwidth = (upper - lower) / middle.  A squeeze (bandwidth < 4% of
    price with 120 rows of context) followed by a directional close
    beyond the middle band sets up the classic expansion trade.
    """
    if factors.rows < 60 or not factors.bb_upper or not factors.bb_lower or not factors.bb_middle:
        return StrategyResult(rationale="insufficient bands")
    bandwidth = (factors.bb_upper - factors.bb_lower) / factors.bb_middle
    score = 0.0
    if bandwidth < 0.04:
        # Squeezed — direction comes from where price sits vs the middle
        # band plus short momentum.
        if factors.latest_close > factors.bb_middle and factors.momentum_3d > 0:
            score += 0.45
        elif factors.latest_close < factors.bb_middle and factors.momentum_3d < 0:
            score -= 0.45
        if factors.volume_ratio_5_20 > 1.2:
            score *= 1.2
    else:
        return StrategyResult(rationale=f"no squeeze (bandwidth {bandwidth:.1%})")
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=max(0.03, (factors.atr_pct or 0.02) * 1.5),
        target_pct=max(0.06, (factors.atr_pct or 0.02) * 3.0),
        rationale=f"bollinger-squeeze score {score:+.2f} (bw {bandwidth:.1%})",
        params_used=params,
    )


def _triple_ma_cross(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """SMA 9 > SMA 21 > SMA 50 stack → long (inverse → short)."""
    if factors.rows < 55:
        return StrategyResult(rationale="insufficient history")
    s9, s21, s50 = factors.sma_9, factors.sma_21, factors.sma_50
    if not (s9 and s21 and s50):
        return StrategyResult(rationale="missing MA data")
    if s9 > s21 > s50 and factors.latest_close > s9:
        score = 0.6
        if factors.macd_hist and factors.macd_hist > 0:
            score += 0.1
    elif s9 < s21 < s50 and factors.latest_close < s9:
        score = -0.6
        if factors.macd_hist and factors.macd_hist < 0:
            score -= 0.1
    else:
        return StrategyResult(rationale="no MA stack")
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.05,
        target_pct=0.12,
        rationale=f"triple-MA score {score:+.2f}",
        params_used=params,
    )


def _supertrend(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Simplified supertrend state from the current ATR band.

    Classic supertrend needs the full band-rolloff series; this single-
    shot approximation treats price above the (median - 3×ATR) band as
    an uptrend state and below (median + 3×ATR) as downtrend, using the
    SMA50 as the median proxy.  Good enough as a *confirming* vote in
    the ensemble; not a standalone supertrend replacement.
    """
    if factors.rows < 60 or not factors.atr_14 or not factors.sma_50:
        return StrategyResult(rationale="insufficient history")
    upper_band = factors.sma_50 + 3.0 * factors.atr_14
    lower_band = factors.sma_50 - 3.0 * factors.atr_14
    if factors.latest_close > upper_band:
        score = 0.5
    elif factors.latest_close < lower_band:
        score = -0.5
    else:
        return StrategyResult(rationale="inside supertrend bands")
    # Trend consistency bonus
    if score > 0 and factors.momentum_10d > 0:
        score += 0.1
    if score < 0 and factors.momentum_10d < 0:
        score -= 0.1
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=max(0.04, (factors.atr_pct or 0.02) * 2.0),
        target_pct=max(0.08, (factors.atr_pct or 0.02) * 4.0),
        rationale=f"supertrend score {score:+.2f}",
        params_used=params,
    )


def _momentum_12_1(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Cross-sectional momentum proxy: 12-month return skipping the last
    month (momentum_63d here is the 3-month analog; the 12-1 shape is
    approximated with the available lookback — strong positive skip-
    month momentum → long, negative → short).
    """
    if factors.rows < 70:
        return StrategyResult(rationale="insufficient history")
    # momentum_63d ≈ 3 months.  A 12-1 proxy on daily data: weight the
    # long momentum more than the recent month (which is skipped).
    long_mom = factors.momentum_63d
    recent_mom = factors.momentum_20d
    score = long_mom * 3.0 - 0.5 * recent_mom   # skip-month emphasis
    score = max(-1.0, min(1.0, score))
    if abs(score) < 0.25:
        return StrategyResult(rationale=f"no momentum edge ({score:+.2f})")
    direction = SignalDirection.LONG if score > 0 else SignalDirection.SHORT
    return StrategyResult(
        direction=direction,
        score=score,
        stop_pct=0.08,
        target_pct=0.20,
        rationale=f"momentum-12-1 score {score:+.2f} (3m {long_mom:+.1%})",
        params_used=params,
    )


def _williams_reversal(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Williams %R oversold bounce / overbought fade with MA filter."""
    if factors.rows < 30 or factors.williams_r_14 is None:
        return StrategyResult(rationale="insufficient history")
    wr = factors.williams_r_14
    score = 0.0
    if wr <= -80:
        score += 0.4
    elif wr >= -20:
        score -= 0.4
    # Filter: only fade against over-extensions in a stable regime
    if factors.sma_50 and factors.latest_close and factors.sma_50:
        above = factors.latest_close > factors.sma_50
        if score > 0 and above:
            score += 0.1   # buying dips in an uptrend
        elif score < 0 and not above:
            score -= 0.1   # fading rips in a downtrend
        else:
            score *= 0.6   # counter-trend fade — dampen
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=0.04,
        target_pct=0.08,
        rationale=f"williams %R {wr:.0f} → score {score:+.2f}",
        params_used=params,
    )


def _vwap_reversion(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Rolling VWAP mean-reversion with ATR-normalised deviation."""
    if factors.rows < 30 or not factors.vwap_20 or not factors.latest_close:
        return StrategyResult(rationale="insufficient VWAP data")
    deviation = (factors.latest_close - factors.vwap_20) / factors.vwap_20
    atr_pct = factors.atr_pct or 0.02
    z = deviation / max(atr_pct, 1e-6)   # deviation in ATR units
    score = 0.0
    if z <= -2.0:
        score += min(0.6, 0.3 + abs(z - 2.0) * 0.05)
    elif z >= 2.0:
        score -= min(0.6, 0.3 + abs(z + 2.0) * 0.05)
    else:
        return StrategyResult(rationale=f"near VWAP (z={z:+.1f})")
    direction = SignalDirection.LONG if score >= 0.3 else (SignalDirection.SHORT if score <= -0.3 else SignalDirection.FLAT)
    return StrategyResult(
        direction=direction,
        score=max(-1.0, min(1.0, score)),
        stop_pct=max(0.03, atr_pct * 1.5),
        target_pct=max(0.05, atr_pct * 2.5),
        rationale=f"vwap-reversion z={z:+.1f} score {score:+.2f}",
        params_used=params,
    )


def _ensemble_consensus(factors: FactorSnapshot, params: Dict[str, Any]) -> StrategyResult:
    """Meta-strategy: |score|-weighted vote across all other strategies.

    This is JEXI Market's "many hands" edge: rather than trusting one
    family, every registered strategy votes and strong convictions
    dominate.  Excludes itself to avoid recursion.  Requires a 60%
    supermajority of voting weight to emit a non-flat signal — a loose
    consensus stays flat.
    """
    votes_long = 0.0
    votes_short = 0.0
    total = 0.0
    details: List[str] = []
    for name, strategy in sorted(all_strategies().items()):
        if name == "ensemble_consensus":
            continue
        res = strategy.run(factors)
        weight = abs(res.score) if res.direction != SignalDirection.FLAT else 0.0
        total += 1.0
        if res.direction == SignalDirection.LONG:
            votes_long += weight
            details.append(f"{name}:+{weight:.2f}")
        elif res.direction == SignalDirection.SHORT:
            votes_short += weight
            details.append(f"{name}:-{weight:.2f}")
    vote_total = votes_long + votes_short
    if vote_total <= 0:
        return StrategyResult(rationale="ensemble: no votes")
    long_share = votes_long / vote_total
    if long_share >= 0.60:
        direction = SignalDirection.LONG
        score = min(1.0, 0.4 + 0.6 * long_share)
    elif long_share <= 0.40:
        direction = SignalDirection.SHORT
        score = min(1.0, 0.4 + 0.6 * (1.0 - long_share))
    else:
        return StrategyResult(
            direction=SignalDirection.FLAT,
            rationale=f"ensemble split {long_share:.0%} long — no supermajority",
        )
    return StrategyResult(
        direction=direction,
        score=score,
        stop_pct=0.05,
        target_pct=0.12,
        rationale=f"ensemble {direction.value} ({long_share:.0%} long weight; {' '.join(details[:5])})",
        params_used=params,
    )


register_strategy(Strategy(
    name="bollinger_squeeze",
    description="Volatility-squeeze expansion trade (Bollinger bandwidth + momentum)",
    regime="sideways",
    fn=_bollinger_squeeze,
))
register_strategy(Strategy(
    name="triple_ma_cross",
    description="SMA 9/21/50 stack alignment with MACD confirmation",
    regime="bull",
    fn=_triple_ma_cross,
))
register_strategy(Strategy(
    name="supertrend",
    description="ATR-banded trend state (simplified supertrend)",
    regime="bull",
    fn=_supertrend,
))
register_strategy(Strategy(
    name="momentum_12_1",
    description="Skip-month momentum proxy (3m momentum emphasized, 1m skipped)",
    regime="any",
    fn=_momentum_12_1,
))
register_strategy(Strategy(
    name="williams_reversal",
    description="Williams %R extremes with trend-aware damping",
    regime="sideways",
    fn=_williams_reversal,
))
register_strategy(Strategy(
    name="vwap_reversion",
    description="Rolling VWAP mean-reversion in ATR units",
    regime="sideways",
    fn=_vwap_reversion,
))
register_strategy(Strategy(
    name="ensemble_consensus",
    description="Weighted vote across all registered strategies (60% supermajority)",
    regime="any",
    fn=_ensemble_consensus,
))
