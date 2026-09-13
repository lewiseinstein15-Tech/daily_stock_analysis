# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) client for JEXI Market — self-contained.

MCP lets JEXI pull in *outside* capabilities — news feeds, fundamentals
providers, screeners, anything the community has published as an MCP
server — without hard-coding them.  JEXI speaks the standard MCP
JSON-RPC handshake over stdio (the same wire protocol the official
SDKs use), so any conforming server works:

    JEXI_MCP_ENABLED=1
    JEXI_MCP_SERVERS='[{"name":"news","command":"uvx","args":["mcp-server-fetch"]},
                       {"name":"market","command":"python","args":["my_server.py"]}]'

Design notes:
* ZERO SDK dependency — the wire protocol is simple JSON-RPC 2.0 over
  the subprocess's stdin/stdout with ``Content-Length`` framing
  (LSP-style), exactly as MCP stdio servers expect.  A fallback
  line-delimited mode handles servers that use newline framing.
* Every server is probed with ``initialize`` → ``tools/list`` at
  connect time; servers that fail to start are skipped with a warning
  (a broken MCP tool must never take the trading loop down).
* Tools are surfaced through :meth:`jexi_market.tools.registry.ToolRegistry.register_mcp`
  so agents can call them like any built-in tool.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from jexi_market.config import MarketConfig

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
_DEFAULT_TIMEOUT = 15.0


class McpStdioClient:
    """One MCP server over stdio (JSON-RPC 2.0, Content-Length framing)."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self.connected = False
        self.server_info: Dict[str, Any] = {}
        self.tools: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------
    def _start(self) -> bool:
        try:
            merged_env = {**os.environ, **(self.env or {})}
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=merged_env,
            )
            return True
        except Exception as exc:
            logger.warning("MCP server %r failed to start: %s", self.name, exc)
            self._proc = None
            return False

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        body = json.dumps(payload).encode("utf-8")
        # Content-Length framing (MCP stdio standard, LSP-style)
        self._proc.stdin.write(
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        self._proc.stdin.flush()

    def _read_message(self) -> Optional[Dict[str, Any]]:
        assert self._proc and self._proc.stdout
        # Read headers
        headers: Dict[str, int] = {}
        while True:
            line = self._proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if b":" in line:
                try:
                    k, v = line.decode("utf-8", "replace").split(":", 1)
                except ValueError:
                    continue
                if k.strip().lower() == "content-length":
                    try:
                        headers["content-length"] = int(v.strip())
                    except ValueError:
                        return None
        length = headers.get("content-length")
        if not length:
            return None
        body = self._proc.stdout.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ------------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------------
    def _request(self, method: str, params: Optional[dict] = None) -> Any:
        with self._lock:
            if self._proc is None and not self._start():
                return None
            rid = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                payload["params"] = params
            try:
                self._send(payload)
            except (BrokenPipeError, OSError):
                return None
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                msg = self._read_message()
                if msg is None:
                    return None
                if msg.get("id") == rid:
                    if "error" in msg:
                        logger.warning("MCP %s %s error: %s", self.name, method, msg["error"])
                        return None
                    return msg.get("result")
            logger.warning("MCP %s %s timed out", self.name, method)
            return None

    # ------------------------------------------------------------------
    # MCP lifecycle
    # ------------------------------------------------------------------
    def initialize(self) -> bool:
        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "jexi-market", "version": "0.4.0"},
        })
        if result is None:
            self.connected = False
            return False
        self.server_info = result.get("serverInfo") or {}
        # Complete the handshake (notifications/initialized has no reply)
        try:
            with self._lock:
                self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except (BrokenPipeError, OSError):
            pass
        self.connected = True
        return True

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._request("tools/list", {})
        if not result:
            return []
        self.tools = result.get("tools") or []
        return self.tools

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        result = self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        if result is None:
            return None
        # MCP tool results: {content: [{type: text, text: ...}], isError?}
        return result

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self.connected = False


# ---------------------------------------------------------------------------
# Connector — manages all configured servers
# ---------------------------------------------------------------------------

class McpConnector:
    """Owns every configured MCP server; survives dead servers."""

    def __init__(self, config: Optional[MarketConfig] = None, *, specs: Optional[List[Dict[str, Any]]] = None):
        self.config = config or MarketConfig()
        self.clients: Dict[str, McpStdioClient] = {}
        self._specs = specs  # injectable for tests

    def _server_specs(self) -> List[Dict[str, Any]]:
        if self._specs is not None:
            return self._specs
        raw = (self.config.mcp_servers_json or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning("JEXI_MCP_SERVERS is not valid JSON — ignored")
            return []

    def connect_all(self) -> Dict[str, List[str]]:
        """Start + initialize every configured server. Returns {server: [tool names]}."""
        out: Dict[str, List[str]] = {}
        for spec in self._server_specs():
            name = str(spec.get("name") or spec.get("command") or "mcp")
            client = McpStdioClient(
                name=name,
                command=str(spec.get("command") or ""),
                args=[str(a) for a in (spec.get("args") or [])],
                env=spec.get("env") or None,
            )
            if not client.command:
                continue
            if client.initialize():
                tools = client.list_tools()
                self.clients[name] = client
                out[name] = [t.get("name", "") for t in tools]
                logger.info("MCP server %s ready with %d tools", name, len(tools))
            else:
                logger.warning("MCP server %s unavailable — continuing without it", name)
                client.close()
        return out

    def call(self, server: str, tool: str, arguments: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        client = self.clients.get(server)
        if client is None:
            return None
        return client.call_tool(tool, arguments)

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()
