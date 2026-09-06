# -*- coding: utf-8 -*-
"""ntfy.sh notification wrapper for J.E.X.I.

ntfy needs no Python package — it is the JSON publish HTTP API
(``POST /{topic}`` with ``title/message/tags/priority``).  This module adds
the ``tags``/``priority`` fields the Jexi spec requires on top of the
repository's existing ``NtfySender`` and honours the same ``NTFY_URL`` /
``NTFY_TOKEN`` config.  When no endpoint is configured the publisher prints
the report to stdout instead (so the pilot is runnable offline).
"""

from __future__ import annotations

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_JEXI_TOPIC = "jexi_reports"


def resolve_jexi_ntfy_url(config) -> Optional[str]:
    """Resolve the Jexi ntfy endpoint: JEXI_NTFY_URL > NTFY_URL > server+topic."""
    jexi_url = getattr(config, "jexi_ntfy_url", None) or ""
    ntfy_url = getattr(config, "ntfy_url", None) or ""
    if jexi_url:
        return jexi_url
    if ntfy_url:
        return ntfy_url
    if getattr(config, "jexi_ntfy_topic", None):
        server = getattr(config, "jexi_ntfy_server", None) or DEFAULT_NTFY_SERVER
        return f"{server.rstrip('/')}/{getattr(config, 'jexi_ntfy_topic')}"
    return None


def _split_endpoint(url: str):
    url = url.rstrip("/")
    parts = url.rsplit("/", 1)
    if len(parts) == 2 and parts[1]:
        return parts[0], parts[1]
    return url, ""


class JexiNotifier:
    """Publish Jexi reports/milestones to ntfy.sh with title/priority/tags."""

    priority_map = {"min": 1, "low": 2, "default": 3, "high": 4, "emergency": 5}

    def __init__(self, config=None, topic: Optional[str] = None):
        self._config = config
        resolved = resolve_jexi_ntfy_url(config) if config is not None else None
        if resolved:
            server, self._topic = _split_endpoint(resolved)
            self._server = server
        else:
            self._server = None
            self._topic = None
            logger.warning("ntfy 未配置：Jexi 通知将只写日志/标准输出")
        if topic:
            self._topic = topic
        self._token = self._resolve_token(config)

    def _resolve_token(self, config) -> str:
        if config is None:
            return ""
        return (getattr(config, "jexi_ntfy_token", None) or getattr(config, "ntfy_token", None) or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self._server and self._topic)

    @property
    def endpoint(self) -> Optional[str]:
        if self.enabled:
            return f"{self._server}/{self._topic}"
        return None

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
            logger.info("[Jexi][%s] %s\n%s", priority, title, message)
            return False

        payload = {
            "topic": self._topic,
            "title": title,
            "message": message,
            "priority": self.priority_map.get(priority, 3),
        }
        if tags:
            payload["tags"] = tags
        if click:
            payload["click"] = click

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "daily_stock_analysis-jexi",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = requests.post(
                self._server,
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
            if 200 <= response.status_code < 300:
                logger.info("ntfy 推送成功: %s", title)
                return True
            logger.error("ntfy 推送失败: HTTP %s (%s)", response.status_code, self._server)
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("ntfy 推送异常: %s", type(exc).__name__)
            return False

    def report(self, title: str, message: str, tags: Optional[List[str]] = None) -> bool:
        return self.publish(title, message, priority="default", tags=tags or ["chart", "stock"])

    def milestone(self, title: str, message: str, tags: Optional[List[str]] = None) -> bool:
        return self.publish(title, message, priority="high", tags=tags or ["tada", "chart"])

    def alert(self, title: str, message: str, tags: Optional[List[str]] = None) -> bool:
        return self.publish(title, message, priority="emergency", tags=tags or ["warning", "triangular_flag_on_post"])
