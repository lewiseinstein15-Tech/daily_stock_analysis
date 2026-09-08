# -*- coding: utf-8 -*-
"""Typed contracts for JEXI Market.

These dataclasses are the *lingua franca* of the multi-agent system.  Every
agent message, tool call, evidence claim, decision and risk check flows
through these types.  Keeping them frozen + explicitly typed means a typo
in one agent cannot silently become a malformed instruction to another.

Design rules enforced here:

* **No invented data.**  ``Evidence`` requires a ``source`` string and a
  ``timestamp``; an agent cannot claim "the price is $X" without saying
  where it got that number and when.
* **Confidence is structural, not vibes.**  ``Confidence`` is built from
  *agreement* + *data freshness* + *evidence count*, never from an LLM
  saying "I feel confident".
* **Risk is hard.**  ``RiskEnvelope`` holds the limits the execution layer
  enforces; agents can *propose* beyond the limits, but the gate rejects.
* **Decisions are auditable.**  Every ``Decision`` carries the full
  evidence trail, the agents that agreed/disagreed, the risks and the
  invalidation conditions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums & value types
# ---------------------------------------------------------------------------


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AgentKind(str, Enum):
    BOSS = "boss"
    ADVISOR = "advisor"           # Prof. Aldric
    EXECUTION = "execution"       # Vic
    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    QUANT = "quant"
    MACRO = "macro"
    NEWS = "news"
    RISK = "risk"
    STRATEGY = "strategy"
    BACKTEST = "backtest"
    DATA_VALIDATION = "data_validation"
    MARKET_MONITOR = "market_monitor"
    RESEARCH = "research"
    SECURITY = "security"


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Task & messaging
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """A unit of work the boss assigns to one or more agents.

    Tasks are immutable; the orchestrator creates child tasks for
    sub-investigations rather than mutating the parent.
    """

    objective: str
    kind: AgentKind
    symbol: Optional[str] = None
    parent_id: Optional[str] = None
    priority: TaskPriority = TaskPriority.NORMAL
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:10]}")
    created_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentMessage:
    """Structured inter-agent message.

    ``evidence`` is the list of concrete ``Evidence`` claims supporting the
    message; ``disagreements`` lists task_ids of messages this message
    explicitly contradicts (the boss uses this to trigger adjudication).
    """

    task_id: str
    from_agent: str
    to_agent: str
    body: Dict[str, Any]
    evidence: List["Evidence"] = field(default_factory=list)
    disagreements: List[str] = field(default_factory=list)
    confidence: Optional["Confidence"] = None
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceLink:
    """A single concrete source reference."""

    source: str                  # e.g. "yfinance", "alpaca", "sec_filing"
    reference: str               # e.g. URL, ticker, filing ID
    retrieved_at: float = field(default_factory=time.time)
    confidence: float = 1.0      # 0..1 — how much this source is trusted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "reference": self.reference,
            "retrieved_at": self.retrieved_at,
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class Evidence:
    """A single verifiable claim with provenance.

    The golden rule of JEXI Market: no agent may assert a fact in a
    recommendation without an ``Evidence`` object backing it.  Inventing
    data is the single most forbidden behaviour.
    """

    claim: str
    source: str
    links: Tuple[EvidenceLink, ...] = ()
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0       # 0..1
    contradicts: Optional[str] = None  # claim id this evidence contradicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "source": self.source,
            "links": [l.to_dict() for l in self.links],
            "timestamp": self.timestamp,
            "confidence": round(self.confidence, 4),
            "contradicts": self.contradicts,
        }


@dataclass(frozen=True)
class Confidence:
    """Structural confidence — never "the AI feels confident".

    Components:
      * ``agreement``      : fraction of independent agents that agree
      * ``data_freshness`` : 0..1, decayed by age of freshest evidence
      * ``evidence_count`` : raw count, normalised by sigmoid
      * ``disagreement_penalty`` : 0..1, raised when Risk/Aldric object
    """

    agreement: float = 0.0
    data_freshness: float = 0.0
    evidence_count: int = 0
    disagreement_penalty: float = 0.0

    @property
    def score(self) -> float:
        """Composite 0..1 confidence score."""
        import math

        evidence_factor = 1.0 - math.exp(-self.evidence_count / 3.0)
        base = (
            0.4 * max(0.0, min(1.0, self.agreement))
            + 0.3 * max(0.0, min(1.0, self.data_freshness))
            + 0.3 * evidence_factor
        )
        return max(0.0, min(1.0, base * (1.0 - 0.5 * self.disagreement_penalty)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agreement": round(self.agreement, 4),
            "data_freshness": round(self.data_freshness, 4),
            "evidence_count": self.evidence_count,
            "disagreement_penalty": round(self.disagreement_penalty, 4),
            "score": round(self.score, 4),
        }


# ---------------------------------------------------------------------------
# Recommendation & Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recommendation:
    """A specialist's recommendation for a symbol."""

    symbol: str
    direction: SignalDirection
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_per_trade: float = 0.02          # fraction of portfolio
    max_holding_days: int = 20
    thesis: str = ""
    invalidation: str = ""                # what would make this wrong
    evidence: Tuple[Evidence, ...] = ()
    agent_id: str = ""
    agent_kind: AgentKind = AgentKind.TECHNICAL
    confidence: Confidence = field(default_factory=Confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "target_price": self.target_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_per_trade": self.risk_per_trade,
            "max_holding_days": self.max_holding_days,
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "evidence": [e.to_dict() for e in self.evidence],
            "agent_id": self.agent_id,
            "agent_kind": self.agent_kind.value,
            "confidence": self.confidence.to_dict(),
        }


@dataclass(frozen=True)
class Decision:
    """The boss's synthesised decision for a symbol.

    This is what the risk gate evaluates and what (in paper mode) becomes
    an Alpaca order.  Every decision carries the full evidence trail and
    the list of agents that agreed / disagreed so post-trade analysis can
    attribute outcomes correctly.
    """

    symbol: str
    direction: SignalDirection
    confidence: Confidence
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_fraction: float = 0.0
    risk_per_trade: float = 0.02
    thesis: str = ""
    invalidation: str = ""
    evidence: Tuple[Evidence, ...] = ()
    supporting_agents: Tuple[str, ...] = ()
    opposing_agents: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()
    regime: MarketRegime = MarketRegime.UNKNOWN
    decided_at: float = field(default_factory=time.time)
    decision_id: str = field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:10]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "confidence": self.confidence.to_dict(),
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_fraction": round(self.position_fraction, 4),
            "risk_per_trade": self.risk_per_trade,
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "evidence": [e.to_dict() for e in self.evidence],
            "supporting_agents": list(self.supporting_agents),
            "opposing_agents": list(self.opposing_agents),
            "risks": list(self.risks),
            "regime": self.regime.value,
            "decided_at": self.decided_at,
        }


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskEnvelope:
    """The hard risk limits enforced at execution time.

    These are *policy*, not advice — the gate will reject any decision that
    breaches them, regardless of which agent proposed it.  Defaults match
    the JEXI Market spec: 2% per trade, 10% drawdown halt, etc.
    """

    max_risk_per_trade: float = 0.02       # 2% of portfolio
    max_position_fraction: float = 0.25    # 25% of equity in one name
    max_portfolio_exposure: float = 1.0    # 100% (no leverage by default)
    max_sector_concentration: float = 0.30  # 30% in one sector
    max_correlated_exposure: float = 0.40   # 40% in correlated cluster
    daily_loss_limit: float = 0.04          # 4% daily loss -> halt
    drawdown_halt_threshold: float = 0.10  # 10% drawdown -> halt
    min_30d_paper_validation: int = 30      # paper days before live
    live_trading_enabled: bool = False      # JEXI_LIVE_TRADING_ENABLED flag

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_position_fraction": self.max_position_fraction,
            "max_portfolio_exposure": self.max_portfolio_exposure,
            "max_sector_concentration": self.max_sector_concentration,
            "max_correlated_exposure": self.max_correlated_exposure,
            "daily_loss_limit": self.daily_loss_limit,
            "drawdown_halt_threshold": self.drawdown_halt_threshold,
            "min_30d_paper_validation": self.min_30d_paper_validation,
            "live_trading_enabled": self.live_trading_enabled,
        }


@dataclass(frozen=True)
class RiskViolation:
    """A concrete breach of the risk envelope."""

    rule: str
    severity: Severity
    detail: str
    proposed_value: Optional[float] = None
    limit: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "detail": self.detail,
            "proposed_value": self.proposed_value,
            "limit": self.limit,
        }


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """A structured tool invocation by an agent."""

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:10]}")
    agent_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a ``ToolCall``."""

    call_id: str
    ok: bool
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ok": self.ok,
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "data": self.data if isinstance(self.data, (str, int, float, bool, list, dict, type(None))) else str(self.data),
        }
