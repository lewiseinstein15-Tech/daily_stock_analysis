# -*- coding: utf-8 -*-
"""Tests for the risk gate."""

from jexi_market.contracts import (
    Confidence,
    Decision,
    Evidence,
    MarketRegime,
    RiskEnvelope,
    Severity,
    SignalDirection,
)
from jexi_market.risk import PortfolioState, RiskGate


def _make_decision(
    direction=SignalDirection.LONG,
    *,
    position_fraction=0.1,
    risk_per_trade=0.02,
    entry=100.0,
    stop_loss=95.0,
    take_profit=110.0,
    symbol="TEST",
) -> Decision:
    return Decision(
        symbol=symbol,
        direction=direction,
        confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=3),
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_fraction=position_fraction,
        risk_per_trade=risk_per_trade,
        thesis="test",
        invalidation="test",
        evidence=(Evidence(claim="test", source="test"),),
        regime=MarketRegime.BULL,
    )


def test_gate_approves_flat_decision():
    gate = RiskGate()
    portfolio = PortfolioState()
    decision = _make_decision(SignalDirection.FLAT)
    result = gate.check(decision, portfolio)
    assert result.approved is True
    assert "FLAT" in result.reason


def test_gate_approves_compliant_long():
    gate = RiskGate()
    portfolio = PortfolioState(equity=100_000.0, cash=100_000.0)
    decision = _make_decision(SignalDirection.LONG, position_fraction=0.1, risk_per_trade=0.02)
    result = gate.check(decision, portfolio)
    assert result.approved is True
    assert len(result.violations) == 0


def test_gate_rejects_excessive_risk_per_trade():
    gate = RiskGate()
    portfolio = PortfolioState()
    decision = _make_decision(SignalDirection.LONG, risk_per_trade=0.05)  # 5% > 2% limit
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert any(v.rule == "max_risk_per_trade" for v in result.violations)


def test_gate_rejects_excessive_position_fraction():
    gate = RiskGate()
    portfolio = PortfolioState()
    decision = _make_decision(SignalDirection.LONG, position_fraction=0.5)  # 50% > 25%
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert any(v.rule == "max_position_fraction" for v in result.violations)


def test_gate_halts_on_drawdown_threshold():
    envelope = RiskEnvelope(drawdown_halt_threshold=0.10)
    gate = RiskGate(envelope)
    # Portfolio in 12% drawdown
    portfolio = PortfolioState(equity=88_000.0, peak_equity=100_000.0)
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert gate.halted is True
    assert any(v.rule == "drawdown_halt_threshold" for v in result.violations)


def test_gate_halts_on_daily_loss_limit():
    envelope = RiskEnvelope(daily_loss_limit=0.04)
    gate = RiskGate(envelope)
    portfolio = PortfolioState(equity=95_000.0, daily_pnl=-5_000.0)  # 5% loss > 4% limit
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert gate.halted is True


def test_gate_blocks_all_trades_when_halted():
    gate = RiskGate()
    gate.halt("test halt")
    portfolio = PortfolioState()
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert "halted" in result.reason.lower()


def test_gate_clear_halt_resumes_trading():
    gate = RiskGate()
    gate.halt("test halt")
    gate.clear_halt()
    assert gate.halted is False
    portfolio = PortfolioState()
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is True


def test_gate_blocks_live_trading_without_paper_validation():
    """Spec: 30 days of paper validation required before live trading."""
    envelope = RiskEnvelope(live_trading_enabled=True, min_30d_paper_validation=30)
    gate = RiskGate(envelope)
    portfolio = PortfolioState(paper_trading_days=5)  # only 5 paper days
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is False
    assert any(v.rule == "paper_validation_required" for v in result.violations)


def test_gate_allows_live_trading_after_validation():
    envelope = RiskEnvelope(live_trading_enabled=True, min_30d_paper_validation=30)
    gate = RiskGate(envelope)
    portfolio = PortfolioState(paper_trading_days=35)  # 35 > 30
    decision = _make_decision(SignalDirection.LONG)
    result = gate.check(decision, portfolio)
    assert result.approved is True


def test_gate_sectors_concentration_warning():
    """Sector concentration breaches produce a WARNING, not a block."""
    envelope = RiskEnvelope(max_sector_concentration=0.30)
    gate = RiskGate(envelope)
    portfolio = PortfolioState(
        equity=100_000.0,
        sector_exposure={"TEST": 0.25},  # already 25% in TEST sector
    )
    # Adding another 10% in TEST -> 35% > 30% limit
    decision = _make_decision(SignalDirection.LONG, position_fraction=0.10, symbol="TEST")
    result = gate.check(decision, portfolio)
    assert any(v.rule == "max_sector_concentration" for v in result.violations)


def test_portfolio_state_drawdown():
    state = PortfolioState(equity=90_000.0, peak_equity=100_000.0)
    assert 0.09 < state.drawdown < 0.11


def test_portfolio_state_daily_loss():
    state = PortfolioState(equity=95_000.0, daily_pnl=-5_000.0)
    assert 0.05 < state.daily_loss < 0.06
