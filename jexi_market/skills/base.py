# -*- coding: utf-8 -*-
"""Skill base class and registry.

Contract:
* ``applies_to`` — cheap gate; a skill that does not apply must cost ~0.
* ``run`` — produces :class:`SkillOutput` (evidence + risk flags + an
  optional position-size scale).  Skills must never raise for expected
  data gaps; they return an empty output and let the pipeline continue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.contracts import Evidence
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import FactorSnapshot

logger = logging.getLogger(__name__)


@dataclass
class SkillOutput:
    evidence: List[Evidence] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    #: position-size suggestion multiplier in [0.25, 1.0]; None = no opinion
    size_scale: Optional[float] = None
    #: facts the debate/arbiter can quote, plain English
    notes: List[str] = field(default_factory=list)

    def merge(self, other: "SkillOutput") -> None:
        self.evidence.extend(other.evidence)
        self.risk_flags.extend(other.risk_flags)
        self.notes.extend(other.notes)
        if other.size_scale is not None:
            self.size_scale = other.size_scale if self.size_scale is None else min(self.size_scale, other.size_scale)


@dataclass
class SkillReport:
    evidence: List[Evidence] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    size_scale: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    ran: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_flags": list(self.risk_flags),
            "size_scale": self.size_scale,
            "notes": list(self.notes),
            "ran": list(self.ran),
            "skipped": list(self.skipped),
            "n_evidence": len(self.evidence),
        }


class Skill:
    """Base class for all skills."""

    id: str = "skill"
    name: str = "Skill"

    def applies_to(
        self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any
    ) -> bool:  # pragma: no cover - overridden
        return True

    def run(
        self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any
    ) -> SkillOutput:  # pragma: no cover - overridden
        return SkillOutput()

    # shared helper -----------------------------------------------------
    @staticmethod
    def _evidence(claim: str, source: str, confidence: float = 0.8) -> Evidence:
        from jexi_market.contracts import EvidenceLink

        return Evidence(
            claim=claim,
            source=source,
            links=(EvidenceLink(source=source, reference=source, confidence=confidence),),
            confidence=confidence,
        )


class SkillRegistry:
    """Runs every applicable skill and folds outputs into one report."""

    def __init__(self, skills: Optional[List[Skill]] = None):
        self.skills = skills or []

    def run_all(
        self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any
    ) -> SkillReport:
        report = SkillReport()
        for skill in self.skills:
            try:
                if not skill.applies_to(snapshot, factors, ctx):
                    report.skipped.append(skill.id)
                    continue
                out = skill.run(snapshot, factors, ctx)
                report.evidence.extend(out.evidence)
                report.risk_flags.extend(out.risk_flags)
                report.notes.extend(out.notes)
                if out.size_scale is not None:
                    report.size_scale = (
                        out.size_scale if report.size_scale is None
                        else min(report.size_scale, out.size_scale)
                    )
                report.ran.append(skill.id)
            except Exception as exc:  # a skill must never kill the pipeline
                logger.warning("skill %s failed: %s", skill.id, exc)
                report.skipped.append(skill.id)
        # clamp global scale
        if report.size_scale is not None:
            report.size_scale = max(0.25, min(1.0, report.size_scale))
        return report
