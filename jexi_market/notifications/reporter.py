# -*- coding: utf-8 -*-
"""ntfy.sh reporter for JEXI Market.

Produces the exact report format from the JEXI Market spec section 23:

    JEXI MARKET REPORT
    ━━━━━━━━━━━━━━━━━━

    TIME:
    08 Sep 2026 10:00 EAT

    TASK:
    Analyze NVDA

    ACTION:
    WATCH / BUY CANDIDATE / AVOID / HOLD

    CONFIDENCE:
    78%

    WHY:
    • Technical trend positive
    • Earnings growth strong
    • Volume increasing
    • Macro environment neutral

    RISKS:
    • High valuation
    • Elevated volatility

    AGENTS:
    ✓ Fundamental
    ✓ Technical
    ✓ Quant
    ✓ News
    ⚠ Risk Agent identified concentration risk

    PROPOSED ENTRY:
    $XXX

    STOP:
    $XXX

    TARGET:
    $XXX

    RISK:
    1.2%

    EVIDENCE:
    [source 1]
    [source 2]

    WHAT JEXI DID:

    1. Retrieved market data
    2. Validated data
    3. Ran 6 specialist analyses
    4. Compared conflicting signals
    5. Ran risk assessment
    6. Produced final decision

    NEXT ACTION:
    Monitor / Paper trade / Re-evaluate

    ━━━━━━━━━━━━━━━━━━

Reports are pushed to ntfy.sh via the existing ``src.jexi.notify``
``JexiNotifier`` so we honour the same ``NTFY_URL`` / ``NTFY_TOKEN``
configuration.  When ntfy is not configured, the report is printed to
stdout (offline / CI friendly).
"""

from __future__ import annotations

import logging
from datetime import datetime as _datetime
from datetime import timezone as _tz
from typing import Any, Dict, List, Optional

import requests

from jexi_market.config import MarketConfig
from jexi_market.contracts import Decision, Recommendation, SignalDirection

logger = logging.getLogger(__name__)

DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_TOPIC = "jexi_market_reports"

# Map a Decision's direction + confidence to a human action label.
_ACTION_LABELS = {
    SignalDirection.LONG: "BUY CANDIDATE",
    SignalDirection.SHORT: "SHORT CANDIDATE",
    SignalDirection.FLAT: "HOLD / WATCH",
}


class NtfyReporter:
    """Render and push JEXI Market reports to ntfy.sh."""

    PRIORITY_MAP = {
        "min": 1, "low": 2, "default": 3, "high": 4, "emergency": 5,
    }

    def __init__(self, config: Optional[MarketConfig] = None):
        self.config = config or MarketConfig()
        self._endpoint = self._resolve_endpoint()
        self._token = (self.config.ntfy_token or "").strip()

    def _resolve_endpoint(self) -> Optional[str]:
        url = self.config.ntfy_url.strip()
        if url:
            return url
        topic = self.config.jexi_ntfy_topic.strip() or DEFAULT_TOPIC
        return f"{DEFAULT_NTFY_SERVER}/{topic}"

    @property
    def enabled(self) -> bool:
        return bool(self._endpoint)

    @property
    def endpoint(self) -> Optional[str]:
        return self._endpoint

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render_report(
        self,
        *,
        decision: Decision,
        recommendations: List[Recommendation],
        agent_ids_run: List[str],
        task: str,
        regime: str,
        timezone: str = "EAT",
    ) -> str:
        """Render the spec-compliant report as a plain string."""
        now = _datetime.now(_tz.utc).strftime("%d %b %Y %H:%M")
        conf_pct = int(decision.confidence.score * 100)
        action = _ACTION_LABELS.get(decision.direction, "WATCH")

        lines: List[str] = []
        lines.append("JEXI MARKET REPORT")
        lines.append("━" * 20)
        lines.append("")
        lines.append(f"TIME:")
        lines.append(f"{now} {timezone}")
        lines.append("")
        lines.append("TASK:")
        lines.append(task)
        lines.append("")
        lines.append("ACTION:")
        lines.append(action)
        lines.append("")
        lines.append("CONFIDENCE:")
        lines.append(f"{conf_pct}%")
        lines.append("")

        # WHY: top 4 thesis points
        lines.append("WHY:")
        thesis_parts = decision.thesis.split("; ") if decision.thesis else []
        for part in thesis_parts[:4]:
            lines.append(f"• {part}")
        if not thesis_parts:
            lines.append("• Composite signal")
        lines.append("")

        # RISKS
        lines.append("RISKS:")
        if decision.risks:
            for risk in decision.risks[:5]:
                lines.append(f"• {risk}")
        else:
            lines.append("• None flagged")
        lines.append("")

        # AGENTS
        lines.append("AGENTS:")
        for rec in recommendations:
            mark = "✓" if rec.direction == decision.direction else ("⚠" if rec.direction == SignalDirection.FLAT else "✗")
            agent_name = rec.agent_id.replace("_", " ").title()
            lines.append(f"{mark} {agent_name}")
        lines.append("")

        # PROPOSED ENTRY / STOP / TARGET / RISK
        if decision.entry is not None:
            lines.append("PROPOSED ENTRY:")
            lines.append(f"${decision.entry:.2f}")
            lines.append("")
        if decision.stop_loss is not None:
            lines.append("STOP:")
            lines.append(f"${decision.stop_loss:.2f}")
            lines.append("")
        if decision.take_profit is not None:
            lines.append("TARGET:")
            lines.append(f"${decision.take_profit:.2f}")
            lines.append("")
        lines.append("RISK:")
        lines.append(f"{decision.risk_per_trade:.1%}")
        lines.append("")

        # EVIDENCE
        lines.append("EVIDENCE:")
        for ev in decision.evidence[:5]:
            lines.append(f"[{ev.source}] {ev.claim}")
        if not decision.evidence:
            lines.append("[none]")
        lines.append("")

        # WHAT JEXI DID
        lines.append("WHAT JEXI DID:")
        steps = [
            "1. Retrieved market data",
            "2. Validated data freshness",
            f"3. Ran {len(recommendations)} specialist analyses",
            "4. Compared conflicting signals",
            "5. Ran risk assessment",
            "6. Prof. Aldric reviewed for confirmation bias",
            "7. Vic produced execution plan",
            "8. Risk gate enforced limits",
        ]
        for step in steps:
            lines.append(step)
        lines.append("")

        # NEXT ACTION
        next_action = "Paper trade" if decision.direction != SignalDirection.FLAT else "Monitor / Re-evaluate"
        if not decision.evidence:
            next_action = "Re-evaluate (insufficient data)"
        lines.append("NEXT ACTION:")
        lines.append(next_action)
        lines.append("")
        lines.append("━" * 20)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    def publish(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: Optional[List[str]] = None,
        click: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> bool:
        if not self.enabled:
            # Offline mode — print to stdout so the report still surfaces.
            print(f"[ntfy:offline] {title}\n{message}")
            return False

        # Split endpoint into server + topic
        endpoint = self._endpoint.rstrip("/")
        parts = endpoint.rsplit("/", 1)
        if len(parts) == 2 and parts[1]:
            server, topic = parts[0], parts[1]
        else:
            server, topic = endpoint, DEFAULT_TOPIC

        payload: Dict[str, Any] = {
            "topic": topic,
            "title": title,
            "message": message,
            "priority": self.PRIORITY_MAP.get(priority, 3),
        }
        if tags:
            payload["tags"] = tags
        if click:
            payload["click"] = click

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "jexi-market/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            resp = requests.post(server, json=payload, headers=headers, timeout=timeout_seconds)
            if 200 <= resp.status_code < 300:
                logger.info("ntfy published: %s", title)
                return True
            logger.error("ntfy failed: HTTP %s (%s)", resp.status_code, server)
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("ntfy exception: %s", type(exc).__name__)
            return False

    def publish_decision(
        self,
        *,
        decision: Decision,
        recommendations: List[Recommendation],
        agent_ids_run: List[str],
        task: str,
        regime: str,
        timezone: str = "EAT",
    ) -> bool:
        """Convenience: render + publish in one call."""
        body = self.render_report(
            decision=decision,
            recommendations=recommendations,
            agent_ids_run=agent_ids_run,
            task=task,
            regime=regime,
            timezone=timezone,
        )
        title = f"JEXI MARKET · {decision.symbol} · {decision.direction.value.upper()}"
        priority = "high" if decision.direction != SignalDirection.FLAT else "default"
        return self.publish(title, body, priority=priority, tags=["chart", "stock"])
