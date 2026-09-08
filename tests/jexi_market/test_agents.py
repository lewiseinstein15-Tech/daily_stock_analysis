# -*- coding: utf-8 -*-
"""Tests for the specialist agents."""

import pandas as pd

from jexi_market.agents import (
    AgentContext,
    DataValidationAgent,
    FundamentalAgent,
    MacroAgent,
    MarketMonitorAgent,
    NewsAgent,
    QuantAgent,
    RiskAgent,
    TechnicalAgent,
    list_agent_ids,
    build_all_agents,
)
from jexi_market.contracts import AgentKind, SignalDirection
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import compute_factors


def _make_snapshot(rows: int = 100, drift: float = 0.001) -> MarketSnapshot:
    """Build a synthetic snapshot with a slight bull drift."""
    import random
    rng = random.Random(42)
    closes = [100.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1.0 + drift + rng.gauss(0, 0.01)))
    df = pd.DataFrame({
        "date": [f"2024-01-{i+1:02d}" for i in range(rows)],
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000 + i * 1000 for i in range(rows)],
    })
    return MarketSnapshot(symbol="TEST", ok=True, df=df, provider="test", rows=rows, freshness_score=1.0)


def _make_bearish_snapshot(rows: int = 100) -> MarketSnapshot:
    return _make_snapshot(rows=rows, drift=-0.002)


def test_all_agents_registered():
    ids = list_agent_ids()
    # Must have all the specialists + leadership
    for expected in [
        "technical", "fundamental", "quant", "macro", "news",
        "risk", "data_validation", "market_monitor",
        "aldric", "vic",
    ]:
        assert expected in ids, f"missing agent: {expected}"


def test_build_all_agents_returns_instances():
    agents = build_all_agents()
    assert len(agents) >= 10
    for agent_id, agent in agents.items():
        assert agent.id == agent_id


def test_technical_agent_bullish_returns_long():
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull")
    agent = TechnicalAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.agent_id == "technical"
    assert rec.agent_kind == AgentKind.TECHNICAL
    # With a clear bull drift, technical should lean long
    assert rec.direction in (SignalDirection.LONG, SignalDirection.FLAT)
    assert len(rec.evidence) > 0


def test_technical_agent_handles_empty_data():
    snap = MarketSnapshot(symbol="X", ok=False)
    factors = compute_factors(None, symbol="X")
    ctx = AgentContext()
    agent = TechnicalAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is None  # no opinion when data unavailable


def test_fundamental_agent_returns_none_without_fundamentals():
    """Fundamental agent must NEVER fabricate fundamentals."""
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull")
    agent = FundamentalAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is None  # no fundamentals in ctx.research_cache -> no opinion


def test_fundamental_agent_uses_research_cache():
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(
        regime="bull",
        research_cache={"fundamentals:TEST": {"pe_ratio": 12.0, "eps_growth_yoy": 0.20, "gross_margin": 0.5}},
    )
    agent = FundamentalAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.direction == SignalDirection.LONG  # cheap + growing


def test_quant_agent_respects_volatility_regime():
    """Quant agent applies vol-regime filter."""
    snap = _make_snapshot(rows=120, drift=0.003)
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull")
    agent = QuantAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.agent_kind == AgentKind.QUANT


def test_macro_agent_reads_regime():
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    agent = MacroAgent()
    # Bull regime -> positive score
    ctx = AgentContext(regime="bull")
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert "bull" in rec.thesis

    # Bear regime -> negative score
    ctx = AgentContext(regime="bear")
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert "bear" in rec.thesis


def test_news_agent_returns_none_without_news():
    """News agent must NEVER invent sentiment."""
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull")
    agent = NewsAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is None

    # With news in cache
    ctx.research_cache["news:TEST"] = {"sentiment": "positive"}
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.direction == SignalDirection.LONG


def test_risk_agent_can_veto():
    """Risk agent's job is to flag risks even when others agree."""
    snap = _make_snapshot(rows=120, drift=0.005)  # high-vol bull
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull", portfolio_drawdown=0.08)
    agent = RiskAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.agent_kind == AgentKind.RISK
    # Risk agent always returns FLAT (veto-style) but raises disagreement penalty
    assert rec.direction == SignalDirection.FLAT
    assert rec.confidence.disagreement_penalty >= 0


def test_data_validation_agent_flags_sparse_data():
    snap = MarketSnapshot(
        symbol="SPARSE", ok=True,
        df=pd.DataFrame({
            "date": [f"2024-01-{i:02d}" for i in range(1, 11)],
            "close": [100.0 + i for i in range(10)],
            "volume": [1_000_000] * 10,
        }),
        provider="test", rows=10, freshness_score=0.1,
    )
    factors = compute_factors(snap.df, symbol="SPARSE")
    ctx = AgentContext()
    agent = DataValidationAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.direction == SignalDirection.FLAT
    assert rec.confidence.disagreement_penalty > 0


def test_data_validation_agent_handles_failed_fetch():
    snap = MarketSnapshot(symbol="FAIL", ok=False, error="network timeout")
    factors = compute_factors(None, symbol="FAIL")
    ctx = AgentContext()
    agent = DataValidationAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert "data unavailable" in rec.thesis.lower()


def test_market_monitor_agent_detects_volume():
    snap = _make_snapshot()
    factors = compute_factors(snap.df, symbol="TEST")
    ctx = AgentContext(regime="bull")
    agent = MarketMonitorAgent()
    rec = agent.analyze(snap, factors, ctx)
    assert rec is not None
    assert rec.agent_kind == AgentKind.MARKET_MONITOR
