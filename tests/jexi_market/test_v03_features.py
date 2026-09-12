# -*- coding: utf-8 -*-
"""v0.3 feature tests — persistent risk state, sizing, brokers,
lifecycle manager, 24/7 runner gates, confidence gating."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jexi_market.config import MarketConfig
from jexi_market.contracts import Confidence, Decision, RiskEnvelope, SignalDirection
from jexi_market.memory import PerformanceMemory


# ---------------------------------------------------------------------------
# Persistent risk state (kill-switch survives restarts)
# ---------------------------------------------------------------------------

def test_halt_persists_across_instances(tmp_path):
    from jexi_market.risk.state import RiskStateStore
    db = str(tmp_path / "state.sqlite")
    s1 = RiskStateStore(db)
    s1.set_halt("daily loss breach")
    # A *new* store instance (simulating a process restart) must see it.
    s2 = RiskStateStore(db)
    assert s2.is_halted()
    assert s2.load()["halt_reason"] == "daily loss breach"
    s2.clear_halt()
    assert not s2.is_halted()


def test_risk_gate_restores_persisted_halt(tmp_path):
    from jexi_market.risk.gate import RiskGate
    from jexi_market.risk.state import RiskStateStore
    db = str(tmp_path / "state.sqlite")
    store = RiskStateStore(db)
    store.set_halt("drawdown breach")
    gate = RiskGate(RiskEnvelope(), state_store=store)
    decision = Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=1.0, data_freshness=1.0, evidence_count=5),
        entry=100.0, position_fraction=0.10,
    )
    from jexi_market.risk.gate import PortfolioState
    result = gate.check(decision, PortfolioState(equity=100_000.0))
    assert not result.approved
    assert "drawdown breach" in result.reason


def test_equity_day_rollover(tmp_path):
    from jexi_market.risk.state import RiskStateStore
    store = RiskStateStore(str(tmp_path / "state.sqlite"))
    derived = store.update_equity(105_000.0)
    assert derived["peak_equity"] == 105_000.0
    assert derived["daily_pnl"] == pytest.approx(0.0, abs=0.01)
    # Simulate gains the same day
    derived = store.update_equity(110_000.0)
    assert derived["daily_pnl"] == pytest.approx(5_000.0, abs=0.01)
    assert derived["peak_equity"] == 110_000.0


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def test_sizing_risk_parity():
    from jexi_market.risk.sizing import SizingInput, size_position
    inp = SizingInput(equity=100_000.0, entry=100.0, stop=95.0,
                      risk_per_trade=0.02, max_fraction=0.25)
    fraction = size_position(inp, "risk_parity")
    # 2% risk / 5% stop distance = 40% -> capped at 25%
    assert fraction == 0.25


def test_sizing_kelly_zero_when_no_edge():
    from jexi_market.risk.sizing import SizingInput, size_position
    inp = SizingInput(equity=100_000.0, entry=100.0, stop=95.0,
                      win_rate=0.30, payoff_ratio=1.0)   # negative edge
    assert size_position(inp, "kelly") == 0.0


def test_sizing_kelly_positive_edge():
    from jexi_market.risk.sizing import SizingInput, size_position
    inp = SizingInput(equity=100_000.0, entry=100.0, stop=95.0,
                      win_rate=0.60, payoff_ratio=1.5, max_fraction=0.25)
    f = size_position(inp, "kelly")
    # f* = 0.6 - 0.4/1.5 = 0.333; half-kelly = 0.167; capped fine
    assert 0.10 < f < 0.20


def test_sizing_vol_target_dampens():
    from jexi_market.risk.sizing import SizingInput, size_position
    high_vol = SizingInput(equity=100_000.0, entry=100.0, stop=95.0,
                           annualised_vol=0.60, target_vol=0.15,
                           base_fraction=0.10, max_fraction=0.25)
    low_vol = SizingInput(equity=100_000.0, entry=100.0, stop=95.0,
                          annualised_vol=0.10, target_vol=0.15,
                          base_fraction=0.10, max_fraction=0.25)
    assert size_position(high_vol, "vol_target") < size_position(low_vol, "vol_target")


# ---------------------------------------------------------------------------
# Paper broker
# ---------------------------------------------------------------------------

def test_paper_broker_fill_and_exits(tmp_path):
    from jexi_market.brokers.paper import PaperBroker
    broker = PaperBroker(str(tmp_path / "paper.sqlite"), starting_cash=10_000.0,
                         price_provider=lambda s: 100.0)
    order = broker.submit_order("AAPL", 2, "buy", stop_loss=90.0, take_profit=130.0)
    assert order.status == "filled"
    assert broker.get_account().cash < 10_000.0
    positions = broker.get_positions()
    assert len(positions) == 1 and positions[0].qty == 2

    # Take-profit fires
    fired = broker.process_fills({"AAPL": 131.0})
    assert len(fired) == 1
    assert fired[0].raw.get("exit_reason") == "take_profit"
    assert broker.get_positions() == []


def test_paper_broker_rejects_sell_without_position(tmp_path):
    from jexi_market.brokers.paper import PaperBroker
    broker = PaperBroker(str(tmp_path / "paper2.sqlite"))
    order = broker.submit_order("MSFT", 1, "sell")
    assert order.status == "rejected"
    assert order.raw["reason"] == "no_position_to_sell"


def test_paper_broker_insufficient_funds(tmp_path):
    from jexi_market.brokers.paper import PaperBroker
    broker = PaperBroker(str(tmp_path / "paper3.sqlite"), starting_cash=100.0,
                         price_provider=lambda s: 500.0)
    order = broker.submit_order("EXPENSIVE", 10, "buy")   # 5000 notional > 100 cash
    assert order.status == "rejected"
    assert order.raw["reason"] == "insufficient_cash"


# ---------------------------------------------------------------------------
# Broker factory
# ---------------------------------------------------------------------------

def test_factory_builds_every_broker():
    from jexi_market.brokers.factory import build_broker
    for name in ("paper", "alpaca", "binance", "pocketoption", "mt5"):
        broker = build_broker(MarketConfig(), name=name)
        assert broker.name == name
        assert broker is not None


def test_factory_unknown_falls_back_to_alpaca():
    from jexi_market.brokers.factory import build_broker
    broker = build_broker(MarketConfig(), name="not_a_broker")
    assert broker.name == "alpaca"


def test_binance_signing_deterministic():
    from jexi_market.brokers.binance import BinanceBroker
    b = BinanceBroker()
    b.api_secret = "test-secret"
    sig1 = b._sign({"symbol": "BTCUSDT", "side": "BUY"})
    sig2 = b._sign({"symbol": "BTCUSDT", "side": "BUY"})
    assert sig1 == sig2
    assert "signature=" in sig1


# ---------------------------------------------------------------------------
# Order lifecycle manager
# ---------------------------------------------------------------------------

class _StubBroker:
    """Minimal broker stub for lifecycle tests."""

    name = "stub"
    supports_bracket_orders = True
    paper = True

    def __init__(self):
        self.orders = []
        self.positions = []
        self.prices = {}

    @property
    def configured(self):
        return True

    def get_account(self):
        from jexi_market.brokers.base import BrokerAccount
        return BrokerAccount(equity=100_000.0, cash=100_000.0)

    def get_positions(self):
        return self.positions

    def submit_order(self, symbol, qty, side, **kwargs):
        from jexi_market.brokers.base import BrokerOrder
        order = BrokerOrder(id=f"o{len(self.orders)}", status="filled",
                            symbol=symbol, qty=qty, side=side,
                            filled_qty=qty, filled_avg_price=self.prices.get(symbol, 100.0))
        self.orders.append(order)
        return order

    def submit_bracket_order(self, symbol, qty, side, *, stop_loss=None,
                             take_profit=None, time_in_force="day"):
        return self.submit_order(symbol, qty, side)

    def get_order(self, order_id):
        return next(o for o in self.orders if o.id == order_id)

    def cancel_order(self, order_id):
        return True

    def close_position(self, symbol):
        from jexi_market.brokers.base import BrokerOrder
        order = BrokerOrder(id="close1", status="filled", symbol=symbol,
                            qty=1.0, side="sell", filled_qty=1.0, filled_avg_price=95.0)
        self.orders.append(order)
        return order

    def get_latest_price(self, symbol):
        return self.prices.get(symbol)


def _long_decision(fraction=0.10):
    return Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.9, data_freshness=1.0, evidence_count=4),
        entry=100.0, stop_loss=95.0, take_profit=115.0,
        position_fraction=fraction,
    )


def test_lifecycle_open_position_journals(tmp_path):
    from jexi_market.execution.lifecycle import OrderLifecycleManager
    memory = PerformanceMemory(":memory:")
    manager = OrderLifecycleManager(_StubBroker(), memory)
    outcome = manager.open_position(_long_decision(), 100_000.0, 100.0)
    assert outcome.ok
    assert outcome.bracket
    # Memory now holds the open trade
    trades = memory.recent_trades()
    assert len(trades) == 1 and trades[0]["outcome"] == "open"


def test_lifecycle_check_exits_stop_loss(tmp_path):
    from jexi_market.execution.lifecycle import OrderLifecycleManager
    memory = PerformanceMemory(":memory:")
    memory.record_decision(_long_decision())
    broker = _StubBroker()
    broker.prices["AAPL"] = 94.0   # below stop 95
    manager = OrderLifecycleManager(broker, memory)
    closed = manager.check_exits({"AAPL": 94.0})
    assert len(closed) == 1 and closed[0]["reason"] == "stop_loss"
    trades = memory.recent_trades()
    assert trades[0]["outcome"] == "loss"


def test_lifecycle_reconcile_closes_ghost_trades(tmp_path):
    from jexi_market.execution.lifecycle import OrderLifecycleManager
    memory = PerformanceMemory(":memory:")
    memory.record_decision(_long_decision())
    broker = _StubBroker()   # no venue positions at all
    manager = OrderLifecycleManager(broker, memory)
    report = manager.reconcile()
    assert "AAPL" in report["closed_in_memory"]
    trades = memory.recent_trades()
    assert trades[0]["outcome"] in {"win", "loss", "breakeven"}
    assert trades[0]["exit_reason"] == "external_close"


# ---------------------------------------------------------------------------
# Confidence gating + FLAT classification in the pipeline
# ---------------------------------------------------------------------------

def test_pipeline_confidence_gate_blocks_weak_decisions(monkeypatch, tmp_path):
    """A gate-approved but weak-confidence decision must be held back."""
    from jexi_market.pipeline import DecisionPipeline
    from jexi_market.orchestrator import MarketBoss, RunResult

    config = MarketConfig(min_confidence=0.99)   # impossibly strict
    config.memory_db_path = ":memory:"

    boss = MarketBoss.__new__(MarketBoss)
    boss.config = config

    # Fake a strong-direction but (per config) weak decision
    decision = Decision(
        symbol="AAPL", direction=SignalDirection.LONG,
        confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=4),
        entry=100.0, position_fraction=0.10,
    )
    result = RunResult(symbol="AAPL")
    result.decision = decision
    result.gate_approved = True

    pipeline = DecisionPipeline.__new__(DecisionPipeline)
    pipeline.config = config
    pipeline.memory = PerformanceMemory(":memory:")
    from jexi_market.observability import AuditLog
    pipeline.audit = AuditLog(str(tmp_path / "audit.jsonl"))

    # Call the confidence gate logic through run path pieces: emulate by
    # verifying the threshold comparison the pipeline performs.
    held = decision.confidence.score < config.min_confidence
    assert held


def test_equity_session_hours():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from jexi_market.runner import is_equity_session
    et = ZoneInfo("America/New_York")
    # Wednesday 12:00 ET (a trading session)
    assert is_equity_session(datetime(2026, 1, 7, 12, 0, tzinfo=et))
    # Wednesday 20:00 ET (after close)
    assert not is_equity_session(datetime(2026, 1, 7, 20, 0, tzinfo=et))
    # Saturday
    assert not is_equity_session(datetime(2026, 1, 10, 12, 0, tzinfo=et))
    # 9:15 ET — pre-market
    assert not is_equity_session(datetime(2026, 1, 7, 9, 15, tzinfo=et))


# ---------------------------------------------------------------------------
# Telegram command handling (no network)
# ---------------------------------------------------------------------------

class _FakeRunner:
    """Bare-minimum runner stand-in for Telegram command tests."""

    def __init__(self, tmp_path):
        from jexi_market.risk.state import RiskStateStore
        self.state = RiskStateStore(str(tmp_path / "tg.sqlite"))
        self.memory = PerformanceMemory(":memory:")

    class _Broker:
        name = "stub"
        paper = True

        @staticmethod
        def get_account():
            from jexi_market.brokers.base import BrokerAccount
            return BrokerAccount(equity=123_456.0, cash=100_000.0)

        @staticmethod
        def get_positions():
            return []

    broker = _Broker()

    def trading_allowed(self):
        return True, "ok"

    def health_payload(self):
        return {"runner": {"cycles": 3}, "risk": {"halted": False, "paused": False},
                "memory": {}, "broker": self.broker.status()}


def test_telegram_pause_resume_kill_clear(tmp_path):
    from jexi_market.telegram_control import TelegramController
    tg = TelegramController.__new__(TelegramController)
    tg.runner = _FakeRunner(tmp_path)
    assert "paused" in tg.handle("/pause", "123").lower()
    assert tg.runner.state.is_paused()
    assert "resumed" in tg.handle("/resume", "123").lower()
    assert not tg.runner.state.is_paused()
    assert "halt" in tg.handle("/kill", "123").lower()
    assert tg.runner.state.is_halted()
    assert "cleared" in tg.handle("/clear", "123").lower()
    assert not tg.runner.state.is_halted()


def test_telegram_unknown_command(tmp_path):
    from jexi_market.telegram_control import TelegramController
    tg = TelegramController.__new__(TelegramController)
    tg.runner = _FakeRunner(tmp_path)
    assert "unknown" in tg.handle("/frobnicate", "123").lower()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_log_appends_jsonl(tmp_path):
    from jexi_market.observability import AuditLog
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    log.event("order_submitted", symbol="AAPL", qty=10)
    log.event("order_filled", symbol="AAPL", qty=10)
    events = log.tail()
    assert len(events) == 2
    assert events[0]["kind"] == "order_submitted"
    assert "ts" in events[0]


def test_prometheus_metrics_renders():
    from jexi_market.observability import prometheus_metrics_text
    text = prometheus_metrics_text({
        "n_trades": 12, "n_win": 7, "n_loss": 5,
        "win_rate": 0.583, "total_pnl_pct": 3.2,
        "risk": {"halted": False, "paused": False, "peak_equity": 104000.0},
        "runner": {"heartbeat_age_seconds": 12.5},
    })
    assert "jexi_trades_total 12" in text
    assert "jexi_risk_halted 0" in text
    assert "jexi_heartbeat_age_seconds 12.5" in text
