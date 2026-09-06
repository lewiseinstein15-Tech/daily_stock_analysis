# -*- coding: utf-8 -*-
"""ntfy notification sender."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse, urlunparse

import requests

from src.config import Config
from src.formatters import strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)

# ntfy rejects oversized JSON messages with HTTP 413 (ntfy.sh caps the message
# body at 4096 bytes). Stay slightly below the cap and fall back to sending the
# full report as a file attachment when the content is longer.
NTFY_MESSAGE_BYTE_LIMIT = 4000


def _latin1_safe_header(value: str, limit: int = 200) -> str:
    """HTTP header values must be latin-1 encodable.

    Titles often contain emojis/CJK — those cannot travel in headers (the
    http.client layer raises UnicodeEncodeError), so replace whatever latin-1
    cannot represent. Message BODIES are unaffected (they stay UTF-8 JSON/raw).
    """
    return (value or "").encode("latin-1", "replace").decode("latin-1").strip()[:limit]


def resolve_ntfy_endpoint(ntfy_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split NTFY_URL into server root and topic from the final path segment."""
    raw_url = (ntfy_url or "").strip().rstrip("/")
    if not raw_url:
        return None, None

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, None

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        return None, None

    topic = unquote(path_segments[-1]).strip()
    if not topic:
        return None, None

    root_path = "/".join(path_segments[:-1])
    server_url = urlunparse(
        parsed._replace(
            path=f"/{root_path}" if root_path else "",
            params="",
            query="",
            fragment="",
        )
    ).rstrip("/")

    return server_url, topic


class NtfySender:
    """Send Markdown text notifications through the ntfy JSON publish API."""

    def __init__(self, config: Config):
        self._ntfy_url = getattr(config, "ntfy_url", None)
        self._ntfy_token = getattr(config, "ntfy_token", None)
        self._webhook_verify_ssl = getattr(config, "webhook_verify_ssl", True)
        limit = getattr(config, "ntfy_message_byte_limit", None)
        try:
            self._message_byte_limit = int(limit) if limit else NTFY_MESSAGE_BYTE_LIMIT
        except (TypeError, ValueError):
            self._message_byte_limit = NTFY_MESSAGE_BYTE_LIMIT

    def _is_ntfy_configured(self) -> bool:
        return bool(self._ntfy_url)

    def _resolve_ntfy_endpoint(self) -> Tuple[Optional[str], Optional[str]]:
        return resolve_ntfy_endpoint(self._ntfy_url)

    def send_to_ntfy(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Publish a notification to ntfy using a JSON body with UTF-8 text."""
        if not self._is_ntfy_configured():
            logger.warning("ntfy URL 未配置，跳过推送")
            return False

        server_url, topic = self._resolve_ntfy_endpoint()
        if not server_url or not topic:
            logger.error("NTFY_URL 必须是包含 topic path 的完整 endpoint，例如 https://ntfy.sh/my-topic")
            return False

        if title is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            title = f"📈 股票分析报告 - {date_str}"
        sanitized_content = strip_hidden_markdown_metadata(content).strip()

        effective_timeout = timeout_seconds or 10

        # Long reports exceed ntfy's message size cap and would fail with
        # HTTP 413 — deliver a truncated summary plus the full text as an
        # attachment instead.
        if len(sanitized_content.encode("utf-8")) > self._message_byte_limit:
            logger.warning(
                "ntfy 消息长度 %s 字节超过上限 %s，改用附件方式发送完整报告",
                len(sanitized_content.encode("utf-8")),
                self._message_byte_limit,
            )
            return self._send_with_attachment(
                server_url, topic, title, sanitized_content, effective_timeout
            )

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "daily_stock_analysis",
        }
        token = (self._ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "topic": topic,
            "title": title,
            "message": sanitized_content,
            "markdown": True,
        }

        try:
            response = requests.post(
                server_url,
                json=payload,
                headers=headers,
                timeout=effective_timeout,
                verify=self._webhook_verify_ssl,
            )
            if 200 <= response.status_code < 300:
                logger.info("ntfy 消息发送成功")
                return True

            if response.status_code == 413:
                logger.warning("ntfy 返回 HTTP 413（消息过大），改用附件方式重试")
                return self._send_with_attachment(
                    server_url, topic, title, sanitized_content, effective_timeout
                )

            logger.error("ntfy 请求失败: HTTP %s", response.status_code)
            logger.debug("ntfy 响应内容: %s", response.text)
            return False
        except requests.exceptions.Timeout:
            logger.error("发送 ntfy 消息失败: 请求超时")
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("发送 ntfy 消息失败: 网络请求异常")
            logger.debug("ntfy 请求异常类型: %s", type(exc).__name__)
            return False
        except Exception as exc:
            logger.error("发送 ntfy 消息失败: 未知异常")
            logger.debug("ntfy 未知异常类型: %s", type(exc).__name__)
            return False

    @staticmethod
    def _truncate_utf8(text: str, limit: int) -> str:
        """Truncate to at most `limit` UTF-8 bytes without breaking characters."""
        encoded = text.encode("utf-8")[:limit]
        return encoded.decode("utf-8", errors="ignore").rstrip()

    def _send_with_attachment(
        self,
        server_url: str,
        topic: str,
        title: str,
        content: str,
        timeout: float,
    ) -> bool:
        """Deliver an oversized report as: truncated summary + full-text file.

        The summary uses the regular JSON publish API; the file is published
        with ntfy's raw-body attachment format (POST /<topic> with a Filename
        header), which bypasses the JSON message size cap.
        """
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "daily_stock_analysis",
        }
        token = (self._ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        summary_limit = max(200, min(self._message_byte_limit, NTFY_MESSAGE_BYTE_LIMIT) - 250)
        summary_sent = False
        for _ in range(3):
            summary = self._truncate_utf8(content, summary_limit)
            if summary != content:
                summary += "\n\n[…内容过长已截断 — 完整报告见附件]"
            try:
                response = requests.post(
                    server_url,
                    json={"topic": topic, "title": title, "message": summary, "markdown": True},
                    headers=headers,
                    timeout=timeout,
                    verify=self._webhook_verify_ssl,
                )
                if 200 <= response.status_code < 300:
                    summary_sent = True
                    break
                if response.status_code != 413:
                    logger.error("ntfy 摘要消息发送失败: HTTP %s", response.status_code)
                    return False
                # 自建 server 可能有更严格的上限：减半重试
                summary_limit = max(200, summary_limit // 2)
                logger.warning("ntfy 摘要仍过大 (HTTP 413)，缩减至 %s 字节重试", summary_limit)
            except requests.exceptions.RequestException:
                logger.error("发送 ntfy 摘要消息失败: 网络请求异常")
                return False
        if not summary_sent:
            logger.error("ntfy 摘要消息发送失败: 多次重试后仍返回 HTTP 413")
            return False

        filename = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        attachment_headers = {
            "User-Agent": "daily_stock_analysis",
            "Title": _latin1_safe_header(f"{title} (full report / 完整报告)"),
            "Filename": filename,
            "Message": _latin1_safe_header("完整报告已作为附件发送。 (Full report attached.)"),
            "Content-Type": "text/markdown; charset=utf-8",
        }
        if token:
            attachment_headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.post(
                f"{server_url}/{topic}",
                data=content.encode("utf-8"),
                headers=attachment_headers,
                timeout=max(timeout, 30.0),
                verify=self._webhook_verify_ssl,
            )
            if 200 <= response.status_code < 300:
                logger.info("ntfy 完整报告已作为附件发送: %s", filename)
                return True
            logger.error("ntfy 附件发送失败: HTTP %s", response.status_code)
            return False
        except requests.exceptions.RequestException:
            logger.error("发送 ntfy 附件失败: 网络请求异常")
            return False
        except Exception:
            logger.error("发送 ntfy 附件失败: 未知异常")
            return False
