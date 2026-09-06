# -*- coding: utf-8 -*-
"""Regression tests for trading-bot safety, ntfy configuration, and agent advisory mode."""

from __future__ import annotations

import os
from unittest import mock

import automated_trading_bot as bot


class StubNotifier:
    def __init__(self):
        self.calls = []

    def send(self, title, message, priority=3, tags=None):
        self.calls.append({"title": title, "message": message, "priority": priority, "tags": tags})
        return True


def _bars(count=30):
    return [
        {"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "c": 100 + i, "o": 99 + i, "h": 101 + i,
         "l": 98 + i, "v": 1000 + i}
        for i in range(count)
    ]


class FakeMarketClient:
    def get_latest_quote(self, symbol):
        return {"ap": 100.0, "bp": 99.9}

    def get_bars(self, symbol, timeframe="1Day", limit=None):
        return _bars()


def test_ntfy_url_is_canonical_for_standalone_bot():
    with mock.patch.dict(
        os.environ,
        {
            "NTFY_URL": "https://notify.example/proxy/my-topic",
            "NTFY_SERVER": "https://ignored.example",
            "NTFY_TOPIC": "ignored-topic",
        },
        clear=True,
    ):
        config = bot.BotConfig.from_env()
    assert config.ntfy_server == "https://notify.example/proxy"
    assert config.ntfy_topic == "my-topic"


def test_ntfy_url_parser_rejects_root_and_preserves_proxy_prefix():
    assert bot.resolve_ntfy_url("https://ntfy.sh") == (None, None)
    assert bot.resolve_ntfy_url("https://ntfy.example/base/topic%2Done") == (
        "https://ntfy.example/base",
        "topic-one",
    )


def test_margin_buying_power_cannot_increase_equity_budget():
    config = bot.BotConfig(
        max_position_percent=50,
        cash_reserve_percent=20,
        max_stocks=3,
        max_buys_per_cycle=3,
        use_repo_analyzer=False,
    )
    candidates = [
        {"symbol": "AAPL", "price": 100, "score": 90, "tradeable": True},
        {"symbol": "MSFT", "price": 100, "score": 80, "tradeable": True},
        {"symbol": "NVDA", "price": 100, "score": 70, "tradeable": True},
    ]
    plans = bot.RiskAgent(config).plan_entries(
        candidates,
        {"equity": "100000", "buying_power": "400000", "cash": "100000"},
        [],
        [],
    )
    assert sum(plan.budget for plan in plans) <= 80000
    assert sum(plan.budget for plan in plans) == 80000


def test_non_paper_endpoint_is_refused_before_client_calls():
    notifier = StubNotifier()
    config = bot.BotConfig(
        api_key="key",
        secret_key="secret",
        trading_base_url="https://api.alpaca.markets",
        ntfy_server="https://notify.example",
        ntfy_topic="topic",
        paper_only=True,
    )
    assert bot.run_cycle(config=config, notifier=notifier) == 3
    assert notifier.calls
    assert "Refusing to trade" in notifier.calls[0]["message"]


def test_optional_repository_agent_advisory_is_blended_but_cannot_execute():
    class FakeExecutor:
        def __init__(self):
            self.calls = []

        def run(self, prompt, context=None):
            self.calls.append((prompt, context))
            return type(
                "Result",
                (),
                {
                    "success": True,
                    "dashboard": {
                        "sentiment_score": 90,
                        "decision_type": "buy",
                        "analysis_summary": "Technical and intelligence agents agree.",
                        "risk_warning": "Paper advisory only.",
                    },
                    "model": "test-model",
                    "error": None,
                },
            )()

    config = bot.BotConfig(
        use_repo_analyzer=False,
        use_llm_agents=True,
        llm_agent_weight=0.5,
    )
    agent = bot.ResearchAgent(FakeMarketClient(), config)
    executor = FakeExecutor()
    agent._get_llm_executor = lambda: executor

    result = agent.research_symbol("AAPL")

    assert result["tradeable"] is True
    assert result["llm_advisory"]["status"] == "ok"
    assert result["technical_score"] == 63  # monotonic but overbought fallback score
    assert result["llm_score"] == 90
    assert result["score"] == 76
    assert executor.calls and executor.calls[0][1]["stock_code"] == "AAPL"


def test_data_quality_agent_blocks_incomplete_symbols():
    audit = bot.DataQualityAgent.validate_research(
        [
            {"symbol": "AAPL", "price": 100, "bars": 30, "tradeable": True},
            {"symbol": "MSFT", "price": 0, "bars": 0, "tradeable": False},
        ]
    )
    assert audit["tradeable_symbols"] == 1
    assert audit["ok"] is False
    assert "MSFT" in audit["warnings"][0]
