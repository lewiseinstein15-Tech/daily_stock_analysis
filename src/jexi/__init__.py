# -*- coding: utf-8 -*-
"""J.E.X.I. — Joint Executive & eXecution Intelligence.

A self-supervised multi-agent market-analysis layer on top of
``daily_stock_analysis``.  Reuses the repository's data provider, tool
registry, ntfy sender and backtest infrastructure; adds the persona registry,
the Jexi boss orchestrator, the deterministic specialist runtime, the
historical paper sim, the self-improvement loop and optional MCP connectors.
"""

from src.jexi.loop import JexiLearningLoop, LoopResult
from src.jexi.notify import JexiNotifier, resolve_jexi_ntfy_url
from src.jexi.orchestrator import JexiBossAgent, get_jexi
from src.jexi.persona import Persona, PersonaRegistry, get_persona_registry
from src.jexi.specialist import SpecialistOpinion, analyze_stock_with_persona

__all__ = [
    "JexiBossAgent",
    "JexiLearningLoop",
    "JexiNotifier",
    "LoopResult",
    "Persona",
    "PersonaRegistry",
    "SpecialistOpinion",
    "analyze_stock_with_persona",
    "get_jexi",
    "get_persona_registry",
    "resolve_jexi_ntfy_url",
]
