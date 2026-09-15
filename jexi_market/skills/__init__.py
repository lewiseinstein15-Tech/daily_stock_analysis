# -*- coding: utf-8 -*-
"""JEXI Market skills — composable, evidence-producing analysis units.

A *skill* is a narrow, deterministic capability that any decision can use:
earnings awareness, volatility regime, liquidity, gap behaviour, portfolio
correlation.  Skills never decide a trade; they attach typed
:class:`~jexi_market.contracts.Evidence` and risk flags that the agents,
the risk team and the orchestrator consume.

This mirrors the "skills" layer popularised by the MCP/agent ecosystem
(e.g. yahoo-finance2's agent skill, FinanceMCP's data tools) but runs
fully offline against data the system already fetched — no external
server required.  For heavier external capabilities the MCP client
(:mod:`jexi_market.mcp`) remains available via ``JEXI_MCP_SERVERS``.
"""

from jexi_market.skills.base import Skill, SkillOutput, SkillReport, SkillRegistry
from jexi_market.skills.pack import build_default_skills

__all__ = [
    "Skill",
    "SkillOutput",
    "SkillReport",
    "SkillRegistry",
    "build_default_skills",
]
