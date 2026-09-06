# -*- coding: utf-8 -*-
"""Real research backend for Jexi specialists (LLM research, deterministic fallback).

Specialists normally run a deterministic factor engine.  When a research backend
is available the same persona crosses a real model: the persona's brief is the
system prompt, the ticking market snapshot is the user prompt, and the model
must reply with a tiny JSON opinion.  Any failure — no backend, timeout,
unparseable output — falls back to the factor engine, so a single research call
can never crash the analysis pipeline.

Backends
--------
- ``opencode_cli``  the built-in opencode CLI preset (no API key required)
- ``litellm``       the repository ``src/llm`` generation backend (needs keys)
- ``auto``          opencode_cli if installed, else litellm if configured, else off
- ``off``           deterministic factor engine only

The research call is cached per ``(bucket, code, persona_id)`` so a rolling
backtest refreshes research once per scenario window per persona per ticker,
never once per bar.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RESEARCH_AUTO = "auto"
RESEARCH_OPENCODE = "opencode_cli"
RESEARCH_LITELLM = "litellm"
RESEARCH_OFF = "off"
SUPPORTED_RESEARCH_BACKENDS = frozenset(
    {RESEARCH_AUTO, RESEARCH_OPENCODE, RESEARCH_LITELLM, RESEARCH_OFF}
)

RESEARCH_BACKEND_ENV = "JEXI_RESEARCH_BACKEND"
RESEARCH_TIMEOUT_ENV = "JEXI_RESEARCH_TIMEOUT_SECONDS"
DEFAULT_RESEARCH_TIMEOUT_SECONDS = 120.0

_SCORE_BLEND_FACTOR = 0.65
_SCORE_BLEND_RESEARCH = 0.35


@dataclass
class ResearchOpinion:
    """Structured opinion returned by the research model."""

    direction: str = "neutral"        # long | short | neutral
    conviction: float = 0.0           # 0..1
    rationale: str = ""
    risk: str = ""
    backend: str = ""
    model: str = ""
    raw: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (
            self.direction in ("long", "short", "neutral")
            and 0.0 <= self.conviction <= 1.0
        )

    @property
    def tilt(self) -> float:
        sign = {"long": 1.0, "neutral": 0.0, "short": -1.0}.get(self.direction, 0.0)
        return self.conviction * sign

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "model": self.model,
            "direction": self.direction,
            "conviction": round(self.conviction, 4),
            "rationale": self.rationale,
            "risk": self.risk,
        }


def _litellm_configured(config) -> bool:
    if config is None:
        return False
    return bool(
        getattr(config, "litellm_model", None)
        or getattr(config, "llm_model_list", None)
    )


def resolve_research_backend(config=None, explicit: Optional[str] = None) -> str:
    """Resolve the active research backend, degrading to ``off`` when unavailable."""
    raw = explicit
    if raw is None:
        if config is not None:
            raw = getattr(config, "jexi_research_backend", None)
        if raw in (None, ""):
            raw = os.getenv(RESEARCH_BACKEND_ENV, RESEARCH_OFF)
    backend = (raw or RESEARCH_OFF).strip().lower()
    if backend not in SUPPORTED_RESEARCH_BACKENDS:
        logger.warning("unknown research backend %r; using %r", raw, RESEARCH_OFF)
        return RESEARCH_OFF
    if backend == RESEARCH_AUTO:
        if shutil.which("opencode"):
            return RESEARCH_OPENCODE
        if _litellm_configured(config):
            return RESEARCH_LITELLM
        return RESEARCH_OFF
    if backend == RESEARCH_OPENCODE and not shutil.which("opencode"):
        logger.warning("opencode_cli requested but the opencode binary is not on PATH")
        return RESEARCH_OFF
    if backend == RESEARCH_LITELLM and not _litellm_configured(config):
        logger.info("litellm research requested but no model configured; falling back to deterministic")
        return RESEARCH_OFF
    return backend


def _research_timeout() -> float:
    try:
        return float(os.getenv(RESEARCH_TIMEOUT_ENV, DEFAULT_RESEARCH_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_RESEARCH_TIMEOUT_SECONDS


# -- market snapshot ---------------------------------------------------------
def build_snapshot_text(code: str, df) -> str:
    """Render a compact, real-number snapshot of the recent daily bars."""
    if df is None or df.empty or "close" not in df.columns:
        return f"{code}: no market data available."

    from src.jexi.specialist import compute_factor_scores

    factors = compute_factor_scores(df)
    closes = df["close"].dropna().tolist()
    latest = float(closes[-1]) if closes else 0.0

    def ret(n):
        if len(closes) <= n or not closes[-1 - n]:
            return 0.0
        return closes[-1] / closes[-1 - n] - 1.0

    feature_lines = [
        f"latest close {latest:.2f}",
        f"3d/10d/60d/120d returns {ret(3):+.2%} / {ret(10):+.2%} / {ret(60):+.2%} / {ret(120):+.2%}",
        f"annualised volatility {factors['volatility']:.0%}",
        f"score vector momentum={factors['momentum']:+.3f} trend={factors['trend']:+.3f} "
        f"reversal={factors['reversal']:+.3f} volume={factors['volume']:+.3f} "
        f"flow={factors['flow']:+.3f} risk={factors['risk']:+.3f}",
    ]

    recent = df.tail(5)
    feature_lines.append("last 5 bars (date close): " + ", ".join(
        f"{str(r['date'])[:10]} {float(r['close']):.2f}" for _, r in recent.iterrows()
    ))
    return f"{code} snapshot ({len(df)} daily bars):\n" + "\n".join(feature_lines)


def build_research_prompt(code: str, snapshot_text: str, persona) -> str:
    brief = (persona.name or persona.id) + " persona"
    if (getattr(persona, "personality", "") or "").strip():
        brief += f". {persona.personality.strip()}"
    if (getattr(persona, "tilt", "") or "").strip():
        brief += f" Tilt: {persona.tilt}."
    if getattr(persona, "focus_metrics", None):
        brief += f" Focus: {', '.join(persona.focus_metrics)}."
    toolkits = getattr(persona, "tools", None) or getattr(persona, "toolkit", None)
    if toolkits:
        brief += f" Toolkit: {', '.join(toolkits) if not isinstance(toolkits, str) else toolkits}."

    return (
        f"You are {brief}\n\n"
        f"Act as this specialist. Conduct a focused research read on the asset below for a paper-trading\n"
        f"decision window. Use quantitative and narrative reasoning. Do NOT invent data outside the snapshot.\n\n"
        f"{snapshot_text}\n\n"
        "Reply with ONLY a single JSON object and no markdown fences:\n"
        '{"direction":"long|short|neutral","conviction":0.0..1.0,'
        '"rationale":"one or two sentences","risk":"one sentence on the main downside risk"}\n'
    )


# -- backends ----------------------------------------------------------------
def _call_opencode(prompt_file: str, *, timeout: float) -> str:
    from src.llm.local_cli_backend import (
        _OPENCODE_STATIC_INSTRUCTION,
        LocalCliExecutionResult,
        _extract_opencode_json_events,
    )

    exe = shutil.which("opencode")
    if not exe:
        raise RuntimeError("opencode binary not found")
    proc = subprocess.run(
        [exe, "--pure", "run", "--format", "json", _OPENCODE_STATIC_INSTRUCTION, "--file", prompt_file],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = LocalCliExecutionResult(
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )
    return _extract_opencode_json_events(result)


def _call_litellm(
    system_prompt: str,
    user_prompt: str,
    config,
    *,
    timeout: float,
) -> str:
    from src.llm.backend_factory import create_generation_backend

    def _completion(prompt: str, generation_config: Dict[str, Any], **kwargs) -> tuple:
        import litellm

        messages = []
        system = kwargs.get("system_prompt")
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        model = generation_config.get("model") or getattr(config, "litellm_model", None)
        if not model:
            raise RuntimeError("no litellm model configured for research")
        response = litellm.completion(
            model=model,
            messages=messages,
            temperature=generation_config.get("temperature", 0.2),
            timeout=timeout,
        )
        text = (response.choices[0].message.content or "") if response.choices else ""
        return text, str(getattr(response, "model", model)), {}

    backend = create_generation_backend("litellm", config=config, litellm_completion_callable=_completion)
    result = backend.generate(
        user_prompt,
        {"temperature": 0.2, "model": getattr(config, "litellm_model", None)},
        system_prompt=system_prompt,
    )
    return result.text


def _parse_opinion(text: str, backend: str, model: str = "") -> Optional[ResearchOpinion]:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    direction = str(payload.get("direction", "neutral")).strip().lower()
    try:
        conviction = float(payload.get("conviction", 0.0))
    except (TypeError, ValueError):
        conviction = 0.0
    if direction not in ("long", "short", "neutral") or not (0.0 <= conviction <= 1.0):
        return None
    return ResearchOpinion(
        direction=direction,
        conviction=conviction,
        rationale=str(payload.get("rationale", "")).strip(),
        risk=str(payload.get("risk", "")).strip(),
        backend=backend,
        model=model,
        raw=text[start : end + 1],
    )


def run_persona_research(
    code: str,
    df,
    persona,
    *,
    backend: Optional[str] = None,
    cache: Optional[Dict[tuple, Optional[ResearchOpinion]]] = None,
    bucket: str = "default",
    timeout: float = DEFAULT_RESEARCH_TIMEOUT_SECONDS,
    config=None,
) -> Optional[ResearchOpinion]:
    """Run one persona against a real model; returns None on any failure.

    ``backend=None``/``off`` short-circuits to None (deterministic mode).  Cache
    key is ``(bucket, code, persona_id)`` so refresh cadence is caller-scoped.
    """
    if not backend or backend == RESEARCH_OFF:
        return None
    cache_key = (bucket, code, persona.id)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    snapshot = build_snapshot_text(code, df)
    output: Optional[ResearchOpinion] = None
    try:
        if backend == RESEARCH_OPENCODE:
            prompt = build_research_prompt(code, snapshot, persona)
            with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fh:
                fh.write(prompt)
                prompt_file = fh.name
            try:
                text = _call_opencode(prompt_file, timeout=timeout)
                output = _parse_opinion(text, backend)
            finally:
                try:
                    os.unlink(prompt_file)
                except OSError:
                    pass
        elif backend == RESEARCH_LITELLM:
            system_prompt, user_prompt = build_research_prompt(code, snapshot, persona).split("\n\n", 1)
            if config is None:
                from src.config import get_config

                config = get_config()
            text = _call_litellm(system_prompt, user_prompt, config, timeout=timeout)
            output = _parse_opinion(text, backend)

        if output is not None and not output.ok:
            output = None
    except Exception as exc:  # noqa: BLE001 - research is best-effort
        logger.debug("research call failed for %s/%s: %s", code, persona.id, exc)
        output = None

    if cache is not None:
        cache[cache_key] = output
    return output
