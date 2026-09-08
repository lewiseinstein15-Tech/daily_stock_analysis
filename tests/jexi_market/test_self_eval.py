# -*- coding: utf-8 -*-
"""Tests for the self-evaluation loop."""

import json
import time

from jexi_market.config import MarketConfig
from jexi_market.contracts import Confidence, Decision, Evidence, MarketRegime, SignalDirection
from jexi_market.data import MarketSnapshot, load_synthetic_frame
from jexi_market.memory import PerformanceMemory
from jexi_market.self_eval import SelfEvaluationLoop, ClosedTrade, _safe_json_list


def _make_decision(direction=SignalDirection.LONG, *, symbol="TEST", entry=100.0, stop=95.0, target=110.0) -> Decision:
    return Decision(
        symbol=symbol,
        direction=direction,
        confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=3),
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        position_fraction=0.1,
        risk_per_trade=0.02,
        thesis="test",
        invalidation="test",
        evidence=(Evidence(claim="test", source="test"),),
        supporting_agents=("technical", "macro"),
        opposing_agents=("risk",),
        regime=MarketRegime.BULL,
    )


def _make_bearish_decision() -> Decision:
    return _make_decision(SignalDirection.SHORT, symbol="BEAR", entry=100.0, stop=105.0, target=90.0).replace(
        symbol="BEAR", direction=SignalDirection.SHORT
    ) if False else Decision(
        symbol="BEAR",
        direction=SignalDirection.SHORT,
        confidence=Confidence(agreement=0.7, data_freshness=1.0, evidence_count=2),
        entry=100.0,
        stop_loss=105.0,
        take_profit=90.0,
        position_fraction=0.1,
        risk_per_trade=0.02,
        thesis="bearish",
        invalidation="close above 105",
        evidence=(Evidence(claim="test", source="test"),),
        supporting_agents=("quant",),
        opposing_agents=("technical",),
        regime=MarketRegime.BEAR,
    )


def test_safe_json_list_handles_all_inputs():
    assert _safe_json_list(None) == []
    assert _safe_json_list([]) == []
    assert _safe_json_list(["a", "b"]) == ["a", "b"]
    assert _safe_json_list('["a", "b"]') == ["a", "b"]
    assert _safe_json_list("not json") == []
    assert _safe_json_list(42) == []


def test_self_eval_returns_empty_when_no_open_trades(tmp_path):
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    loop = SelfEvaluationLoop(memory=memory)
    # Patch data client to avoid network calls
    loop.data_client = type("X", (), {"get_daily": lambda self, s, days=5: MarketSnapshot(symbol=s, ok=False)})()
    closed = loop.evaluate_open_trades()
    assert closed == []


def test_self_eval_closes_stop_loss(tmp_path):
    """A long position where latest drops below stop should close as stop_loss."""
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    decision = _make_decision(entry=100.0, stop=95.0, target=110.0)
    memory.record_decision(decision, regime="bull")

    loop = SelfEvaluationLoop(memory=memory)
    # Patch data client to return a snapshot with latest price 90 (below stop 95)
    import pandas as pd
    class FakeDataClient:
        def get_daily(self, symbol, days=5):
            return MarketSnapshot(
                symbol=symbol, ok=True,
                df=pd.DataFrame({"close": [90.0], "date": ["2024-09-08"]}),
                provider="test", rows=1, freshness_score=1.0,
            )
    loop.data_client = FakeDataClient()
    closed = loop.evaluate_open_trades()
    assert len(closed) == 1
    assert closed[0].exit_reason == "stop_loss"
    assert closed[0].exit_price == 95.0
    assert closed[0].pnl_pct < 0  # lost money
    # supporting (long) agents are wrong; opposing (risk) is correct
    assert "technical" in closed[0].agents_wrong
    assert "risk" in closed[0].agents_correct


def test_self_eval_closes_take_profit(tmp_path):
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    decision = _make_decision(entry=100.0, stop=95.0, target=110.0)
    memory.record_decision(decision, regime="bull")

    loop = SelfEvaluationLoop(memory=memory)
    import pandas as pd
    class FakeDataClient:
        def get_daily(self, symbol, days=5):
            return MarketSnapshot(
                symbol=symbol, ok=True,
                df=pd.DataFrame({"close": [115.0], "date": ["2024-09-08"]}),
                provider="test", rows=1, freshness_score=1.0,
            )
    loop.data_client = FakeDataClient()
    closed = loop.evaluate_open_trades()
    assert len(closed) == 1
    assert closed[0].exit_reason == "take_profit"
    assert closed[0].exit_price == 110.0
    assert closed[0].pnl_pct > 0
    assert "technical" in closed[0].agents_correct
    assert "risk" in closed[0].agents_wrong


def test_self_eval_closes_short_take_profit(tmp_path):
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    decision = _make_bearish_decision()
    memory.record_decision(decision, regime="bear")

    loop = SelfEvaluationLoop(memory=memory)
    import pandas as pd
    class FakeDataClient:
        def get_daily(self, symbol, days=5):
            # Price drops below target 90 -> take profit
            return MarketSnapshot(
                symbol=symbol, ok=True,
                df=pd.DataFrame({"close": [85.0], "date": ["2024-09-08"]}),
                provider="test", rows=1, freshness_score=1.0,
            )
    loop.data_client = FakeDataClient()
    closed = loop.evaluate_open_trades()
    assert len(closed) == 1
    assert closed[0].exit_reason == "take_profit"
    assert closed[0].exit_price == 90.0
    assert closed[0].pnl_pct > 0  # short profitable
    assert "quant" in closed[0].agents_correct


def test_self_eval_updates_agent_stats(tmp_path):
    """Closing a trade should update the agent_stats table."""
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    decision = _make_decision(entry=100.0, stop=95.0, target=110.0)
    memory.record_decision(decision, regime="bull")

    loop = SelfEvaluationLoop(memory=memory)
    import pandas as pd
    class FakeDataClient:
        def get_daily(self, symbol, days=5):
            return MarketSnapshot(
                symbol=symbol, ok=True,
                df=pd.DataFrame({"close": [115.0], "date": ["2024-09-08"]}),
                provider="test", rows=1, freshness_score=1.0,
            )
    loop.data_client = FakeDataClient()
    loop.evaluate_open_trades()

    stats = memory.agent_stats()
    assert "technical" in stats
    assert stats["technical"]["n_correct"] == 1
    assert "risk" in stats
    assert stats["risk"]["n_wrong"] == 1


def test_agent_leaderboard_sorted_by_accuracy(tmp_path):
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    # Add 5 trades where technical is always right
    for _ in range(5):
        decision = _make_decision(entry=100.0, stop=95.0, target=110.0)
        memory.record_decision(decision, regime="bull")
        memory.close_trade(
            decision.decision_id,
            exit_price=110.0, pnl_pct=0.10, exit_reason="take_profit",
            agents_correct=["technical"], agents_wrong=["risk"],
        )
    loop = SelfEvaluationLoop(memory=memory)
    board = loop.agent_leaderboard(min_calls=1)
    assert len(board) >= 2
    assert board[0]["accuracy"] >= board[-1]["accuracy"]
    assert board[0]["agent_id"] == "technical"


def test_agent_leaderboard_empty_when_no_history(tmp_path):
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    loop = SelfEvaluationLoop(memory=memory)
    board = loop.agent_leaderboard(min_calls=3)
    assert board == []


def test_closed_trade_to_dict():
    ct = ClosedTrade(
        decision_id="dec_1",
        symbol="TEST",
        direction="long",
        entry_price=100.0,
        exit_price=110.0,
        pnl_pct=0.10,
        exit_reason="take_profit",
        days_held=5,
        agents_correct=["technical"],
        agents_wrong=["risk"],
    )
    d = ct.to_dict()
    assert d["symbol"] == "TEST"
    assert d["direction"] == "long"
    assert d["pnl_pct"] == 0.10
    assert d["agents_correct"] == ["technical"]
