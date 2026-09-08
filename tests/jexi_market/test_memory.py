# -*- coding: utf-8 -*-
"""Tests for the performance memory."""

import os
import tempfile

from jexi_market.config import MarketConfig
from jexi_market.contracts import (
    Confidence,
    Decision,
    Evidence,
    MarketRegime,
    SignalDirection,
)
from jexi_market.memory import PerformanceMemory


def _make_decision(direction=SignalDirection.LONG) -> Decision:
    return Decision(
        symbol="TEST",
        direction=direction,
        confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=3),
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        position_fraction=0.1,
        risk_per_trade=0.02,
        thesis="test",
        invalidation="test",
        evidence=(Evidence(claim="test", source="test"),),
        supporting_agents=("technical", "macro"),
        opposing_agents=("risk",),
        regime=MarketRegime.BULL,
    )


def test_memory_initializes_schema(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)
    # Tables should exist — agent_stats query should not raise
    stats = memory.agent_stats()
    assert stats == {}


def test_record_decision_creates_trade_record(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)
    decision = _make_decision()
    trade_id = memory.record_decision(decision, regime="bull")
    assert trade_id > 0
    recent = memory.recent_trades(limit=5)
    assert len(recent) == 1
    assert recent[0]["symbol"] == "TEST"
    assert recent[0]["outcome"] == "open"


def test_close_trade_updates_outcome(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)
    decision = _make_decision()
    memory.record_decision(decision, regime="bull")
    memory.close_trade(
        decision.decision_id,
        exit_price=105.0,
        pnl_pct=0.05,
        exit_reason="take_profit",
        agents_correct=["technical", "macro"],
        agents_wrong=["risk"],
    )
    summary = memory.stats_summary()
    assert summary["n_trades"] == 1
    assert summary["n_win"] == 1
    assert summary["n_loss"] == 0
    assert summary["win_rate"] == 1.0


def test_agent_stats_tracks_accuracy(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)

    # Record 4 trades: 3 where technical was right, 1 wrong
    for i, (pnl, correct) in enumerate([(0.05, True), (-0.03, False), (0.02, True), (0.01, True)]):
        decision = _make_decision()
        memory.record_decision(decision, regime="bull")
        memory.close_trade(
            decision.decision_id,
            exit_price=100.0 * (1 + pnl),
            pnl_pct=pnl,
            exit_reason="test",
            agents_correct=["technical"] if correct else [],
            agents_wrong=[] if correct else ["technical"],
        )

    stats = memory.agent_stats()
    assert "technical" in stats
    assert stats["technical"]["n_calls"] == 4
    assert stats["technical"]["n_correct"] == 3
    assert 0.74 < stats["technical"]["accuracy"] < 0.76


def test_agent_weight_clamped(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)

    # With no history -> default weight 1.0
    assert memory.agent_weight("unknown_agent") == 1.0

    # Add some trades — agent always right
    for _ in range(5):
        decision = _make_decision()
        memory.record_decision(decision, regime="bull")
        memory.close_trade(
            decision.decision_id,
            exit_price=105.0,
            pnl_pct=0.05,
            exit_reason="take_profit",
            agents_correct=["technical"],
            agents_wrong=[],
        )

    # Agent with 100% accuracy -> weight at upper clamp (1.5)
    w = memory.agent_weight("technical")
    assert 1.4 < w <= 1.5


def test_agent_weight_low_accuracy_clamped(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)

    # Agent always wrong
    for _ in range(5):
        decision = _make_decision()
        memory.record_decision(decision, regime="bull")
        memory.close_trade(
            decision.decision_id,
            exit_price=95.0,
            pnl_pct=-0.05,
            exit_reason="stop_loss",
            agents_correct=[],
            agents_wrong=["technical"],
        )

    # 0% accuracy -> weight at lower clamp (0.5)
    w = memory.agent_weight("technical")
    assert 0.5 <= w < 0.6


def test_paper_trading_days_increments(tmp_path):
    db_path = str(tmp_path / "test_memory.sqlite")
    memory = PerformanceMemory(db_path)
    assert memory.paper_trading_days() == 0
    decision = _make_decision()
    memory.record_decision(decision, regime="bull")
    assert memory.paper_trading_days() == 1
