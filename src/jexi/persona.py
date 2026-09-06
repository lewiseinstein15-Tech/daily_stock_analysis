# -*- coding: utf-8 -*-
"""Persona registry loader for the J.E.X.I. agent system.

Personas are declared as typed data in ``personas.yaml`` and drive a single
shared specialist runtime (:mod:`src.jexi.specialist`).  Keeping personas as
data (not 50 near-identical agent classes) makes the registry cheap to extend,
audit and auto-tune — and matches the repository's "no parallel
implementations" rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

PERSONAS_FILE = Path(__file__).resolve().parent / "personas.yaml"

# Tool names must exist in the real ToolRegistry (src/agent/tools/*).
KNOWN_TOOLS = frozenset(
    {
        "get_realtime_quote",
        "get_daily_history",
        "get_chip_distribution",
        "get_analysis_context",
        "get_stock_info",
        "get_capital_flow",
        "get_portfolio_snapshot",
        "get_market_indices",
        "get_sector_rankings",
        "analyze_trend",
        "calculate_ma",
        "get_volume_analysis",
        "analyze_pattern",
        "search_stock_news",
        "search_comprehensive_intel",
        "get_stock_backtest_summary",
    }
)

# Scoring tilts the deterministic baseline understands.
KNOWN_TILTS = frozenset(
    {"momentum", "macro", "value", "sentiment", "flow", "risk", "quant", "volatility"}
)

_FOCUS_METRICS = frozenset(
    {"momentum", "reversal", "trend", "volume", "flow", "volatility", "risk"}
)


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    personality: str
    brief: str
    tilt: str
    focus_metrics: tuple
    base_weight: float = 1.0
    tools: tuple = ()
    kind: str = "specialist"

    @property
    def tool_allowlist(self) -> frozenset:
        return frozenset(self.tools)


@dataclass(frozen=True)
class LeadershipBundle:
    jexi: Persona
    thorne: Persona
    sterling: Persona
    advisors: tuple = ()

    @property
    def all(self) -> tuple:
        return (self.jexi, self.thorne, self.sterling) + self.advisors


def _build_persona(
    id_: str, raw: dict, kind: str, defaults: Optional[dict] = None
) -> Persona:
    data = dict(defaults or {})
    data.update(raw or {})
    tools = tuple(t for t in (data.get("tools") or []) if t in KNOWN_TOOLS)
    unknown = [t for t in (data.get("tools") or []) if t not in KNOWN_TOOLS]
    if unknown:
        raise ValueError(f"persona `{id_}` references unknown tools: {sorted(unknown)}")
    tilt = data.get("tilt", "momentum")
    if tilt not in KNOWN_TILTS:
        raise ValueError(f"persona `{id_}` has unknown tilt `{tilt}`")
    focus = tuple(f for f in (data.get("focus_metrics") or []) if f in _FOCUS_METRICS)
    return Persona(
        id=id_,
        name=str(data.get("name", id_)),
        role=str(data.get("role", "")),
        personality=str(data.get("personality", "")),
        brief=str(data.get("brief", "")),
        tilt=tilt,
        focus_metrics=focus,
        base_weight=float(data.get("base_weight", 1.0)),
        tools=tools,
        kind=kind,
    )


class PersonaRegistry:
    """Loads and validates ``personas.yaml`` once per process."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path or PERSONAS_FILE)
        self._data: Dict = {}
        self._leadership: Optional[LeadershipBundle] = None
        self._specialists: Dict[str, Persona] = {}
        self._by_name: Dict[str, str] = {}

    def load(self) -> "PersonaRegistry":
        with open(self._path, "r", encoding="utf-8") as fh:
            self._data = yaml.safe_load(fh) or {}

        leadership_raw = self._data.get("leadership") or {}
        self._leadership = LeadershipBundle(
            jexi=_build_persona("jexi", leadership_raw.get("jexi") or {}, "leader"),
            thorne=_build_persona(
                "thorne", leadership_raw.get("thorne") or {}, "leader"
            ),
            sterling=_build_persona(
                "sterling", leadership_raw.get("sterling") or {}, "leader"
            ),
        )

        defaults = self._data.get("defaults") or {}
        seen: Dict[str, str] = {"jexi", "thorne", "sterling"}
        for item in self._data.get("specialists") or []:
            id_ = str(item.get("id") or "").strip()
            if not id_:
                raise ValueError("personas.yaml: specialist entry missing `id`")
            if id_ in seen:
                raise ValueError(f"personas.yaml: duplicate persona id `{id_}`")
            seen.add(id_)
            persona = _build_persona(id_, item, "specialist", defaults)
            self._specialists[id_] = persona
            self._by_name[persona.name.lower()] = id_

        if not self._specialists:
            raise ValueError("personas.yaml: no specialists defined")
        return self

    @property
    def leadership(self) -> LeadershipBundle:
        return self._leadership

    @property
    def specialist_ids(self) -> tuple:
        return tuple(sorted(self._specialists))

    def specialists(self) -> tuple:
        return tuple(self._specialists.values())

    def get(self, id_: str) -> Persona:
        return self._specialists.get(id_.strip().lower())

    def select(self, ids: Optional[List[str]] = None) -> tuple:
        if ids:
            missing = [i for i in ids if i not in self._specialists]
            if missing:
                raise KeyError(f"unknown specialist ids: {sorted(missing)}")
            chosen = [self._specialists[i] for i in ids]
        else:
            chosen = list(self._specialists.values())
        return tuple(sorted(chosen, key=lambda p: (p.base_weight, p.id), reverse=True))

    def resolve_alias(self, value: str) -> Optional[Persona]:
        """Resolve a specialist by id or (case-insensitive) display name."""
        persona = self.get(value)
        if persona:
            return persona
        return self._specialists.get(self._by_name.get(value.strip().lower(), ""))


_registry: Optional[PersonaRegistry] = None


def get_persona_registry(path: Optional[Path] = None) -> PersonaRegistry:
    """Module-level cached registry (mirrors ToolRegistry cache pattern)."""
    global _registry
    if _registry is None:
        _registry = PersonaRegistry(path).load()
    return _registry
