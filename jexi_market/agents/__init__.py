# -*- coding: utf-8 -*-
"""Agent package — exports every agent through one import.

Importing this package registers every specialist and leadership agent
with the registry.  Callers do::

    from jexi_market.agents import build_all_agents, list_agent_ids
"""

from jexi_market.agents.base import (
    AgentContext,
    BaseAgent,
    build_all_agents,
    get_agent_class,
    list_agent_ids,
    register_agent,
)
from jexi_market.agents.leadership import (
    ProfAldricAgent,
    RegimeClassifier,
    Review,
    VicAgent,
    ExecutionPlan,
)
from jexi_market.agents.specialists import (
    DataValidationAgent,
    FundamentalAgent,
    MacroAgent,
    MarketMonitorAgent,
    NewsAgent,
    QuantAgent,
    RiskAgent,
    TechnicalAgent,
)

__all__ = [
    "AgentContext",
    "BaseAgent",
    "DataValidationAgent",
    "ExecutionPlan",
    "FundamentalAgent",
    "MacroAgent",
    "MarketMonitorAgent",
    "NewsAgent",
    "ProfAldricAgent",
    "QuantAgent",
    "RegimeClassifier",
    "Review",
    "RiskAgent",
    "TechnicalAgent",
    "VicAgent",
    "build_all_agents",
    "get_agent_class",
    "list_agent_ids",
    "register_agent",
]
