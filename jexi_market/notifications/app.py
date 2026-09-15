# -*- coding: utf-8 -*-
"""Jexi-app reporter: pushes JEXI Market reports into the user's app feed.

Same public surface as :class:`~jexi_market.notifications.reporter.NtfyReporter`
(``publish`` / ``publish_decision`` / ``enabled`` / ``endpoint``) so it can be
swapped in transparently by :func:`make_reporter`.  Reports land in the
Notifications feed inside the Jexi app — plain English, no external app.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import requests

from jexi_market.app_account import app_configured, push_notification
from jexi_market.config import MarketConfig
from jexi_market.contracts import Decision, Recommendation, SignalDirection
from jexi_market.notifications.reporter import NtfyReporter

logger = logging.getLogger(__name__)


class AppReporter:
    """Publish JEXI Market reports to the user's Jexi account feed."""

    def __init__(self, config: Optional[MarketConfig] = None):
        self.config = config or MarketConfig()
        self._renderer = NtfyReporter(self.config)  # reused for report rendering only
        self._ok = app_configured(self.config)

    @property
    def enabled(self) -> bool:
        return self._ok

    @property
    def endpoint(self) -> Optional[str]:
        if not self._ok:
            return None
        return f"{(self.config.jexi_app_server or '').rstrip('/')}/api/agent/notify (Jexi app)"

    def publish(
        self,
        title: str,
        message: str,
        *,
        priority: str = "default",
        tags: Optional[List[str]] = None,
        click: Optional[str] = None,
        timeout_seconds: float = 12.0,
    ) -> bool:
        if not self._ok:
            print(f"[jexi-app:offline] {title}\n{message}")
            return False
        kind = "warn" if priority in ("high", "emergency") else "info"
        sent = push_notification(
            self.config,
            message,
            kind=kind,
            title=title,
            timeout_seconds=timeout_seconds,
        )
        if sent:
            logger.info("jexi app published: %s", title)
        return sent

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
        body = self._renderer.render_report(
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


def make_reporter(config: Optional[MarketConfig] = None):
    """Pick the right reporter: the Jexi app when wired, ntfy otherwise.

    The Jexi app is the default destination — ``JEXI_APP_SERVER`` +
    ``JEXI_AGENT_SECRET`` + ``JEXI_APP_EMAIL`` switch everything into the
    app feed and no external service is needed.
    """
    cfg = config or MarketConfig()
    if app_configured(cfg):
        return AppReporter(cfg)
    return NtfyReporter(cfg)
