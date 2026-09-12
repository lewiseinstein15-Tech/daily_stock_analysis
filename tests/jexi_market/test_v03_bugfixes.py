# -*- coding: utf-8 -*-
"""v0.3 regression tests — bug fixes found in the code audit.

Each test pins a previously-broken behaviour so it can't silently
regress: B1 backtest exit cost, B2 look-ahead entry, B4 MACD seed,
B8 naked-short refusal, B9 paper-day pollution, B10 qty precision,
B11 synthetic determinism, B13 zero-equity guard, B15 scaled fraction.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jexi_market.backtest.engine import run_backtest
from jexi_market.config import MarketConfig
from jexi_market.contracts import Confidence, Decision, RiskEnvelope, SignalDirection
from jexi_market.data import load_synthetic_frame
from jexi_market.execution.alpaca import AlpacaClient, _format_qty
from jexi_market.indicators import macd
from jexi_market.memory import PerformanceMemory
from jexi_market.risk.gate import GateResult, PortfolioState, RiskGate
from jexi_market.strategies import get_strategy, list_strategies


# ---------------------------------------------------------------------------
# B1 — backtest exit cost must be proportional to notional, not P&L
# ---------------------------------------------------------------------------

def test_backtest_exit_cost_on_notional():
    """Two trades with opposite P&L must pay symmetric exit costs."""
    rows = []
    price = 100.0
    for i in range(60):
        rows.append({
            "date": f"2024-01-{i+1:02d}",
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1_000_000,
        })
        price += 0.10
    df = pd.DataFrame(rows)

    class AlwaysLongStrategy:
        name = "always_long"

        def run(self, factors):
            from jexi_market.strategies.registry import StrategyResult
            from jexi_market.contracts import SignalDirection
            return StrategyResult(
                direction=SignalDirection.LONG, score=0.9,
                stop_pct=0.50, target_pct=0.50,
            )

    result = run_backtest(
        df, AlwaysLongStrategy(), symbol="TEST",
        transaction_cost_bps=100.0, slippage_bps=0.0,  # 1% cost, visible
    )
    # With 1% round-trip costs on every trade, gross flat P&L is 0 but
    # net equity must be BELOW start — previously exit costs were ~0.
    assert result.total_return < 0.0, (
        "exit costs are not being charged on notional (B1 regression)"
    )


# ---------------------------------------------------------------------------
# B2 — entries must fill at the NEXT day's open, not the signal day's close
# ---------------------------------------------------------------------------

def test_backtest_entry_uses_next_open():
    """Signal on day i must not profit from day i's close-to-close move."""
    # A price series that gaps UP massively on day 31 (after the signal).
    closes = [100.0] * 31 + [110.0] + [110.0] * 10
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "date": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "open": c,
            "high": c * 1.001,
            "low": c * 0.999,
            "close": c,
            "volume": 1_000_000,
        })
    df = pd.DataFrame(rows)

    class SignalOnDay30:
        name = "day30_signal"
        # fires long on exactly the 31-bar window (day index 30)

        def run(self, factors):
            from jexi_market.strategies.registry import StrategyResult
            from jexi_market.contracts import SignalDirection
            if factors.rows == 31:
                return StrategyResult(direction=SignalDirection.LONG, score=1.0,
                                      stop_pct=0.20, target_pct=0.30)
            return StrategyResult()

    result = run_backtest(SignalOnDay30()(df) if False else df, SignalOnDay30(), symbol="TEST",
                          slippage_bps=0.0, transaction_cost_bps=0.0)
    # Entry must be at the day-31 OPEN (110), not the day-30 close (100),
    # so the 10-point gap is NOT captured as profit.
    assert result.n_trades == 1
    trade = result.trades[0]
    assert abs(trade.entry_price - 110.0) < 0.11, (
        f"entry filled at {trade.entry_price} — look-ahead! (B2 regression)"
    )


# ---------------------------------------------------------------------------
# B4 — MACD EMA seed must not double-count the seed bar
# ---------------------------------------------------------------------------

def test_macd_constant_series():
    """MACD of a constant series must be exactly (0, 0, 0)."""
    closes = [50.0] * 60
    line, signal, hist = macd(closes)
    assert line is not None and abs(line) < 1e-9
    assert signal is not None and abs(signal) < 1e-9
    assert hist is not None and abs(hist) < 1e-9


# ---------------------------------------------------------------------------
# B8 — naked shorts must be refused; sells clamped to held qty
# ---------------------------------------------------------------------------

class _FakePositionsClient:
    """AlpacaClient stub with configurable held positions."""

    def __init__(self, held):
        self._held = held
        self.submitted = []

    def submit_order(self, symbol, qty, side, **kwargs):
        self.submitted.append((symbol, qty, side))
        from jexi_market.execution.alpaca import Order
        return Order(id="1", status="filled", symbol=symbol, qty=qty, side=side,
                     type="market", time_in_force="day", filled_qty=qty,
                     filled_avg_price=100.0)

    def get_positions(self):
        return self._held


def _short_decision(symbol="AAPL", fraction=0.10):
    return Decision(
        symbol=symbol,
        direction=SignalDirection.SHORT,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=3),
        entry=100.0,
        position_fraction=fraction,
    )


def test_short_refused_without_held_position(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    client = AlpacaClient(MarketConfig())
    client._paper = True
    fake = _FakePositionsClient(held=[])
    monkeypatch.setattr(client, "get_positions", fake.get_positions)
    with pytest.raises(ValueError, match="long-only policy"):
        client.execute_decision(_short_decision(), 100_000.0, latest_price=100.0)


def test_short_clamped_to_held_qty(monkeypatch):
    from jexi_market.execution.alpaca import Position
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    client = AlpacaClient(MarketConfig())
    client._paper = True
    held = [Position(symbol="AAPL", qty=5.0, side="long", market_value=500.0,
                     cost_basis=500.0, unrealized_pl=0.0, unrealized_plpc=0.0,
                     current_price=100.0)]
    fake = _FakePositionsClient(held=held)
    monkeypatch.setattr(client, "get_positions", fake.get_positions)
    monkeypatch.setattr(client, "submit_order", fake.submit_order)
    # 10% of 100k = 10k -> 100 shares proposed, but only 5 held.
    client.execute_decision(_short_decision(), 100_000.0, latest_price=100.0)
    assert len(fake.submitted) == 1
    assert fake.submitted[0][1] == 5.0   # clamped
    assert fake.submitted[0][2] == "sell"


# ---------------------------------------------------------------------------
# B10 — qty precision must be broker-safe
# ---------------------------------------------------------------------------

def test_format_qty_precision():
    assert _format_qty(13.233333333333334) == "13.23"
    assert _format_qty(100.0) == "100"
    assert _format_qty(7) == "7"
    assert _format_qty(0.125) == "0.12"  # rounds to 2dp


# ---------------------------------------------------------------------------
# B9 — FLAT decisions must not count as paper-trading days
# ---------------------------------------------------------------------------

def test_paper_trading_days_excludes_flat():
    memory = PerformanceMemory(":memory:")
    flat = Decision(symbol="X", direction=SignalDirection.FLAT,
                    confidence=Confidence(), entry=None)
    real = Decision(symbol="Y", direction=SignalDirection.LONG,
                    confidence=Confidence(agreement=0.8, data_freshness=1.0,
                                          evidence_count=2),
                    entry=100.0)
    for _ in range(5):
        memory.record_decision(flat)
    memory.record_decision(real)
    assert memory.paper_trading_days() == 1, (
        "FLAT rows must not count toward the 30-day live gate (B9 regression)"
    )


# ---------------------------------------------------------------------------
# B11 — synthetic data must be deterministic across processes
# ---------------------------------------------------------------------------

def test_synthetic_frame_deterministic():
    import subprocess
    code = (
        "import sys; sys.path.insert(0, '.');"
        "from jexi_market.data import load_synthetic_frame;"
        "df = load_synthetic_frame('AAPL', 30, 0);"
        "print(float(df['close'].iloc[0]))"
    )
    outs = []
    for _ in range(2):
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        outs.append(proc.stdout.strip())
    assert outs[0] == outs[1] and outs[0], (
        f"synthetic frame differs across processes: {outs} (B11 regression)"
    )


# ---------------------------------------------------------------------------
# B13 — gate must not crash on zero equity
# ---------------------------------------------------------------------------

def test_gate_zero_equity_no_crash():
    gate = RiskGate(RiskEnvelope())
    decision = Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=3),
        entry=100.0, position_fraction=0.10,
    )
    portfolio = PortfolioState(equity=0.0, cash=0.0, positions_value=0.0)
    result = gate.check(decision, portfolio)
    assert isinstance(result, GateResult)


# ---------------------------------------------------------------------------
# B15 — mild position overshoot is scaled + approved; gross is rejected
# ---------------------------------------------------------------------------

def test_gate_scales_mild_overshoot():
    gate = RiskGate(RiskEnvelope(max_position_fraction=0.25))
    decision = Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=3),
        entry=100.0, position_fraction=0.30,   # 1.2x the cap
    )
    result = gate.check(decision, PortfolioState(equity=100_000.0))
    assert result.approved
    assert result.scaled_position_fraction == 0.25


def test_gate_rejects_gross_overshoot():
    gate = RiskGate(RiskEnvelope(max_position_fraction=0.25))
    decision = Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=3),
        entry=100.0, position_fraction=0.75,   # 3x the cap
    )
    result = gate.check(decision, PortfolioState(equity=100_000.0))
    assert not result.approved


# ---------------------------------------------------------------------------
# New strategies registered and functional
# ---------------------------------------------------------------------------

def test_v03_strategies_registered():
    expected = {
        "bollinger_squeeze", "triple_ma_cross", "supertrend",
        "momentum_12_1", "williams_reversal", "vwap_reversion",
        "ensemble_consensus",
    }
    assert expected.issubset(set(list_strategies()))


def test_ensemble_produces_consensus():
    df = load_synthetic_frame("AAPL", 140, 7)
    from jexi_market.indicators import compute_factors
    factors = compute_factors(df, symbol="AAPL")
    ensemble = get_strategy("ensemble_consensus")
    result = ensemble.run(factors)
    assert result.rationale  # always explains itself
    assert -1.0 <= result.score <= 1.0
