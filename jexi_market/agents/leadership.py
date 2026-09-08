# -*- coding: utf-8 -*-
"""Leadership agents: Prof. Aldric (strategic advisor) and Vic (execution).

These two agents are deliberately different from the specialists:

* **Prof. Aldric** does NOT produce a directional recommendation.  He
  reads the regime + the specialist consensus and writes a *review*:
  what could be wrong, what evidence contradicts the consensus, what
  would invalidate the thesis.  His job is to be skeptical, not to
  pick stocks.  He raises the disagreement_penalty when he finds
  structural holes in the consensus.

* **Vic** takes the synthesised :class:`Decision` and turns it into an
  executable :class:`ExecutionPlan`: position sizing, entry/exit rules,
  stop/take profit, max holding period.  Vic never overrides the risk
  envelope; if the math says a position would breach a limit, he
  scales it down or stands aside.

These map to "Prof. Thorne" and "Vic Sterling" in the existing
``src/jexi`` persona registry; we keep the names Aldric/Vic here for
clarity with the user-facing spec.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from jexi_market.agents.base import AgentContext, BaseAgent, register_agent
from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Decision,
    Evidence,
    MarketRegime,
    Recommendation,
    SignalDirection,
)
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import FactorSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prof. Aldric — strategic / skeptical reviewer
# ---------------------------------------------------------------------------


@dataclass
class Review:
    """Prof. Aldric's structured review of a specialist consensus."""

    symbol: str
    agreement: float                     # 0..1, fraction of agreeing agents
    contradiction_points: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    disagreement_penalty: float = 0.0    # 0..1, raised on structural holes
    regime: MarketRegime = MarketRegime.UNKNOWN
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "agreement": round(self.agreement, 4),
            "contradiction_points": self.contradiction_points,
            "invalidation_conditions": self.invalidation_conditions,
            "disagreement_penalty": round(self.disagreement_penalty, 4),
            "regime": self.regime.value,
            "notes": self.notes,
        }


@register_agent
class ProfAldricAgent(BaseAgent):
    """Skeptical senior researcher.

    Asks: "Why is this conclusion correct? What evidence contradicts
    it? What would make this thesis invalid? What is the probability
    that we are wrong?"
    """

    id = "aldric"
    name = "Prof. Aldric — Strategic Advisor"
    kind = AgentKind.ADVISOR

    def review(
        self,
        symbol: str,
        recommendations: List[Recommendation],
        regime: MarketRegime,
        factors: FactorSnapshot,
    ) -> Review:
        """Produce a Review from the specialist consensus."""
        if not recommendations:
            return Review(
                symbol=symbol,
                agreement=0.0,
                contradiction_points=["no specialist produced a recommendation"],
                disagreement_penalty=1.0,
                regime=regime,
                notes="insufficient analyst coverage",
            )

        # Count directional agreement (excluding the Risk/Data agents which
        # are explicitly veto-style).
        directional = [
            r for r in recommendations
            if r.agent_kind not in (AgentKind.RISK, AgentKind.DATA_VALIDATION)
            and r.direction != SignalDirection.FLAT
        ]
        if not directional:
            agreement = 0.0
            dominant = SignalDirection.FLAT
        else:
            longs = sum(1 for r in directional if r.direction == SignalDirection.LONG)
            shorts = sum(1 for r in directional if r.direction == SignalDirection.SHORT)
            agreement = max(longs, shorts) / len(directional)
            dominant = SignalDirection.LONG if longs > shorts else (SignalDirection.SHORT if shorts > longs else SignalDirection.FLAT)

        contradictions: List[str] = []
        invalidations: List[str] = []
        penalty = 0.0

        # 1. Volatility check
        if factors.annualised_vol > 0.6:
            contradictions.append(f"elevated volatility {factors.annualised_vol:.0%} questions directional conviction")
            penalty += 0.2

        # 2. Drawdown check
        if factors.drawdown > 0.15:
            contradictions.append(f"already in {factors.drawdown:.0%} drawdown from peak")
            penalty += 0.2

        # 3. Regime vs direction check
        if regime == MarketRegime.BEAR and dominant == SignalDirection.LONG:
            contradictions.append("bear regime but consensus is long — counter-trend")
            penalty += 0.25
        if regime == MarketRegime.VOLATILE:
            contradictions.append("volatile regime — directional bets less reliable")
            penalty += 0.15

        # 4. Risk agent veto
        risk_recs = [r for r in recommendations if r.agent_kind == AgentKind.RISK]
        if risk_recs and any(r.confidence.disagreement_penalty > 0.3 for r in risk_recs):
            contradictions.append("Risk Agent raised elevated disagreement penalty")
            penalty += 0.2

        # 5. Data validation penalty
        dv_recs = [r for r in recommendations if r.agent_kind == AgentKind.DATA_VALIDATION]
        if dv_recs and any(r.confidence.disagreement_penalty > 0.3 for r in dv_recs):
            contradictions.append("Data Validation Agent flagged quality concerns")
            penalty += 0.2

        # 6. Invalidation conditions from the specialists themselves
        for r in recommendations:
            if r.invalidation:
                invalidations.append(r.invalidation)

        penalty = min(1.0, penalty)

        return Review(
            symbol=symbol,
            agreement=agreement,
            contradiction_points=contradictions,
            invalidation_conditions=list(set(invalidations))[:5],
            disagreement_penalty=penalty,
            regime=regime,
            notes=f"{len(directional)} directional specialists, agreement {agreement:.0%}",
        )


# ---------------------------------------------------------------------------
# Vic — execution planner
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPlan:
    """Vic's execution plan for a :class:`Decision`.

    Position sizing uses the *risk-per-trade* method: position fraction =
    min(risk_per_trade / stop_distance, max_position_fraction).  This is
    the same math as the existing ``src/jexi/papersim.py`` but applied
    here on top of the typed Decision/Evidence contracts.
    """

    symbol: str
    direction: SignalDirection
    position_fraction: float = 0.0
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_holding_days: int = 15
    risk_per_trade: float = 0.02
    notes: List[str] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        return self.direction != SignalDirection.FLAT and self.position_fraction > 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "position_fraction": round(self.position_fraction, 4),
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "max_holding_days": self.max_holding_days,
            "risk_per_trade": self.risk_per_trade,
            "notes": self.notes,
            "actionable": self.actionable,
        }


@register_agent
class VicAgent(BaseAgent):
    """Execution & portfolio optimization specialist."""

    id = "vic"
    name = "Vic — Execution & Portfolio Optimization"
    kind = AgentKind.EXECUTION

    def plan(
        self,
        decision: Decision,
        *,
        max_position_fraction: float = 0.25,
        max_risk_per_trade: float = 0.02,
    ) -> ExecutionPlan:
        """Turn a Decision into an ExecutionPlan respecting risk limits."""
        plan = ExecutionPlan(
            symbol=decision.symbol,
            direction=decision.direction,
            entry=decision.entry,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            risk_per_trade=min(decision.risk_per_trade, max_risk_per_trade),
            max_holding_days=20,
        )

        if decision.direction == SignalDirection.FLAT:
            plan.notes.append("FLAT decision — stand aside")
            return plan

        if not decision.entry or not decision.stop_loss:
            plan.notes.append("missing entry or stop — cannot size position")
            return plan

        # Risk-based position sizing: fraction = risk / stop_distance
        stop_distance = abs(decision.entry - decision.stop_loss) / decision.entry
        if stop_distance <= 0:
            plan.notes.append("zero stop distance — cannot size position")
            return plan

        raw_fraction = plan.risk_per_trade / stop_distance
        plan.position_fraction = min(raw_fraction, max_position_fraction)

        plan.notes.append(
            f"risk-based sizing: {plan.position_fraction:.1%} of equity "
            f"({plan.risk_per_trade:.0%} risk / {stop_distance:.1%} stop)"
        )

        # Volatility override: if regime is volatile, halve position
        if decision.regime == MarketRegime.VOLATILE:
            plan.position_fraction *= 0.5
            plan.notes.append("volatility regime override: position halved")

        # Confidence override: scale by confidence score (0.5..1.0 multiplier)
        conf_mult = 0.5 + 0.5 * decision.confidence.score
        plan.position_fraction *= conf_mult
        plan.notes.append(f"confidence multiplier {conf_mult:.2f}")

        return plan


# ---------------------------------------------------------------------------
# Regime classifier (used by the boss before dispatching specialists)
# ---------------------------------------------------------------------------


class RegimeClassifier:
    """Deterministic market-regime classifier.

    Reuses the same math as ``src.jexi.orchestrator.RegimeClassifier``
    but returns a typed :class:`MarketRegime` enum and a score in [-1, 1].
    """

    @staticmethod
    def classify(closes: List[float]) -> Tuple[MarketRegime, float, str]:
        if not closes or len(closes) < 30:
            return MarketRegime.UNKNOWN, 0.0, "insufficient history"

        latest = closes[-1]
        window = min(120, len(closes))
        lookback = closes[-window:]
        ret = latest / lookback[0] - 1.0 if lookback[0] else 0.0

        # Annualised vol
        returns = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        mean = sum(returns) / len(returns) if returns else 0.0
        var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
        ann_vol = (var ** 0.5) * (252 ** 0.5) if var > 0 else 0.0

        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else sum(closes) / len(closes)
        above_ma = latest >= ma60

        if ann_vol >= 0.45:
            return MarketRegime.VOLATILE, 0.0, f"ann vol {ann_vol:.0%} >= 45%"
        if ret >= 0.08 and above_ma:
            return MarketRegime.BULL, min(1.0, ret / 0.3), f"{window}d return {ret:+.1%} above MA60"
        if ret <= -0.08 and not above_ma:
            return MarketRegime.BEAR, -min(1.0, abs(ret) / 0.3), f"{window}d return {ret:+.1%} below MA60"
        return MarketRegime.SIDEWAYS, 0.0, f"{window}d return {ret:+.1%} no dominant trend"
