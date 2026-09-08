# -*- coding: utf-8 -*-
"""Risk gate — the hard enforcement layer.

The risk gate is the *only* component in JEXI Market that can block a
decision from becoming a paper order.  It enforces the
:class:`RiskEnvelope` policy independently of what any agent proposed.

Critical design rule (spec section 13): "An AI agent must not be able
to simply instruct another component to bypass them."  The gate has
no override flag.  The only way to change its behaviour is to change
the :class:`RiskEnvelope` policy itself (via env vars), and that's
intentional — it forces the human operator to consciously raise the
limits, not an agent.

The gate records every rejection as a :class:`RiskViolation` for the
post-trade audit trail.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from jexi_market.contracts import (
    Decision,
    RiskEnvelope,
    RiskViolation,
    Severity,
    SignalDirection,
)

logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    """Snapshot of the paper portfolio at gate time."""

    equity: float = 100_000.0
    cash: float = 100_000.0
    positions_value: float = 0.0
    open_positions: int = 0
    sector_exposure: dict = field(default_factory=dict)   # sector -> fraction
    correlated_exposure: float = 0.0
    daily_pnl: float = 0.0
    peak_equity: float = 100_000.0
    paper_trading_days: int = 0
    live_trading_active: bool = False

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def daily_loss(self) -> float:
        if self.equity <= 0:
            return 1.0
        return max(0.0, -self.daily_pnl / self.equity)

    def to_dict(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "positions_value": round(self.positions_value, 2),
            "open_positions": self.open_positions,
            "drawdown": round(self.drawdown, 4),
            "daily_loss": round(self.daily_loss, 4),
            "paper_trading_days": self.paper_trading_days,
            "peak_equity": round(self.peak_equity, 2),
        }


@dataclass
class GateResult:
    """Result of a gate check."""

    approved: bool
    violations: List[RiskViolation] = field(default_factory=list)
    scaled_position_fraction: Optional[float] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "violations": [v.to_dict() for v in self.violations],
            "scaled_position_fraction": self.scaled_position_fraction,
            "reason": self.reason,
        }


class RiskGate:
    """The execution-layer risk gate.

    Construct once with a :class:`RiskEnvelope` and call :meth:`check`
    for every decision before it becomes a paper order.
    """

    def __init__(self, envelope: Optional[RiskEnvelope] = None):
        self.envelope = envelope or RiskEnvelope()
        self._halted = False
        self._halt_reason = ""
        self._halted_at: Optional[float] = None

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def halt(self, reason: str) -> None:
        """Enter protective state — only a human can clear this."""
        self._halted = True
        self._halt_reason = reason
        self._halted_at = time.time()
        logger.critical("RISK HALT: %s", reason)

    def clear_halt(self) -> None:
        """Manual clear — only call after human review."""
        self._halted = False
        self._halt_reason = ""
        self._halted_at = None

    def check(
        self,
        decision: Decision,
        portfolio: PortfolioState,
    ) -> GateResult:
        """Evaluate a decision against the risk envelope."""
        violations: List[RiskViolation] = []

        # 0. Halt check — if we're in protective state, reject everything.
        if self._halted:
            return GateResult(
                approved=False,
                reason=f"system halted: {self._halt_reason}",
                violations=[RiskViolation(
                    rule="system_halt",
                    severity=Severity.CRITICAL,
                    detail=f"halted at {self._halted_at}: {self._halt_reason}",
                )],
            )

        # 1. Direction-less decision — nothing to gate, approve trivially.
        if decision.direction == SignalDirection.FLAT:
            return GateResult(approved=True, reason="FLAT — no order needed")

        # 2. Live-trading precondition: 30 days of paper validation.
        if not self.envelope.live_trading_enabled:
            # Paper mode — no further live checks needed.
            pass
        else:
            if portfolio.paper_trading_days < self.envelope.min_30d_paper_validation:
                violations.append(RiskViolation(
                    rule="paper_validation_required",
                    severity=Severity.CRITICAL,
                    detail=(
                        f"live trading enabled but only {portfolio.paper_trading_days} "
                        f"paper days (< {self.envelope.min_30d_paper_validation})"
                    ),
                    proposed_value=float(portfolio.paper_trading_days),
                    limit=float(self.envelope.min_30d_paper_validation),
                ))

        # 3. Risk per trade
        if decision.risk_per_trade > self.envelope.max_risk_per_trade:
            violations.append(RiskViolation(
                rule="max_risk_per_trade",
                severity=Severity.ERROR,
                detail=(
                    f"decision risk {decision.risk_per_trade:.2%} exceeds limit "
                    f"{self.envelope.max_risk_per_trade:.2%}"
                ),
                proposed_value=decision.risk_per_trade,
                limit=self.envelope.max_risk_per_trade,
            ))

        # 4. Position fraction
        if decision.position_fraction > self.envelope.max_position_fraction:
            violations.append(RiskViolation(
                rule="max_position_fraction",
                severity=Severity.ERROR,
                detail=(
                    f"position fraction {decision.position_fraction:.2%} exceeds limit "
                    f"{self.envelope.max_position_fraction:.2%}"
                ),
                proposed_value=decision.position_fraction,
                limit=self.envelope.max_position_fraction,
            ))

        # 5. Portfolio exposure (after this trade)
        new_exposure = portfolio.positions_value / portfolio.equity + decision.position_fraction
        if new_exposure > self.envelope.max_portfolio_exposure:
            violations.append(RiskViolation(
                rule="max_portfolio_exposure",
                severity=Severity.ERROR,
                detail=(
                    f"projected exposure {new_exposure:.2%} exceeds limit "
                    f"{self.envelope.max_portfolio_exposure:.2%}"
                ),
                proposed_value=new_exposure,
                limit=self.envelope.max_portfolio_exposure,
            ))

        # 6. Daily loss limit
        if portfolio.daily_loss >= self.envelope.daily_loss_limit:
            violations.append(RiskViolation(
                rule="daily_loss_limit",
                severity=Severity.CRITICAL,
                detail=(
                    f"daily loss {portfolio.daily_loss:.2%} >= limit "
                    f"{self.envelope.daily_loss_limit:.2%}"
                ),
                proposed_value=portfolio.daily_loss,
                limit=self.envelope.daily_loss_limit,
            ))
            self.halt("daily loss limit breached")

        # 7. Drawdown halt
        if portfolio.drawdown >= self.envelope.drawdown_halt_threshold:
            violations.append(RiskViolation(
                rule="drawdown_halt_threshold",
                severity=Severity.CRITICAL,
                detail=(
                    f"drawdown {portfolio.drawdown:.2%} >= halt threshold "
                    f"{self.envelope.drawdown_halt_threshold:.2%}"
                ),
                proposed_value=portfolio.drawdown,
                limit=self.envelope.drawdown_halt_threshold,
            ))
            self.halt("drawdown halt threshold breached")

        # 8. Sector concentration (simplified — uses decision.symbol as the
        # sector key when no real sector classification is supplied)
        sector = decision.symbol  # placeholder; real impl maps symbol -> sector
        new_sector = portfolio.sector_exposure.get(sector, 0.0) + decision.position_fraction
        if new_sector > self.envelope.max_sector_concentration:
            violations.append(RiskViolation(
                rule="max_sector_concentration",
                severity=Severity.WARNING,
                detail=(
                    f"sector '{sector}' exposure {new_sector:.2%} exceeds limit "
                    f"{self.envelope.max_sector_concentration:.2%}"
                ),
                proposed_value=new_sector,
                limit=self.envelope.max_sector_concentration,
            ))

        # --- Decision: any CRITICAL or ERROR violation -> reject.
        blocking = [v for v in violations if v.severity in (Severity.CRITICAL, Severity.ERROR)]
        if blocking:
            return GateResult(
                approved=False,
                violations=violations,
                reason=f"{len(blocking)} blocking violation(s)",
            )

        # --- Warnings only: approve but scale position down if needed.
        scaled = decision.position_fraction
        if decision.position_fraction > self.envelope.max_position_fraction:
            scaled = self.envelope.max_position_fraction

        # If we have a WARNING (e.g., sector concentration), log but approve.
        return GateResult(
            approved=True,
            violations=violations,
            scaled_position_fraction=scaled,
            reason="approved" + (f" with {len(violations)} warning(s)" if violations else ""),
        )
