# -*- coding: utf-8 -*-
"""Tests for the safe Jexi OS MCP descriptor export."""

from types import SimpleNamespace

from src.agent.mcp_manifest import build_mcp_manifest


class FakeTool:
    def __init__(self, name, category, read_only, side_effects=None):
        self.name = name
        self.category = category
        self.policy = SimpleNamespace(
            read_only=read_only,
            side_effects=side_effects or [],
            permissions=["market_data"],
            scope_dimensions=["stock"],
        )

    def to_mcp_descriptor(self):
        return {
            "name": self.name,
            "description": "test tool",
            "inputSchema": {"type": "object", "properties": {}},
        }


class FakeRegistry:
    def list_tools(self):
        return [
            FakeTool("get_quote", "data", True),
            FakeTool("submit_order", "action", False, ["broker_order"]),
        ]


def test_default_manifest_excludes_order_actions_and_marks_read_only():
    manifest = build_mcp_manifest(FakeRegistry())
    assert [tool["name"] for tool in manifest["tools"]] == ["get_quote"]
    assert manifest["tools"][0]["annotations"]["readOnlyHint"] is True
    assert manifest["tools"][0]["x-jexi-policy"]["requires_confirmation"] is False


def test_action_tools_can_be_explicitly_exported_but_require_confirmation():
    manifest = build_mcp_manifest(FakeRegistry(), include_actions=True)
    order = next(tool for tool in manifest["tools"] if tool["name"] == "submit_order")
    assert order["annotations"]["destructiveHint"] is True
    assert order["x-jexi-policy"]["requires_confirmation"] is True
