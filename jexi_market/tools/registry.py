# -*- coding: utf-8 -*-
"""Tool registry for JEXI Market.

A small, typed tool registry that lets agents call external capabilities
(search, market data, news, calculations) through a uniform interface.
Tools are intentionally simple callables — no MCP SDK dependency at
this layer; the MCP client (in ``src.jexi.mcp_client``) is a separate
adapter that can be plugged in via :meth:`ToolRegistry.register_mcp`.

Each tool call returns a :class:`ToolResult`.  Failed tool calls never
crash the caller — they return ``ok=False`` with an error message,
which agents treat as "tool unavailable".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jexi_market.contracts import ToolCall, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """A single registered tool."""

    name: str
    description: str
    fn: Callable[[Dict[str, Any]], Any]
    timeout_seconds: float = 30.0

    def call(self, arguments: Dict[str, Any]) -> ToolResult:
        import time as _t
        call_id = f"call_{int(_t.time() * 1000)}"
        start = _t.time()
        try:
            data = self.fn(arguments)
            elapsed_ms = (_t.time() - start) * 1000.0
            return ToolResult(
                call_id=call_id,
                ok=True,
                data=data,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (_t.time() - start) * 1000.0
            return ToolResult(
                call_id=call_id,
                ok=False,
                error=str(exc),
                elapsed_ms=elapsed_ms,
            )


class ToolRegistry:
    """In-memory tool registry."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def call(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(call_id="", ok=False, error=f"unknown tool: {name}")
        return tool.call(arguments)

    def register_mcp(self, mcp_client: Any) -> None:
        """Register tools from an MCP client (src.jexi.mcp_client).

        Each MCP tool is exposed under its name; calls are forwarded
        to the MCP client's ``call_tool`` method.
        """
        if not hasattr(mcp_client, "list_tools"):
            logger.warning("MCP client missing list_tools; skipping")
            return
        try:
            for tool_name in mcp_client.list_tools():
                def make_fn(tn):
                    def fn(args):
                        return mcp_client.call_tool(tn, args)
                    return fn
                self.register(Tool(
                    name=f"mcp.{tool_name}",
                    description=f"MCP tool: {tool_name}",
                    fn=make_fn(tool_name),
                ))
        except Exception as exc:
            logger.warning("MCP tool registration failed: %s", exc)


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


def _tool_get_quote(registry: "ToolRegistry", client) -> None:
    def fn(args: Dict[str, Any]):
        symbol = args.get("symbol", "")
        snap = client.get_daily(symbol, days=args.get("days", 5))
        if not snap.ok:
            return {"ok": False, "error": snap.error}
        return {
            "ok": True,
            "symbol": symbol,
            "latest_price": snap.latest_price,
            "last_date": snap.last_date,
            "provider": snap.provider,
        }
    registry.register(Tool(name="get_quote", description="Get latest price for a symbol", fn=fn))


def _tool_search_news(research_engine: Any, registry: "ToolRegistry") -> None:
    def fn(args: Dict[str, Any]):
        query = args.get("query", "")
        finding = research_engine.research(query, backend="web_search") if research_engine else None
        if not finding:
            return {"ok": False, "error": "no research backend available"}
        return finding.to_dict()
    registry.register(Tool(name="search_news", description="Search news / web for a topic", fn=fn))


def _tool_calc_position_size(registry: "ToolRegistry") -> None:
    def fn(args: Dict[str, Any]):
        equity = float(args.get("equity", 100_000.0))
        risk_per_trade = float(args.get("risk_per_trade", 0.02))
        stop_distance = float(args.get("stop_distance", 0.05))
        max_fraction = float(args.get("max_fraction", 0.25))
        if stop_distance <= 0:
            return {"ok": False, "error": "stop_distance must be positive"}
        fraction = min(risk_per_trade / stop_distance, max_fraction)
        return {
            "ok": True,
            "fraction": fraction,
            "dollar_allocation": equity * fraction,
            "risk_dollars": equity * risk_per_trade,
        }
    registry.register(Tool(name="calc_position_size", description="Risk-based position sizing", fn=fn))


def build_default_registry(market_data_client: Any = None, research_engine: Any = None) -> ToolRegistry:
    """Build the default tool registry with built-in tools."""
    registry = ToolRegistry()
    if market_data_client is not None:
        _tool_get_quote(registry, market_data_client)
    if research_engine is not None:
        _tool_search_news(research_engine, registry)
    _tool_calc_position_size(registry)
    return registry
