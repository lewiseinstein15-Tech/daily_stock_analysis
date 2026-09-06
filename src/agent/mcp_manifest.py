# -*- coding: utf-8 -*-
"""MCP-compatible manifest export for the Jexi OS agent tool surface.

This module deliberately exports *descriptors*, not an MCP transport and not a
broker-execution server.  The repository's existing ToolSurface is an internal
Python boundary.  A manifest lets an MCP host discover safe research tools while
keeping order submission behind the deterministic RiskAgent / ExecutionAgent
path and the paper-trading safety gate.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

# Research tools that an external MCP host may discover without gaining a
# trading side effect.  Action-category tools are excluded by default.
_READ_ONLY_CATEGORIES = frozenset({"data", "analysis", "search", "market", "backtest"})


def build_mcp_manifest(
    registry: Any,
    *,
    include_categories: Optional[Iterable[str]] = None,
    include_actions: bool = False,
) -> Dict[str, Any]:
    """Return a JSON-serialisable MCP tool manifest from a ToolRegistry.

    The standard MCP fields are ``name``, ``description`` and ``inputSchema``.
    ``annotations`` and ``x-jexi-policy`` are additional host-side hints; an
    MCP client must still enforce its own allowlist and confirmation policy.
    """
    categories = set(include_categories or _READ_ONLY_CATEGORIES)
    if include_actions:
        categories.add("action")

    tools = []
    for tool in registry.list_tools():
        if tool.category not in categories:
            continue
        descriptor = tool.to_mcp_descriptor()
        policy = getattr(tool, "policy", None)
        read_only = getattr(policy, "read_only", None)
        side_effects = list(getattr(policy, "side_effects", []) or [])
        descriptor["annotations"] = {
            "readOnlyHint": read_only is True,
            "destructiveHint": bool(read_only is False or side_effects),
            "openWorldHint": tool.category in {"data", "search", "market"},
        }
        descriptor["x-jexi-policy"] = {
            "category": tool.category,
            "read_only": read_only,
            "side_effects": side_effects,
            "permissions": list(getattr(policy, "permissions", []) or []),
            "requires_confirmation": bool(read_only is not True),
            "requires_stock_scope": "stock" in (getattr(policy, "scope_dimensions", []) or []),
        }
        tools.append(descriptor)

    tools.sort(key=lambda item: item["name"])
    return {
        "name": "jexi-os-daily-stock-analysis",
        "version": "1",
        "description": (
            "Read-only research and backtest tools from daily_stock_analysis. "
            "Trading actions are not exposed by this manifest."
        ),
        "tools": tools,
    }


def build_default_mcp_manifest(config: Any = None) -> Dict[str, Any]:
    """Build a manifest from the repository's registered agent tools."""
    from src.agent.factory import get_tool_registry

    return build_mcp_manifest(get_tool_registry(config))
