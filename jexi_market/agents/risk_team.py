# -*- coding: utf-8 -*-
"""Risk management team — three reviewers and a portfolio-manager veto.

Second pattern pulled from TauricResearch/TradingAgents: after the trader
proposes a trade, a *risk team* reviews it from three temperaments
(aggressive, neutral, conservative) and a portfolio manager takes the
final call.

This is a REAL implementation, not a persona prompt: each reviewer scores
the actual proposal against the actual numbers — drawdown from the risk
state store, daily P&L, volatility (ATR%), exposure, position size — and
each concern is a plain-English string that lands in the decision's risk
list and the user's app feed.

Division of labour (important):
* this team is *advisory* — it scales the position down (0.5x-1.0x) and
  can veto (position_fraction -> 0),
* the hard :class:`~jexi_market.risk.gate.RiskGate` ALWAYS runs after it
  and remains the only authority that can enforce limits.  The team can
  never *loosen* anything the gate enforces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.contracts import (
    Decision,
    RiskEnvelope,
    SignalDirection,
)
from jexi_market.indicators import FactorSnapshot
from jexi_market.risk import PortfolioState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewerScore:
    reviewer: str          # "aggressive" | "neutral" | "conservative"
    approve: bool
    score: float           # 0..1 approval strength
    concerns: tuple = ()   # plain-English concerns

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "approve": self.approve,
            "score": round(self.score, 4),
            "concerns": list(self.concerns),
        }


@dataclass
class RiskTeamVerdict:
    reviewers: List[ReviewerScore] = field(default_factory=list)
    consensus_score: float = 0.0        # mean approval strength
    n_approve: int = 0
    veto: bool = False                  # PM overrule -> no trade
    position_scale: float = 1.0         # multiply Vic's fraction (<= 1.0)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewers": [r.to_dict() for r in self.reviewers],
            "consensus_score": round(self.consensus_score, 4),
            "n_approve": self.n_approve,
            "veto": self.veto,
            "position_scale": round(self.position_scale, 4),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# The team
# ---------------------------------------------------------------------------


class RiskTeam:
    """Three-temperament risk review of a concrete trade proposal."""

    def review(
        self,
        decision: Decision,
        portfolio: PortfolioState,
        factors: FactorSnapshot,
        envelope: RiskEnvelope,
        *,
        earnings_in_days: Optional[int] = None,
    ) -> RiskTeamVerdict:
        concerns_all: List[str] = []

        # Shared, real inputs
        dd = self._current_drawdown(portfolio)
        daily_loss_pct = self._daily_loss_pct(portfolio)
        atr_pct = (factors.atr_pct if factors.atr_pct else (
            (factors.atr_14 / factors.latest_close) if (factors.atr_14 and factors.latest_close) else 0.03
        ))
        conf = decision.confidence.score
        frac = decision.position_fraction

        aggressive = self._review_aggressive(decision, dd, daily_loss_pct, atr_pct, conf)
        neutral = self._review_neutral(decision, dd, daily_loss_pct, atr_pct, conf, envelope)
        conservative = self._review_conservative(
            decision, dd, daily_loss_pct, atr_pct, conf, envelope, portfolio, earnings_in_days
        )

        reviewers = [aggressive, neutral, conservative]
        n_approve = sum(1 for r in reviewers if r.approve)
        consensus = sum(r.score for r in reviewers) / 3.0

        for r in reviewers:
            concerns_all.extend(r.concerns)

        # PM rules:
        #  * neutral AND conservative both reject  -> veto (do not trade)
        #  * one rejection  -> scale 0.75
        #  * two rejections (aggressive+neutral, conservative approved) -> scale 0.5
        #  * all approve -> scale 1.0, but still trim when consensus is lukewarm
        veto = (not neutral.approve) and (not conservative.approve)
        n_reject = 3 - n_approve
        if veto:
            scale = 0.0
            notes = "Risk team veto: neutral and conservative reviewers both rejected this trade."
        elif n_reject == 0:
            scale = 1.0 if consensus >= 0.7 else 0.85
            notes = "Risk team approved unanimously."
        elif n_reject == 1:
            scale = 0.75
            notes = f"Risk team split ({n_approve}/3 approve) — position trimmed to 75%."
        else:
            scale = 0.5
            notes = f"Risk team skeptical ({n_approve}/3 approve) — position halved."

        return RiskTeamVerdict(
            reviewers=reviewers,
            consensus_score=consensus,
            n_approve=n_approve,
            veto=veto,
            position_scale=scale,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Reviewers
    # ------------------------------------------------------------------
    def _review_aggressive(
        self, d: Decision, dd: float, daily_loss_pct: float, atr_pct: float, conf: float
    ) -> ReviewerScore:
        """Green-light bias — only blocks on account damage or junk setups."""
        concerns: List[str] = []
        score = 0.75
        if d.direction == SignalDirection.FLAT:
            return ReviewerScore("aggressive", True, 0.5, ("No trade proposed.",))
        if dd <= -0.08:
            concerns.append(f"Account is {abs(dd):.0%} off its peak — aggressive reviewer still ok, but watch it.")
            score -= 0.2
        if daily_loss_pct <= -0.03:
            concerns.append("Today is already a red day over 3% — aggressive reviewer wants smaller size.")
            score -= 0.25
        if conf < 0.35:
            concerns.append("Consensus confidence is thin for an aggressive entry.")
            score -= 0.15
        approve = score >= 0.4
        return ReviewerScore("aggressive", approve, max(0.0, min(1.0, score)), tuple(concerns))

    def _review_neutral(
        self, d: Decision, dd: float, daily_loss_pct: float, atr_pct: float, conf: float,
        envelope: RiskEnvelope,
    ) -> ReviewerScore:
        """Approves when confidence is real and volatility is tradable."""
        concerns: List[str] = []
        if d.direction == SignalDirection.FLAT:
            return ReviewerScore("neutral", True, 0.5, ("No trade proposed.",))
        score = 0.6
        if conf < 0.45:
            concerns.append(f"Confidence {conf:.0%} is below the neutral reviewer's 45% bar.")
            score -= 0.3
        if atr_pct > 0.08:
            concerns.append(f"Daily swings of {atr_pct:.1%} are too hot — neutral reviewer wants calmer tape.")
            score -= 0.3
        if daily_loss_pct <= -envelope.daily_loss_limit:
            concerns.append("Daily loss limit already breached — neutral reviewer says stand down today.")
            score -= 0.5
        if dd <= -envelope.drawdown_halt_threshold:
            concerns.append(f"Portfolio drawdown {abs(dd):.0%} is at the halt threshold.")
            score -= 0.5
        approve = score >= 0.45
        return ReviewerScore("neutral", approve, max(0.0, min(1.0, score)), tuple(concerns))

    def _review_conservative(
        self, d: Decision, dd: float, daily_loss_pct: float, atr_pct: float, conf: float,
        envelope: RiskEnvelope, portfolio: PortfolioState, earnings_in_days: Optional[int],
    ) -> ReviewerScore:
        """Capital preservation first — small sizes, calm tape, no event risk."""
        concerns: List[str] = []
        if d.direction == SignalDirection.FLAT:
            return ReviewerScore("conservative", True, 0.5, ("No trade proposed.",))
        score = 0.5
        half_max = envelope.max_position_fraction * 0.5
        if d.position_fraction > half_max:
            concerns.append(
                f"Position is {d.position_fraction:.0%} of the book — conservative reviewer prefers under {half_max:.0%}."
            )
            score -= 0.2
        if atr_pct > 0.05:
            concerns.append(f"Volatility {atr_pct:.1%} per day is above the conservative comfort zone.")
            score -= 0.25
        if conf < 0.55:
            concerns.append(f"Confidence {conf:.0%} is too thin for the conservative book.")
            score -= 0.25
        if portfolio.open_positions >= 8:
            concerns.append(f"Already {portfolio.open_positions} open positions — diversification dilution.")
            score -= 0.15
        if earnings_in_days is not None and earnings_in_days <= 3:
            concerns.append(f"Earnings land in {earnings_in_days} day(s) — binary event risk.")
            score -= 0.4
        if daily_loss_pct < 0:
            concerns.append("Down on the day — conservative reviewer prefers to wait for tomorrow.")
            score -= 0.1
        approve = score >= 0.45
        return ReviewerScore("conservative", approve, max(0.0, min(1.0, score)), tuple(concerns))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _current_drawdown(portfolio: PortfolioState) -> float:
        peak = float(portfolio.peak_equity or 0.0)
        equity = float(portfolio.equity or 0.0)
        if peak <= 0 or equity <= 0:
            return 0.0
        return (equity - peak) / peak

    @staticmethod
    def _daily_loss_pct(portfolio: PortfolioState) -> float:
        day_start = float(getattr(portfolio, "day_start_equity", 0.0) or 0.0)
        if day_start <= 0:
            pnl = float(portfolio.daily_pnl or 0.0)
            equity = float(portfolio.equity or 0.0)
            if equity > 0:
                day_start = equity - pnl
            else:
                return 0.0
        if day_start <= 0:
            return 0.0
        return float(portfolio.daily_pnl or 0.0) / day_start
