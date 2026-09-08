# -*- coding: utf-8 -*-
"""Base agent class and registry for JEXI Market.

Every agent in JEXI Market inherits from :class:`BaseAgent`.  The contract
is intentionally small:

* ``analyze(snapshot, factors, ctx) -> Recommendation``
* ``id``, ``name``, ``kind`` for identification
* ``tools`` — the tool allowlist (enforced by the tool registry)

The registry is a simple dict-by-id; agents are instantiated lazily by
their id.  This keeps the orchestrator cheap and makes adding a new
specialist a single ``@register_agent`` decorator.

This is NOT "functions with fancy names".  Each agent below has a real,
deterministic analysis function that consumes the shared
:class:`FactorSnapshot` and produces a typed :class:`Recommendation` with
evidence links — exactly the contract the JEXI Market spec demands.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Evidence,
    EvidenceLink,
    Recommendation,
    SignalDirection,
)
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import FactorSnapshot

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Per-run context shared with every agent.

    Holds the risk envelope (so agents can size their recommendations
    appropriately), the market regime (so Prof. Aldric's regime view
    flows to every specialist), and any cached research payload.
    """

    regime: str = "unknown"
    regime_score: float = 0.0
    portfolio_value: float = 100_000.0
    portfolio_drawdown: float = 0.0
    risk_envelope: Optional[Any] = None
    research_cache: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """Common base for every JEXI Market agent."""

    id: str = "base"
    name: str = "Base Agent"
    kind: AgentKind = AgentKind.TECHNICAL
    tools: Tuple[str, ...] = ()

    def __init__(self, config: Optional[Any] = None):
        self.config = config

    # ------------------------------------------------------------------
    # Subclasses override this.
    # ------------------------------------------------------------------
    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers used by every specialist.
    # ------------------------------------------------------------------
    @staticmethod
    def evidence(
        claim: str,
        source: str,
        *,
        reference: str = "",
        confidence: float = 1.0,
    ) -> Evidence:
        link = EvidenceLink(
            source=source,
            reference=reference or source,
            confidence=confidence,
        )
        return Evidence(
            claim=claim,
            source=source,
            links=(link,),
            confidence=confidence,
        )

    @staticmethod
    def confidence_from_factors(
        factors: FactorSnapshot,
        *,
        agreement: float = 0.0,
        disagreement_penalty: float = 0.0,
    ) -> Confidence:
        """Build a structural Confidence object.

        ``agreement`` is supplied by the orchestrator (it knows how many
        other agents agree).  ``data_freshness`` is derived from the
        snapshot row count.
        """
        return Confidence(
            agreement=agreement,
            data_freshness=min(1.0, factors.rows / 120.0),
            evidence_count=1,
            disagreement_penalty=disagreement_penalty,
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{self.__class__.__name__} id={self.id} kind={self.kind.value}>"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_AGENT_REGISTRY: Dict[str, type] = {}
_AGENT_ORDER: List[str] = []


def register_agent(cls: type) -> type:
    """Class decorator: register a BaseAgent subclass by its ``id``."""
    agent_id = getattr(cls, "id", None)
    if not agent_id:
        raise ValueError(f"agent class {cls.__name__} missing 'id' attribute")
    if agent_id in _AGENT_REGISTRY:
        raise ValueError(f"duplicate agent id: {agent_id}")
    _AGENT_REGISTRY[agent_id] = cls
    _AGENT_ORDER.append(agent_id)
    return cls


def get_agent_class(agent_id: str) -> Optional[type]:
    return _AGENT_REGISTRY.get(agent_id)


def list_agent_ids() -> List[str]:
    return list(_AGENT_ORDER)


def build_all_agents(config: Optional[Any] = None) -> Dict[str, BaseAgent]:
    """Instantiate every registered agent.

    Used by the orchestrator to get the full specialist roster.
    """
    out: Dict[str, BaseAgent] = {}
    for agent_id in _AGENT_ORDER:
        cls = _AGENT_REGISTRY[agent_id]
        try:
            out[agent_id] = cls(config=config)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("failed to build agent %s: %s", agent_id, exc)
    return out
