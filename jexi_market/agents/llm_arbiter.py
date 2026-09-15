# -*- coding: utf-8 -*-
"""LLM arbiter — the user's AI key becomes a *judge*, not a trader.

Until now the AI keys saved in the Jexi app were plumbed into the bot but
never consumed.  This module closes that loop: when the consensus vote is
in and the debate has run, the arbiter shows the full evidence pack to the
user's chosen LLM (OpenAI, Gemini, Anthropic or DeepSeek) and asks for a
structured judgment.

Safety rails (these are the difference between an agent and a chatbot):

* The LLM sees ONLY real numbers — factor values, each agent's vote and
  confidence, the debate verdict.  It is instructed to judge the evidence,
  and it has no tool access and no data source, so it cannot invent
  prices or news.
* Its entire influence is a confidence delta clamped to ±0.15.  It can
  push a near-tie either way; it can never flip a strong consensus.
* Output must parse as JSON with the expected keys; anything malformed,
  slow (timeout) or unavailable (no key / ``JEXI_LLM_ARBITER=off``)
  degrades to "no opinion" and the deterministic pipeline proceeds
  untouched.
* The transport is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.contracts import (
    Recommendation,
    SignalDirection,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class ArbiterVerdict:
    ok: bool = False
    provider: str = ""
    model: str = ""
    verdict: str = "no_opinion"      # "agree" | "disagree" | "no_opinion"
    direction_hint: str = ""         # "long" | "short" | "flat" (advisory only)
    confidence_delta: float = 0.0    # clamped to [-0.15, +0.15]
    reason: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "model": self.model,
            "verdict": self.verdict,
            "direction_hint": self.direction_hint,
            "confidence_delta": round(self.confidence_delta, 4),
            "reason": self.reason,
            "error": self.error,
        }


MAX_DELTA = 0.15

_SYSTEM_PROMPT = (
    "You are the arbitration judge of a multi-agent trading system. "
    "You receive: computed technical factors, each analyst agent's vote with "
    "its confidence, and the outcome of a bull/bear debate. "
    "Judge ONLY the evidence provided. Do not invent prices, news or data. "
    "Respond with ONLY a JSON object, no prose, with exactly these keys: "
    '{"verdict": "agree"|"disagree", "direction_hint": "long"|"short"|"flat", '
    '"confidence_delta": <number between -0.15 and 0.15>, '
    '"reason": "<max 2 short sentences>"} '
    '"agree" means the evidence supports the proposed trade; a negative '
    "confidence_delta means you find the case weaker than the agents did."
)


# ---------------------------------------------------------------------------
# Arbiter
# ---------------------------------------------------------------------------


class LLMArbiter:
    """One-call evidence judge using the user's own AI key."""

    #: injectable for tests: callable(url, headers, body_bytes, timeout) -> (status, body)
    transport: Any = None

    def __init__(self, config: Optional[Any] = None, timeout: float = 20.0):
        self.config = config
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def enabled() -> bool:
        """True when a provider key exists and the feature is not off."""
        mode = os.environ.get("JEXI_LLM_ARBITER", "auto").strip().lower()
        if mode in ("off", "0", "false", "no"):
            return False
        return LLMArbiter._detect_provider()[0] != ""

    @staticmethod
    def _detect_provider() -> tuple:
        """(provider, endpoint, model, headers_builder) for the first key present."""
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            model = os.environ.get("JEXI_LLM_MODEL") or "gpt-4o-mini"
            return (
                "openai", "https://api.openai.com/v1/chat/completions", model,
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
        if key:
            model = os.environ.get("JEXI_LLM_MODEL") or "gemini-2.0-flash"
            return (
                "gemini",
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                model,
                {"x-goog-api-key": key, "Content-Type": "application/json"},
            )
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key:
            model = os.environ.get("JEXI_LLM_MODEL") or "claude-3-5-haiku-latest"
            return (
                "anthropic", "https://api.anthropic.com/v1/messages", model,
                {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            )
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if key:
            model = os.environ.get("JEXI_LLM_MODEL") or "deepseek-chat"
            return (
                "deepseek", "https://api.deepseek.com/chat/completions", model,
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        return ("", "", "", {})

    def arbitrate(
        self,
        *,
        symbol: str,
        factors_summary: Dict[str, Any],
        recommendations: List[Recommendation],
        debate: Any = None,
        proposed_direction: SignalDirection = SignalDirection.FLAT,
    ) -> ArbiterVerdict:
        if proposed_direction == SignalDirection.FLAT:
            return ArbiterVerdict(ok=True, verdict="no_opinion", reason="No trade proposed — arbiter not consulted.")

        provider, endpoint, model, headers = self._detect_provider()
        if not provider:
            return ArbiterVerdict(ok=False, error="no AI key configured")

        prompt = self._build_prompt(
            symbol=symbol,
            factors_summary=factors_summary,
            recommendations=recommendations,
            debate=debate,
            proposed_direction=proposed_direction,
        )

        try:
            body = self._request_body(provider, model, prompt)
            raw = self._post(endpoint, headers, body)
            parsed = self._parse(provider, raw)
            return self._validate(parsed, provider, model)
        except Exception as exc:  # never break the pipeline
            logger.info("arbiter unavailable: %s", exc)
            return ArbiterVerdict(ok=False, provider=provider, model=model, error=str(exc))

    # ------------------------------------------------------------------
    # Request building per provider
    # ------------------------------------------------------------------
    @staticmethod
    def _request_body(provider: str, model: str, prompt: str) -> bytes:
        if provider in ("openai", "deepseek"):
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 300,
            }
        elif provider == "gemini":
            payload = {
                "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 300},
            }
        elif provider == "anthropic":
            payload = {
                "model": model,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 300,
            }
        else:  # pragma: no cover
            raise ValueError(f"unknown provider {provider}")
        return json.dumps(payload).encode("utf-8")

    def _post(self, endpoint: str, headers: Dict[str, str], body: bytes) -> str:
        if self.transport is not None:
            status, text = self.transport(endpoint, headers, body, self.timeout)
            if status >= 400:
                raise RuntimeError(f"provider HTTP {status}")
            return text
        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"provider HTTP {resp.status}")
            return resp.read().decode("utf-8", errors="replace")

    @staticmethod
    def _parse(provider: str, raw: str) -> Dict[str, Any]:
        data = json.loads(raw)
        if provider == "gemini":
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        elif provider == "anthropic":
            text = data["content"][0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]
        return LLMArbiter._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Tolerant JSON extraction — models love to add prose fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object in arbiter response")
        return json.loads(text[start:end + 1])

    # ------------------------------------------------------------------
    # Validation — the rails
    # ------------------------------------------------------------------
    @staticmethod
    def _validate(parsed: Dict[str, Any], provider: str, model: str) -> ArbiterVerdict:
        verdict = str(parsed.get("verdict", "")).lower()
        if verdict not in ("agree", "disagree"):
            raise ValueError(f"invalid verdict {verdict!r}")
        hint = str(parsed.get("direction_hint", "flat")).lower()
        if hint not in ("long", "short", "flat"):
            hint = "flat"
        try:
            delta = float(parsed.get("confidence_delta", 0.0))
        except (TypeError, ValueError):
            delta = 0.0
        delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
        reason = str(parsed.get("reason", ""))[:300]
        return ArbiterVerdict(ok=True, provider=provider, model=model, verdict=verdict,
                              direction_hint=hint, confidence_delta=delta, reason=reason)

    # ------------------------------------------------------------------
    # Prompt — real numbers only
    # ------------------------------------------------------------------
    @staticmethod
    def _build_prompt(
        *,
        symbol: str,
        factors_summary: Dict[str, Any],
        recommendations: List[Recommendation],
        debate: Any,
        proposed_direction: SignalDirection,
    ) -> str:
        lines = [f"Symbol: {symbol}", f"Proposed trade: {proposed_direction.value.upper()}"]
        lines.append("Computed factors (real values): " + json.dumps(factors_summary, default=str))

        lines.append("Agent votes:")
        for r in recommendations:
            if r.direction == SignalDirection.FLAT:
                continue
            ev_claims = "; ".join(e.claim for e in r.evidence[:2]) or "n/a"
            lines.append(
                f"- {r.agent_id} ({r.agent_kind.value}): {r.direction.value} "
                f"confidence {r.confidence.score:.2f}; evidence: {ev_claims}"
            )

        if debate is not None:
            d = debate.to_dict() if hasattr(debate, "to_dict") else debate
            lines.append(
                "Bull/bear debate result: winner={winner} margin={margin}".format(**d)
            )
            for side in ("bull_points", "bear_points"):
                for p in d.get(side, [])[:2]:
                    lines.append(f"  [{side.replace('_points','')}] {p.get('claim')} "
                                 f"(strength {p.get('strength')})")
        lines.append("Judge this trade proposal now. JSON only.")
        return "\n".join(lines)
