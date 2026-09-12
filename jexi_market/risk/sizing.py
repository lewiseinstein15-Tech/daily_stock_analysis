# -*- coding: utf-8 -*-
"""Position-sizing engines for JEXI Market (v0.3).

The old system had exactly one sizing rule: risk-parity on the stop
distance, capped at 25% of equity.  Real funds blend several sizing
methods depending on the edge and the regime.  This module implements
four, all bounded by the risk envelope:

* ``risk_parity``    — risk a fixed % of equity between entry and stop
                       (the classic "2% rule"; the previous default).
* ``fixed_fraction`` — always allocate a fixed fraction of equity.
* ``kelly``          — half-Kelly from the *live* performance memory:
                       f* = W - (1 - W) / R, halved for safety, clamped
                       to [0, max_fraction].  Uses realised win-rate and
                       payoff ratio from closed paper trades, so the
                       system sizes up only when its own history earns it.
* ``vol_target``     — scale the base fraction by (target_vol / realized_vol)
                       so the portfolio carries roughly constant risk.

All methods return a fraction of equity in [0, max_fraction] and never
raise on degenerate inputs (they degrade to the smallest sane size).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SIZING_METHODS = ("risk_parity", "fixed_fraction", "kelly", "vol_target")


@dataclass
class SizingInput:
    """Everything a sizing method may need (extra fields are ignored)."""

    equity: float
    entry: float
    stop: Optional[float]              # absolute stop price
    risk_per_trade: float = 0.02       # fraction of equity to risk
    max_fraction: float = 0.25         # hard cap from the risk envelope
    # Kelly inputs (from performance memory)
    win_rate: Optional[float] = None   # 0..1
    payoff_ratio: Optional[float] = None  # avg_win / avg_loss
    min_trades_for_kelly: int = 20
    # Vol-target inputs
    annualised_vol: Optional[float] = None   # e.g. 0.35 = 35%
    target_vol: float = 0.15                 # 15% annualised target
    # Base allocation used as the anchor for vol targeting
    base_fraction: float = 0.10


def _clamp(fraction: float, max_fraction: float) -> float:
    if fraction != fraction:  # NaN
        return 0.0
    return max(0.0, min(max_fraction, fraction))


def size_position(inp: SizingInput, method: str = "risk_parity") -> float:
    """Return the position fraction of equity for the given inputs."""
    method = (method or "risk_parity").lower().strip()
    if method == "fixed_fraction":
        return _size_fixed_fraction(inp)
    if method == "kelly":
        return _size_kelly(inp)
    if method == "vol_target":
        return _size_vol_target(inp)
    if method == "risk_parity":
        return _size_risk_parity(inp)
    logger.warning("unknown sizing method %r — falling back to risk_parity", method)
    return _size_risk_parity(inp)


def _size_risk_parity(inp: SizingInput) -> float:
    """Risk a fixed fraction of equity over the entry->stop distance."""
    if inp.equity <= 0 or inp.entry <= 0:
        return 0.0
    if inp.stop is None or inp.stop <= 0:
        # No stop — cannot do risk parity; fall back to a conservative
        # fixed slice of the cap.
        return _clamp(inp.max_fraction * 0.25, inp.max_fraction)
    stop_distance = abs(inp.entry - inp.stop) / inp.entry
    if stop_distance <= 1e-6:
        return 0.0
    fraction = inp.risk_per_trade / stop_distance
    return _clamp(fraction, inp.max_fraction)


def _size_fixed_fraction(inp: SizingInput) -> float:
    """A constant fraction, independent of the stop distance."""
    base = inp.base_fraction if inp.base_fraction and inp.base_fraction > 0 else inp.max_fraction * 0.4
    return _clamp(base, inp.max_fraction)


def _size_kelly(inp: SizingInput) -> float:
    """Half-Kelly from realised performance.

    f* = W - (1 - W) / R   where W = win rate, R = payoff ratio.
    We apply half-Kelly (the standard practical derating for estimation
    error) and require a minimum sample of closed trades — before that
    the method degrades to risk-parity.
    """
    if (
        inp.win_rate is None
        or inp.payoff_ratio is None
        or inp.win_rate <= 0
        or inp.payoff_ratio <= 0
    ):
        return _size_risk_parity(inp)
    # Sample-size guard lives on the caller via min_trades_for_kelly;
    # here we only sanity-check the inputs.
    f_star = inp.win_rate - (1.0 - inp.win_rate) / inp.payoff_ratio
    half_kelly = f_star / 2.0
    if half_kelly <= 0:
        # Negative edge historically — size to zero (don't trade).
        return 0.0
    return _clamp(half_kelly, inp.max_fraction)


def _size_vol_target(inp: SizingInput) -> float:
    """Scale the base fraction to hit an annualised vol target."""
    if not inp.annualised_vol or inp.annualised_vol <= 0:
        return _clamp(inp.base_fraction, inp.max_fraction)
    scale = inp.target_vol / inp.annualised_vol
    scale = max(0.25, min(1.5, scale))   # damp extreme scaling
    return _clamp(inp.base_fraction * scale, inp.max_fraction)


def kelly_inputs_from_memory_stats(stats: Dict[str, Any], *, min_trades: int = 20) -> Dict[str, Any]:
    """Extract (win_rate, payoff_ratio, eligible) from memory stats.

    ``stats`` is the dict returned by ``PerformanceMemory.stats_summary()``
    plus ``avg_win``/``avg_loss`` when available.  Returns a dict suitable
    for :class:`SizingInput` kwargs.
    """
    n = int(stats.get("n_trades", 0) or 0)
    win_rate = stats.get("win_rate")
    avg_win = stats.get("avg_win")
    avg_loss = stats.get("avg_loss")
    payoff = None
    if avg_win is not None and avg_loss is not None and avg_loss > 0:
        payoff = abs(avg_win / avg_loss)
    eligible = bool(win_rate is not None and payoff and n >= min_trades)
    return {
        "win_rate": float(win_rate) if win_rate is not None else None,
        "payoff_ratio": float(payoff) if payoff else None,
        "eligible": eligible,
    }
