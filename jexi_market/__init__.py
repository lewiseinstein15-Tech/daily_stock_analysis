# -*- coding: utf-8 -*-
"""JEXI Market — autonomous multi-agent market intelligence & trading system.

JEXI Market is the market-specialist branch of JEXI OS.  It owns its own
research, analysis, strategy, backtesting, risk and (paper) execution layers
and reports to the main JEXI OS through a clean event/contract boundary.

This package is built on top of the repository's existing infrastructure
(``src/jexi`` prototype, ``data_provider`` fetchers, ``src/jexi/notify``)
and is intentionally compatible with it: the deterministic specialist engine,
the persona registry and the ntfy notifier remain the source of truth for
those concerns; JEXI Market adds the orchestration spine, the decision
pipeline, the risk gate, the Alpaca paper-trading client, the strategy
framework, the backtesting engine, the performance memory and the
structured agent-to-agent communication layer required by the JEXI Market
specification.

All trading in this package is paper-only by default.  Real trading is
gated behind an explicit ``JEXI_LIVE_TRADING_ENABLED=1`` environment flag
*and* a 30-day paper-validation precondition enforced by
:mod:`jexi_market.risk.gate`.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Public API — kept narrow on purpose.  Import heavy submodules lazily.
from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Decision,
    Evidence,
    EvidenceLink,
    MarketRegime,
    Recommendation,
    RiskEnvelope,
    RiskViolation,
    Severity,
    SignalDirection,
    Task,
    TaskPriority,
    TaskStatus,
    ToolCall,
    ToolResult,
)
from jexi_market.orchestrator import MarketBoss
from jexi_market.pipeline import DecisionPipeline

__all__ = [
    "AgentKind",
    "Confidence",
    "Decision",
    "DecisionPipeline",
    "Evidence",
    "EvidenceLink",
    "MarketBoss",
    "MarketRegime",
    "Recommendation",
    "RiskEnvelope",
    "RiskViolation",
    "Severity",
    "SignalDirection",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "ToolCall",
    "ToolResult",
    "__version__",
]
