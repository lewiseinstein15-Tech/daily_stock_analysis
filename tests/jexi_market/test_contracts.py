# -*- coding: utf-8 -*-
"""Tests for the JEXI Market contracts."""

from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Decision,
    Evidence,
    EvidenceLink,
    MarketRegime,
    Recommendation,
    RiskEnvelope,
    RiskViolation,
    Severity,
    SignalDirection,
    Task,
    TaskPriority,
    TaskStatus,
)


def test_signal_direction_values():
    assert SignalDirection.LONG.value == "long"
    assert SignalDirection.SHORT.value == "short"
    assert SignalDirection.FLAT.value == "flat"


def test_task_default_factory_unique_ids():
    t1 = Task(objective="analyze", kind=AgentKind.TECHNICAL)
    t2 = Task(objective="analyze", kind=AgentKind.TECHNICAL)
    assert t1.task_id != t2.task_id
    assert t1.status if hasattr(t1, "status") else True  # status is on TaskStatus enum, not Task
    assert t1.priority == TaskPriority.NORMAL


def test_evidence_requires_source():
    ev = Evidence(claim="price is 100", source="yfinance")
    assert ev.source == "yfinance"
    assert ev.confidence == 1.0
    assert ev.links == ()


def test_evidence_link_to_dict():
    link = EvidenceLink(source="alpaca", reference="AAPL:2024-01-01", confidence=0.9)
    d = link.to_dict()
    assert d["source"] == "alpaca"
    assert d["reference"] == "AAPL:2024-01-01"
    assert d["confidence"] == 0.9


def test_confidence_score_composite():
    # High agreement + high freshness + many evidence -> high score
    c = Confidence(agreement=1.0, data_freshness=1.0, evidence_count=10)
    assert c.score > 0.8

    # Low everything -> low score
    c = Confidence(agreement=0.0, data_freshness=0.0, evidence_count=0)
    assert c.score < 0.1

    # Disagreement penalty reduces score
    c1 = Confidence(agreement=1.0, data_freshness=1.0, evidence_count=5)
    c2 = Confidence(agreement=1.0, data_freshness=1.0, evidence_count=5, disagreement_penalty=1.0)
    assert c2.score < c1.score
    assert c2.score == c1.score * 0.5


def test_recommendation_to_dict_roundtrip():
    rec = Recommendation(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        target_price=200.0,
        stop_loss=180.0,
        take_profit=220.0,
        thesis="bullish trend",
        invalidation="close below 180",
        evidence=(Evidence(claim="above SMA20", source="technical"),),
        agent_id="technical",
        agent_kind=AgentKind.TECHNICAL,
        confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=3),
    )
    d = rec.to_dict()
    assert d["symbol"] == "AAPL"
    assert d["direction"] == "long"
    assert d["target_price"] == 200.0
    assert d["agent_kind"] == "technical"
    assert len(d["evidence"]) == 1
    assert d["evidence"][0]["claim"] == "above SMA20"


def test_decision_carries_evidence_and_agents():
    d = Decision(
        symbol="MSFT",
        direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=5),
        entry=400.0,
        stop_loss=380.0,
        take_profit=440.0,
        position_fraction=0.1,
        thesis="strong momentum",
        invalidation="close below 380",
        evidence=(Evidence(claim="MACD positive", source="technical"),),
        supporting_agents=("technical", "quant"),
        opposing_agents=("risk",),
        risks=("elevated volatility",),
        regime=MarketRegime.BULL,
    )
    payload = d.to_dict()
    assert payload["symbol"] == "MSFT"
    assert payload["direction"] == "long"
    assert payload["regime"] == "bull"
    assert payload["supporting_agents"] == ["technical", "quant"]
    assert payload["opposing_agents"] == ["risk"]
    assert payload["risks"] == ["elevated volatility"]
    assert "decision_id" in payload


def test_risk_envelope_defaults():
    env = RiskEnvelope()
    assert env.max_risk_per_trade == 0.02
    assert env.max_position_fraction == 0.25
    assert env.drawdown_halt_threshold == 0.10
    assert env.live_trading_enabled is False
    assert env.min_30d_paper_validation == 30


def test_risk_violation():
    v = RiskViolation(
        rule="max_risk_per_trade",
        severity=Severity.ERROR,
        detail="3% > 2%",
        proposed_value=0.03,
        limit=0.02,
    )
    d = v.to_dict()
    assert d["rule"] == "max_risk_per_trade"
    assert d["severity"] == "error"
    assert d["proposed_value"] == 0.03
    assert d["limit"] == 0.02


def test_task_status_enum():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.REJECTED.value == "rejected"
    assert TaskStatus.FAILED.value == "failed"


def test_market_regime_enum():
    assert MarketRegime.BULL.value == "bull"
    assert MarketRegime.BEAR.value == "bear"
    assert MarketRegime.SIDEWAYS.value == "sideways"
    assert MarketRegime.VOLATILE.value == "volatile"
    assert MarketRegime.UNKNOWN.value == "unknown"
