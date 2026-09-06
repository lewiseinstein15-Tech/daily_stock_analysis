# -*- coding: utf-8 -*-
"""Deterministic specialist runtime for J.E.X.I.

Each persona (see :mod:`src.jexi.persona`) maps to a *tilt* and *focus
metrics*.  This module implements a compact, offline-testable indicator engine
that produces a differentiated opinion per persona, so the pilot runs without
LLM keys.  When ``--llm`` is configured the same persona brief is used as the
system prompt for the repository's agent executor (LLM-backed mode), with this
deterministic result as a fallback.

This is a *default import-free-of-side-effects* module: it only needs pandas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.jexi.persona import Persona

# Signal constants shared with the report layer.
SIGNAL_LONG = "long"
SIGNAL_FLAT = "flat"
SIGNAL_SHORT = "short"

# Blend weights when an LLM research crossover is available.
_SCORE_BLEND_FACTOR = 0.65
_SCORE_BLEND_RESEARCH = 0.35


@dataclass
class SpecialistOpinion:
    persona: Persona
    score: float = 0.0
    signal: str = SIGNAL_FLAT
    confidence: float = 0.0
    rationale: List[str] = field(default_factory=list)
    factor_scores: Dict[str, float] = field(default_factory=dict)
    target_direction: Optional[str] = None
    research: Optional[dict] = None

    def to_dict(self) -> dict:
        payload = {
            "agent": self.persona.id,
            "name": self.persona.name,
            "role": self.persona.role,
            "signal": self.signal,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "tilt": self.persona.tilt,
            "factor_scores": {k: round(v, 4) for k, v in self.factor_scores.items()},
            "rationale": self.rationale,
            "target_direction": self.target_direction,
        }
        if self.research is not None:
            payload["research"] = self.research
        return payload


def _series_values(df, column: str):
    if column not in df.columns:
        return []
    return df[column].dropna().tolist()


def compute_factor_scores(df) -> Dict[str, float]:
    """Compute a shared factor set from a normalized daily OHLCV frame.

    Columns expected: ``date``, ``open``, ``high``, ``low``, ``close``,
    ``volume``; plus optional ``ma5/ma10/ma20/volume_ratio`` already computed
    by :class:`data_provider.base.BaseFetcher`.
    """
    if df is None or df.empty:
        return {k: 0.0 for k in ("momentum", "trend", "reversal", "volume", "flow", "volatility", "risk")}

    closes = _series_values(df, "close")
    volumes = _series_values(df, "volume")
    latest = float(closes[-1]) if closes else 0.0

    # Momentum: blend of 3d/10d/20d returns.
    def pct_return(n):
        if len(closes) <= n or closes[-1 - n] == 0:
            return 0.0
        return closes[-1] / closes[-1 - n] - 1.0

    momentum = 0.5 * pct_return(3) + 0.3 * pct_return(10) + 0.2 * pct_return(20)

    # Trend: price vs ma5/ma20 plus ma20 slope.
    ma5 = _series_values(df, "ma5")
    ma20 = _series_values(df, "ma20")
    trend = 0.0
    if ma5 and ma20:
        slope = (ma20[-1] - ma20[max(0, len(ma20) - 6)]) / (ma20[max(0, len(ma20) - 6)] or 1.0)
        trend = 0.6 * ((latest - ma20[-1]) / (ma20[-1] or 1.0)) + 0.4 * slope

    # Reversal: RSI(14) pulled toward its midpoint, sign flips for extremes.
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rsi = 50.0
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    reversal = -((rsi - 50.0) / 50.0)  # overbought -> negative score

    # Volume: recent participation compared to history.
    if len(volumes) >= 6:
        recent = sum(volumes[-5:]) / 5
        older = sum(volumes[-20:]) / min(20, len(volumes)) if len(volumes) >= 15 else recent
        volume = (recent / (older or 1.0)) - 1.0
        volume = max(-1.0, min(1.0, volume))
    else:
        volume = 0.0

    # Flow: up-day volume dominance over the last 5 days.
    flow = 0.0
    if len(closes) >= 2:
        up_vol = sum(
            volumes[i] for i in range(max(1, len(closes) - 5), len(closes))
            if closes[i] >= closes[i - 1]
        )
        window_vol = sum(volumes[max(1, len(closes) - 5):])
        if window_vol:
            flow = 2.0 * (up_vol / window_vol) - 1.0

    # Volatility: annualised std of daily returns.
    if len(closes) >= 2:
        returns = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] != 0]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / max(1, len(returns) - 1)
        volatility = min(2.0, (variance ** 0.5) * (252 ** 0.5))
    else:
        volatility = 0.0

    # Risk: high drawdown from 60d peak + fat volatility buffer.
    recent_window = closes[-60:]
    peak = max(recent_window) if recent_window else latest
    drawdown = (peak - latest) / (peak or 1.0) if peak else 0.0
    risk = 0.7 * drawdown + 0.3 * (volatility / 2.0)

    return {
        "momentum": momentum,
        "trend": trend,
        "reversal": reversal,
        "volume": volume,
        "flow": flow,
        "volatility": volatility,
        "risk": risk,
    }


def _tilt_weight(tilt: str, factor: str) -> float:
    """How much a tilt leans on each factor (all tilts see all factors)."""
    table = {
        "momentum": {"momentum": 2.0, "trend": 1.2, "flow": 0.8, "volume": 0.6, "reversal": 0.3, "volatility": 0.3, "risk": 0.2},
        "macro": {"trend": 2.0, "momentum": 1.0, "volatility": 0.7, "risk": 0.7, "flow": 0.4, "reversal": 0.3, "volume": 0.2},
        "value": {"reversal": 2.0, "trend": 1.0, "momentum": 0.8, "risk": 0.5, "volume": 0.3, "flow": 0.3, "volatility": 0.2},
        "sentiment": {"flow": 2.0, "reversal": 1.2, "momentum": 0.8, "volume": 0.6, "trend": 0.4, "volatility": 0.4, "risk": 0.2},
        "flow": {"flow": 2.0, "momentum": 1.2, "volume": 1.0, "trend": 0.6, "reversal": 0.3, "volatility": 0.3, "risk": 0.2},
        "risk": {"risk": 2.0, "volatility": 1.2, "trend": 0.5, "momentum": 0.4, "flow": 0.3, "reversal": 0.3, "volume": 0.2},
        "quant": {"momentum": 1.6, "reversal": 1.2, "volume": 0.8, "trend": 0.8, "flow": 0.5, "volatility": 0.4, "risk": 0.3},
        "volatility": {"volatility": 2.0, "reversal": 1.0, "risk": 0.8, "momentum": 0.5, "trend": 0.4, "flow": 0.3, "volume": 0.2},
    }
    return table.get(tilt, {}).get(factor, 0.5)


def analyze_stock_with_persona(
    persona: Persona,
    df,
    provider_name: Optional[str] = None,
    *,
    code: Optional[str] = None,
    research: Optional[str] = None,
    research_cache: Optional[dict] = None,
    research_bucket: str = "default",
) -> SpecialistOpinion:
    """Run one persona against a daily OHLCV frame and produce an opinion.

    ``research`` (a resolved backend id) enables the LLM research crossover:
    the persona brief is the system prompt and the market snapshot the user
    prompt; the model's JSON opinion is blended 35/65 with the deterministic
    factor score.  Any research failure keeps the factor-only result.
    """
    factors = compute_factor_scores(df)

    weighted = 0.0
    weight_sum = 0.0
    for factor, value in factors.items():
        w = _tilt_weight(persona.tilt, factor)
        if factor in persona.focus_metrics:
            w += 1.0
        weighted += w * value
        weight_sum += w
    score = weighted / weight_sum if weight_sum else 0.0
    score = max(-1.0, min(1.0, score))

    # Confidence scales with how extreme the signal is and how much data anchored it.
    if df is None or df.empty:
        confidence = 0.0
    else:
        rows = len(df)
        data_anchor = min(1.0, rows / 60.0)
        confidence = min(1.0, 0.35 + 0.35 * abs(score) + 0.25 * data_anchor)

    if score >= 0.12:
        signal = SIGNAL_LONG
    elif score <= -0.12:
        signal = SIGNAL_SHORT
    else:
        signal = SIGNAL_FLAT

    rationale = _build_rationale(signal, factors, score, rows=len(df) if df is not None else 0)
    opinion = SpecialistOpinion(
        persona=persona,
        score=score,
        signal=signal,
        confidence=confidence,
        rationale=rationale,
        factor_scores=factors,
        target_direction="up" if signal == SIGNAL_LONG else ("down" if signal == SIGNAL_SHORT else None),
    )

    if research:
        from src.jexi import research as _research

        if research != _research.RESEARCH_OFF:
            note = _research.run_persona_research(
                code or str(getattr(df, "code", "") or ""),
                df,
                persona,
                backend=research,
                cache=research_cache,
                bucket=research_bucket,
            )
            if note is not None and note.ok:
                combined = max(-1.0, min(1.0, _SCORE_BLEND_FACTOR * score + _SCORE_BLEND_RESEARCH * note.tilt))
                note_payload = note.to_dict()
                opinion.research = note_payload
                if abs(note.tilt) >= 0.5:
                    opinion.score = combined
                    opinion.signal = (
                        SIGNAL_LONG if combined >= 0.12 else (SIGNAL_SHORT if combined <= -0.12 else SIGNAL_FLAT)
                    )
                    opinion.target_direction = (
                        "up" if opinion.signal == SIGNAL_LONG
                        else ("down" if opinion.signal == SIGNAL_SHORT else None)
                    )
                    opinion.rationale.insert(
                        0, f"research({note.backend}): {note.rationale or 'no rationale'} ({note.direction} {note.conviction:.0%})"
                    )
    return opinion


def _build_rationale(signal: str, factors: dict, score: float, rows: int) -> List[str]:
    parts = [f"{signal.upper()} decision (blended score {score:+.2f})"]
    if factors["momentum"] > 0.03:
        parts.append(f"momentum positive ({factors['momentum']:+.2%} 20d blend)")
    elif factors["momentum"] < -0.03:
        parts.append(f"momentum negative ({factors['momentum']:+.2%} 20d blend)")
    trend = factors["trend"]
    if trend > 0.02:
        parts.append("price above rising MA20 (uptrend)")
    elif trend < -0.02:
        parts.append("price below falling MA20 (downtrend)")
    if abs(factors["reversal"]) > 0.15:
        label = "oversold (RSI extreme)" if factors["reversal"] > 0 else "overbought (RSI extreme)"
        parts.append(label)
    if factors["volume"] > 0.4:
        parts.append("expanding volume participation")
    if factors["flow"] > 0.25:
        parts.append("up-day volume dominance")
    elif factors["flow"] < -0.25:
        parts.append("down-day volume dominance")
    if factors["volatility"] > 1.0:
        parts.append(f"elevated volatility ({factors['volatility']:.0%} ann.)")
    parts.append(f"anchored on {rows} daily bars")
    return parts
