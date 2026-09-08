# -*- coding: utf-8 -*-
"""Research engine for JEXI Market.

JEXI Market owns its own research capability so it can investigate
market questions without depending on the main JEXI OS agents.  The
engine supports multiple backends:

* ``web_search`` — uses the repo's existing search service if a search
  API key is configured (SerpAPI / Tavily / Brave / Bocha / Anspire).
  Falls back to a no-op when no key is set (NEVER fabricates results).
* ``fundamentals`` — uses the repo's fundamental adapter if available.
* ``news`` — uses the repo's intelligence service if available.

Every research result is wrapped in a :class:`ResearchFinding` with
provenance, confidence and a contradiction flag — exactly the contract
the spec section 17 demands.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResearchFinding:
    """A single research result with provenance."""

    topic: str
    summary: str = ""
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.0
    retrieved_at: float = field(default_factory=time.time)
    backend: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    contradictions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "sources": self.sources,
            "confidence": round(self.confidence, 4),
            "retrieved_at": self.retrieved_at,
            "backend": self.backend,
            "contradictions": self.contradictions,
        }


class ResearchEngine:
    """Owns JEXI Market's research capability.

    The engine is intentionally pluggable: each backend is a callable
    that takes a query string and returns a :class:`ResearchFinding`.
    When no backend is available (no API key, no network), the engine
    returns ``None`` — it never fabricates findings.
    """

    def __init__(self, config: Optional[Any] = None):
        self.config = config
        self._backends: Dict[str, Any] = {}
        self._init_backends()

    def _init_backends(self) -> None:
        # 1. Repo search service (Anspire / SerpAPI / Tavily / Brave / Bocha)
        try:
            from src.search_service import SearchService  # type: ignore

            service = SearchService(self.config) if self.config else SearchService()
            if service and hasattr(service, "search"):
                self._backends["web_search"] = service.search
                logger.info("research backend 'web_search' initialised (repo SearchService)")
        except Exception as exc:
            logger.debug("web_search backend unavailable: %s", exc)

        # 2. Repo intelligence service (news + sentiment)
        try:
            from src.services.intelligence_service import IntelligenceService  # type: ignore

            self._backends["intelligence"] = IntelligenceService(self.config) if self.config else IntelligenceService()
            logger.info("research backend 'intelligence' initialised")
        except Exception as exc:
            logger.debug("intelligence backend unavailable: %s", exc)

    @property
    def available_backends(self) -> List[str]:
        return list(self._backends.keys())

    def research(self, topic: str, *, backend: Optional[str] = None) -> Optional[ResearchFinding]:
        """Run a single research query.

        Returns ``None`` if no backend is available — callers MUST treat
        that as "no opinion", never "neutral".
        """
        if not self._backends:
            return None
        chosen = backend or next(iter(self._backends))
        fn_or_obj = self._backends.get(chosen)
        if fn_or_obj is None:
            return None
        try:
            if callable(fn_or_obj):
                # web_search-style: search(query) -> list of results
                results = fn_or_obj(topic) or []
                if isinstance(results, list) and results:
                    first = results[0] if isinstance(results[0], dict) else {"title": str(results[0])}
                    return ResearchFinding(
                        topic=topic,
                        summary=str(first.get("snippet") or first.get("title") or ""),
                        sources=[str(first.get("url") or first.get("link") or "") for r in results[:3] for first in [r]],
                        confidence=0.6,
                        backend=chosen,
                        raw={"n_results": len(results), "first": first},
                    )
                return None
            # IntelligenceService-style object
            if hasattr(fn_or_obj, "get_intelligence"):
                intel = fn_or_obj.get_intelligence(topic)
                if intel:
                    return ResearchFinding(
                        topic=topic,
                        summary=str(getattr(intel, "summary", "") or ""),
                        sources=list(getattr(intel, "sources", []) or []),
                        confidence=float(getattr(intel, "confidence", 0.5)),
                        backend=chosen,
                        raw={"intel": intel.__dict__} if hasattr(intel, "__dict__") else {},
                    )
            return None
        except Exception as exc:
            logger.warning("research backend '%s' failed for '%s': %s", chosen, topic, exc)
            return None
