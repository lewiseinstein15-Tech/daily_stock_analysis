# -*- coding: utf-8 -*-
"""Bull vs Bear research debate — the TradingAgents pattern, built native.

Pattern pulled from TauricResearch/TradingAgents (106k stars): after the
analyst team speaks, a *bull researcher* and a *bear researcher* each build
the strongest honest case for and against the trade, rebut each other in
structured rounds, and a research manager declares the winner.

This implementation is fully deterministic — the cases are built from the
actual agent recommendations, the computed factors and the research cache
(fundamentals + news).  No LLM is required; when an LLM arbiter is also
configured (see ``llm_arbiter.py``) it judges the *output* of this debate.

Rules enforced here (mirroring the JEXI golden rule):
* every point carries a strength 0..1 derived from real evidence
  confidence — no invented claims,
* a point that gets successfully rebutted loses 25% of its strength,
* the winner's margin, not the loudest voice, moves confidence,
* the adjustment applied to the decision is bounded (±0.10) so a
  one-sided debate can never create a trade the analysts did not support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.contracts import (
    AgentKind,
    Evidence,
    EvidenceLink,
    MarketRegime,
    Recommendation,
    SignalDirection,
)
from jexi_market.indicators import FactorSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DebatePoint:
    """One argument in the debate, with real provenance."""

    side: str            # "bull" | "bear"
    claim: str
    strength: float      # 0..1 — derived from evidence confidence
    source: str          # agent id / factor name / research key

    def to_dict(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "claim": self.claim,
            "strength": round(self.strength, 4),
            "source": self.source,
        }


@dataclass
class DebateVerdict:
    bull_points: List[DebatePoint] = field(default_factory=list)
    bear_points: List[DebatePoint] = field(default_factory=list)
    rebuttals: List[str] = field(default_factory=list)
    winner: str = "split"            # "bull" | "bear" | "split"
    margin: float = 0.0              # 0..1 — how one-sided the debate was
    bull_total: float = 0.0
    bear_total: float = 0.0
    confidence_adjustment: float = 0.0   # bounded [-0.10, +0.10]
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bull_points": [p.to_dict() for p in self.bull_points],
            "bear_points": [p.to_dict() for p in self.bear_points],
            "rebuttals": list(self.rebuttals),
            "winner": self.winner,
            "margin": round(self.margin, 4),
            "bull_total": round(self.bull_total, 4),
            "bear_total": round(self.bear_total, 4),
            "confidence_adjustment": round(self.confidence_adjustment, 4),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Counter-map used for rebuttals (deterministic, evidence-based)
# ---------------------------------------------------------------------------

# If a bull point carries one of these keys, the bear side can counter with
# the paired argument when it actually has that factor on its side.
_COUNTERS: Dict[str, str] = {
    "trend": "overbought_risk",
    "momentum": "overbought_risk",
    "regime": "regime_turn",
    "volume": "distribution_risk",
    "fundamentals": "valuation_risk",
    "news": "news_reversal",
}


# ---------------------------------------------------------------------------
# Debate stage
# ---------------------------------------------------------------------------


class DebateStage:
    """Runs the bull/bear debate for one symbol.  Zero LLM, zero network."""

    MAX_POINTS_PER_SIDE = 4
    REBUT_DISCOUNT = 0.25
    MAX_ADJUSTMENT = 0.10

    def run(
        self,
        *,
        symbol: str,
        recommendations: List[Recommendation],
        factors: FactorSnapshot,
        research_cache: Optional[Dict[str, Any]] = None,
        regime: MarketRegime = MarketRegime.UNKNOWN,
        proposed_direction: SignalDirection = SignalDirection.FLAT,
    ) -> DebateVerdict:
        research_cache = research_cache or {}
        bull = self._build_cases("bull", symbol, recommendations, factors, research_cache, regime)
        bear = self._build_cases("bear", symbol, recommendations, factors, research_cache, regime)

        # --- Round 1: openings (already built) -------------------------
        bull_total = sum(p.strength for p in bull)
        bear_total = sum(p.strength for p in bear)

        # --- Round 2: rebuttals ----------------------------------------
        rebuttals: List[str] = []
        bull_scored = [DebatePoint(**p.__dict__) for p in bull]
        bear_scored = [DebatePoint(**p.__dict__) for p in bear]

        bull_scored, b_reb = self._apply_rebuttals(bull_scored, bear, "bull")
        bear_scored, u_reb = self._apply_rebuttals(bear_scored, bull, "bear")
        rebuttals.extend(b_reb + u_reb)

        bull_total = sum(p.strength for p in bull_scored)
        bear_total = sum(p.strength for p in bear_scored)

        total = bull_total + bear_total
        if total <= 0:
            return DebateVerdict(
                bull_points=bull_scored,
                bear_points=bear_scored,
                rebuttals=rebuttals,
                winner="split",
                margin=0.0,
                bull_total=0.0,
                bear_total=0.0,
                confidence_adjustment=0.0,
                summary="Debate produced no evidence-backed points on either side.",
            )

        margin = abs(bull_total - bear_total) / total
        if margin < 0.15:
            winner = "split"
        else:
            winner = "bull" if bull_total > bear_total else "bear"

        adjustment = self._adjustment(winner, margin, proposed_direction)
        summary = self._summarise(symbol, winner, margin, bull_scored, bear_scored, proposed_direction)

        return DebateVerdict(
            bull_points=bull_scored,
            bear_points=bear_scored,
            rebuttals=rebuttals,
            winner=winner,
            margin=margin,
            bull_total=bull_total,
            bear_total=bear_total,
            confidence_adjustment=adjustment,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Case building
    # ------------------------------------------------------------------
    def _build_cases(
        self,
        side: str,
        symbol: str,
        recommendations: List[Recommendation],
        factors: FactorSnapshot,
        research_cache: Dict[str, Any],
        regime: MarketRegime,
    ) -> List[DebatePoint]:
        points: List[DebatePoint] = []

        want_dir = SignalDirection.LONG if side == "bull" else SignalDirection.SHORT

        # 1. Agent recommendations aligned with this side
        for rec in recommendations:
            if rec.agent_kind in (AgentKind.RISK, AgentKind.DATA_VALIDATION):
                continue
            if rec.direction == want_dir and rec.thesis:
                points.append(DebatePoint(
                    side=side,
                    claim=rec.thesis[:160],
                    strength=max(0.2, min(1.0, rec.confidence.score)),
                    source=rec.agent_id,
                ))

        # 2. Deterministic factor arguments
        points.extend(self._factor_points(side, factors, regime))

        # 3. Research cache arguments (fundamentals + news)
        points.extend(self._research_points(side, research_cache, symbol))

        # Dedupe by claim, keep the strongest, cap per side
        best: Dict[str, DebatePoint] = {}
        for p in points:
            key = p.claim
            if key not in best or p.strength > best[key].strength:
                best[key] = p
        ordered = sorted(best.values(), key=lambda p: p.strength, reverse=True)
        return ordered[: self.MAX_POINTS_PER_SIDE]

    def _factor_points(
        self, side: str, f: FactorSnapshot, regime: MarketRegime
    ) -> List[DebatePoint]:
        out: List[DebatePoint] = []
        src = "factors"

        if side == "bull":
            if f.sma_50 and f.latest_close and f.latest_close > f.sma_50:
                out.append(DebatePoint("bull", f"Price above the 50-day average — trend is up", min(1.0, 0.5 + abs(f.momentum_20d) * 4), "factors:sma_50"))
            if f.momentum_20d > 0.02:
                out.append(DebatePoint("bull", f"20-day momentum is positive ({f.momentum_20d:+.1%})", min(1.0, 0.4 + f.momentum_20d * 4), "factors:momentum_20d"))
            if f.macd_hist is not None and f.macd_hist > 0:
                out.append(DebatePoint("bull", "MACD histogram positive — momentum turning up", 0.5, "factors:macd_hist"))
            if f.volume_ratio_5_20 > 1.2:
                out.append(DebatePoint("bull", "Recent volume runs above the 20-day norm — accumulation", min(0.9, 0.4 + f.volume_ratio_5_20 / 5), "factors:volume_ratio"))
            if regime == MarketRegime.BULL:
                out.append(DebatePoint("bull", "Market regime classified bullish", 0.6, "factors:regime"))
            if f.rsi_14 is not None and 45 <= f.rsi_14 <= 62:
                out.append(DebatePoint("bull", "RSI in the healthy 45-62 zone — room to run before overbought", 0.55, "factors:rsi_14"))
        else:
            if f.rsi_14 is not None and f.rsi_14 > 70:
                out.append(DebatePoint("bear", f"RSI {f.rsi_14:.0f} — overbought, pullback risk", min(1.0, 0.5 + (f.rsi_14 - 70) / 30), "factors:rsi_14"))
            if f.sma_50 and f.latest_close and f.latest_close < f.sma_50:
                out.append(DebatePoint("bear", "Price below the 50-day average — trend is down", 0.6, "factors:sma_50"))
            if f.momentum_20d < -0.02:
                out.append(DebatePoint("bear", f"20-day momentum is negative ({f.momentum_20d:+.1%})", min(1.0, 0.4 + abs(f.momentum_20d) * 4), "factors:momentum_20d"))
            if f.macd_hist is not None and f.macd_hist < 0:
                out.append(DebatePoint("bear", "MACD histogram negative — momentum turning down", 0.5, "factors:macd_hist"))
            if f.annualised_vol > 0.6:
                out.append(DebatePoint("bear", f"Annualised volatility {f.annualised_vol:.0%} — elevated risk", min(0.9, 0.4 + f.annualised_vol / 2), "factors:vol"))
            if regime in (MarketRegime.BEAR, MarketRegime.VOLATILE):
                out.append(DebatePoint("bear", f"Market regime classified {regime.value}", 0.6, "factors:regime"))
            if f.drawdown < -0.10:
                out.append(DebatePoint("bear", f"Drawdown {f.drawdown:.0%} from peak — damaged trend", 0.55, "factors:drawdown"))
        return out

    def _research_points(
        self, side: str, cache: Dict[str, Any], symbol: str
    ) -> List[DebatePoint]:
        out: List[DebatePoint] = []
        fund = cache.get(f"fundamentals:{symbol}")
        if isinstance(fund, dict):
            growth = fund.get("revenue_growth")
            margin_ = fund.get("profit_margin")
            de = fund.get("debt_to_equity")
            pe = fund.get("pe_ratio")
            if side == "bull":
                if isinstance(growth, (int, float)) and growth > 0.10:
                    out.append(DebatePoint("bull", f"Revenue growing {growth:+.0%} year over year", min(1.0, 0.5 + growth), "fundamentals:revenue_growth"))
                if isinstance(margin_, (int, float)) and margin_ > 0.15:
                    out.append(DebatePoint("bull", f"Healthy profit margin ({margin_:.0%})", 0.6, "fundamentals:profit_margin"))
                if isinstance(pe, (int, float)) and 0 < pe < 25:
                    out.append(DebatePoint("bull", f"P/E of {pe:.1f} is not stretched", 0.5, "fundamentals:pe"))
            else:
                if isinstance(de, (int, float)) and de > 2.0:
                    out.append(DebatePoint("bear", f"Debt-to-equity {de:.1f} — heavy leverage", min(0.9, 0.5 + de / 10), "fundamentals:debt_to_equity"))
                if isinstance(pe, (int, float)) and pe > 60:
                    out.append(DebatePoint("bear", f"P/E of {pe:.0f} — rich valuation", 0.7, "fundamentals:pe"))
                if isinstance(growth, (int, float)) and growth < -0.05:
                    out.append(DebatePoint("bear", f"Revenue shrinking ({growth:+.0%})", 0.65, "fundamentals:revenue_growth"))

        news = cache.get(f"news:{symbol}")
        if isinstance(news, dict):
            score = news.get("sentiment_score")
            n = news.get("n_items") or 0
            if isinstance(score, (int, float)) and n >= 2:
                if side == "bull" and score > 0.15:
                    out.append(DebatePoint("bull", f"News sentiment positive ({score:+.2f} over {n} items)", min(0.9, 0.4 + abs(score)), "news:sentiment"))
                if side == "bear" and score < -0.15:
                    out.append(DebatePoint("bear", f"News sentiment negative ({score:+.2f} over {n} items)", min(0.9, 0.4 + abs(score)), "news:sentiment"))
        return out

    # ------------------------------------------------------------------
    # Rebuttals
    # ------------------------------------------------------------------
    def _apply_rebuttals(
        self,
        side_points: List[DebatePoint],
        opposing: List[DebatePoint],
        side: str,
    ) -> tuple:
        """Discount points that the opposition actually counters.

        A rebuttal lands only when the opposing case has a point of
        comparable or higher strength — weak counters do nothing.
        """
        reb: List[str] = []
        scored: List[DebatePoint] = []
        for p in side_points:
            strength = p.strength
            category = self._categorise(p)
            for opp in opposing:
                opp_cat = self._categorise(opp)
                if _COUNTERS.get(category) == opp_cat and opp.strength >= p.strength * 0.8:
                    strength *= (1.0 - self.REBUT_DISCOUNT)
                    verb = "countered" if side == "bull" else "answered"
                    reb.append(f"Bear {verb}: {p.claim} — {opp.claim}" if side == "bull"
                               else f"Bull answered: {p.claim} — {opp.claim}")
                    break
            scored.append(DebatePoint(side=p.side, claim=p.claim, strength=strength, source=p.source))
        return scored, reb

    @staticmethod
    def _categorise(point: DebatePoint) -> str:
        s = point.source.lower()
        claim = point.claim.lower()
        if "rsi" in s or "overbought" in claim:
            return "overbought_risk"
        if "regime" in s:
            return "regime" if point.side == "bull" else "regime_turn"
        if "volume" in s or "accumulation" in claim:
            return "volume"
        if "momentum" in s or "macd" in s:
            return "momentum"
        if "sma" in s or "trend" in claim:
            return "trend"
        if "fundamentals" in s or "p/e" in claim or "revenue" in claim or "debt" in claim:
            return "fundamentals" if point.side == "bull" else "valuation_risk"
        if "news" in s:
            return "news" if point.side == "bull" else "news_reversal"
        if "vol" in s or "drawdown" in s:
            return "regime_turn"
        return "other"

    # ------------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------------
    def _adjustment(
        self, winner: str, margin: float, proposed: SignalDirection
    ) -> float:
        """Bound the debate's influence on the final decision.

        The debate can *add* conviction when it agrees with the proposed
        direction and *subtract* when it contradicts it.  A split debate
        moves nothing.  Never more than ±0.10 — the analysts, not the
        debaters, own the trade.
        """
        if winner == "split" or proposed == SignalDirection.FLAT:
            return 0.0
        magnitude = round(min(self.MAX_ADJUSTMENT, 0.04 + margin * 0.06), 4)
        winner_is_long = winner == "bull"
        proposed_is_long = proposed == SignalDirection.LONG
        if winner_is_long == proposed_is_long:
            return magnitude
        return -magnitude

    def _summarise(
        self,
        symbol: str,
        winner: str,
        margin: float,
        bull: List[DebatePoint],
        bear: List[DebatePoint],
        proposed: SignalDirection,
    ) -> str:
        top_bull = bull[0].claim if bull else "no bull case"
        top_bear = bear[0].claim if bear else "no bear case"
        if winner == "split":
            return f"{symbol} debate: split. Bull: {top_bull}. Bear: {top_bear}."
        side_name = "Bulls" if winner == "bull" else "Bears"
        strength = "clearly" if margin >= 0.4 else ("narrowly" if margin < 0.25 else "")
        return (
            f"{symbol} debate: {side_name} won {strength} "
            f"(margin {margin:.0%}). Bull: {top_bull}. Bear: {top_bear}."
        )


# ---------------------------------------------------------------------------
# Evidence helper — debate output feeds the decision trail
# ---------------------------------------------------------------------------


def debate_evidence(verdict: DebateVerdict) -> tuple:
    """Convert the debate outcome into Evidence objects for the Decision."""
    evs = []
    for p in verdict.bull_points[:2]:
        evs.append(Evidence(
            claim=f"[bull] {p.claim}",
            source="debate",
            links=(EvidenceLink(source="debate", reference=p.source, confidence=p.strength),),
            confidence=p.strength,
        ))
    for p in verdict.bear_points[:2]:
        evs.append(Evidence(
            claim=f"[bear] {p.claim}",
            source="debate",
            links=(EvidenceLink(source="debate", reference=p.source, confidence=p.strength),),
            confidence=p.strength,
        ))
    return tuple(evs)
