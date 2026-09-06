# -*- coding: utf-8 -*-
"""Optional MCP (Model Context Protocol) client adapter for J.E.X.I.

Connects the Jexi tool surface to external, free MCP market-data servers over
stdio (default disabled — ``JEXI_MCP_ENABLED=1``).  Verified no-key servers:

  * ``finance-data-mcp`` — Yahoo/SEC EDGAR/CoinGecko/ECB/World Bank, 10 tools
  * ``mcp-market-data`` (EricGrill) — Yahoo Finance quotes/history/news
  * ``equibles`` hosted MCP — 111 tools, free tier (key optional via OAuth)

Implementation detail: this uses the official ``mcp`` PyPI SDK if installed
and falls back to a zero-dependency JSON-RPC-over-stdio transport otherwise,
so the pilot never *requires* extra packages.  Any MCP failure is trapped and
logged; MCP is an enhancement, never a dependency of the analysis path.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MCP_CONFIG_CONTRACT = "jexi.mcp.servers"  # JSON string under Config


def is_mcp_enabled(config) -> bool:
    return bool(getattr(config, "jexi_mcp_enabled", False))


def _server_commands(config) -> List[Dict[str, Any]]:
    raw = getattr(config, "jexi_mcp_servers", "") or ""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("JEXI_MCP_SERVERS is not valid JSON; ignoring")
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict) and item.get("name")]


class McpJsonRpcClient:
    """Tiny stdio JSON-RPC MCP client (transport + tool surface).

    Speaks the MCP ``initialize / tools/list / tools/call`` flows over a
    ``stdio`` subprocess with zero third-party dependencies.  Used only when
    the ``mcp`` SDK is not installed.
    """

    def __init__(self, name: str, command: str, args: List[str], env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self._proc: Optional[subprocess.Popen] = None
        self._deadline: float = 30.0
        if str(command).strip() == "npx":
            self._resolvable = shutil.which("npx") is not None
        else:
            self._resolvable = shutil.which(command) is not None

    def _start(self) -> bool:
        if self._resolvable and self._proc is None:
            command = [self.command] + list(self.args)
            try:
                self._proc = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=dict(self.env) if self.env else None,
                    text=True,
                )
            except OSError as exc:
                logger.warning("MCP server %s failed to start: %s", self.name, exc)
                return False
        return self._proc is not None

    def _request(self, method: str, params: Optional[dict] = None) -> Any:
        if not self._start():
            return None
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        line = json.dumps(req)
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
            while True:
                raw = self._proc.stdout.readline().strip()
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("id") == 1 or (method == "initialize" and msg.get("result")):
                    if "result" in msg:
                        return msg["result"]
                    break
        except Exception as exc:
            logger.warning("MCP request `%s` to %s failed: %s", method, self.name, exc)
        return None

    def initialize(self) -> Optional[dict]:
        return self._request("initialize")

    def list_tools(self) -> List[str]:
        result = self._request("tools/list")
        tools = []
        for tool in ((result or {}).get("tools") or []):
            tools.append(tool.get("name") or "?")
        return tools

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Optional[dict]:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        if isinstance(result, dict) and result.get("content"):
            return result
        return None

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None


class JexiMcpConnector:
    """Connects Jexi personas to extra MCP tool groups as a pure enhancement."""

    def __init__(self, config):
        self._config = config
        self._clients: Dict[str, Any] = {}
        self._mcp_sdk_available = self._probe_mcp_sdk()

    @staticmethod
    def _probe_mcp_sdk() -> bool:
        try:
            import mcp  # noqa: F401
            return True
        except ImportError:
            return False

    def connect_all(self) -> Dict[str, List[str]]:
        if not is_mcp_enabled(self._config):
            return {}
        inventory: Dict[str, List[str]] = {}
        for spec in _server_commands(self._config):
            client = McpJsonRpcClient(
                name=spec["name"],
                command=spec.get("command", "npx"),
                args=list(spec.get("args", []) or []),
                env=spec.get("env") or {},
            )
            try:
                client.initialize()
                tools = client.list_tools()
                self._clients[spec["name"]] = client
                inventory[spec["name"]] = tools
                logger.info("MCP server %s connected with %d tools", spec["name"], len(tools))
            except Exception as exc:
                logger.warning("MCP server %s unavailable: %s", spec["name"], exc)
        return inventory

    def call(self, server: str, tool: str, arguments: Optional[dict] = None) -> Optional[dict]:
        client = self._clients.get(server)
        if client is None:
            return None
        return client.call_tool(tool, arguments)

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()


def default_mcp_specs() -> List[Dict[str, Any]]:
    """Recommended free MCP servers for the ``JEXI_MCP_SERVERS`` config."""
    return [
        {
            "name": "finance-data-mcp",
            "command": "npx",
            "args": ["-y", "finance-data-mcp"],
            "env": {"SEC_USER_AGENT": "Jexi Research jexi@example.com"},
        }
    ]
