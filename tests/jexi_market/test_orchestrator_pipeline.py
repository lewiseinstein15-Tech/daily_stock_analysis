# -*- coding: utf-8 -*-
"""Integration tests for the orchestrator + pipeline."""

import pandas as pd

from jexi_market.agents import AgentContext
from jexi_market.config import MarketConfig
from jexi_market.contracts import MarketRegime, SignalDirection
from jexi_market.data import MarketSnapshot, load_synthetic_frame
from jexi_market.indicators import compute_factors
from jexi_market.orchestrator import MarketBoss
from jexi_market.pipeline import DecisionPipeline
from jexi_market.agents.leadership import RegimeClassifier


def _make_synthetic_snapshot(symbol="SYNTH", rows=120, drift=0.002) -> MarketSnapshot:
    # NB: deterministic seed — hash() is salted per process and would make
    # the consensus direction (and hence memory row count) flaky.
    seed = sum(bytearray(symbol.encode("utf-8"))) % 1000
    df = load_synthetic_frame(symbol, days=rows, seed=seed)
    # Apply drift to closes
    df["close"] = df["close"] * (1.0 + drift * df.index)
    df["high"] = df["close"] * 1.01
    df["low"] = df["close"] * 0.99
    return MarketSnapshot(
        symbol=symbol, ok=True, df=df, provider="synthetic",
        rows=rows, freshness_score=1.0,
    )


def test_regime_classifier_bullish():
    """Closing prices rising strongly should classify as BULL."""
    closes = [100.0 + i * 0.5 for i in range(120)]  # strong uptrend
    regime, score, why = RegimeClassifier.classify(closes)
    assert regime == MarketRegime.BULL
    assert score > 0


def test_regime_classifier_bearish():
    closes = [200.0 - i * 0.7 for i in range(120)]  # strong downtrend
    regime, score, why = RegimeClassifier.classify(closes)
    assert regime == MarketRegime.BEAR
    assert score < 0


def test_regime_classifier_insufficient_data():
    closes = [100.0, 101.0]
    regime, score, why = RegimeClassifier.classify(closes)
    assert regime == MarketRegime.UNKNOWN


def test_boss_analyze_symbol_with_synthetic_data(monkeypatch):
    """Boss should produce a decision when given good synthetic data."""
    config = MarketConfig()
    config.ntfy_url = ""  # offline mode

    boss = MarketBoss(config)

    # Patch the data client to return our synthetic snapshot
    snap = _make_synthetic_snapshot("AAPL", rows=120, drift=0.003)
    monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

    result = boss.analyze_symbol("AAPL", days=120)
    assert result.error is None
    assert result.decision is not None
    assert result.regime != MarketRegime.UNKNOWN
    assert len(result.recommendations) > 0
    assert result.report_text  # non-empty


def test_boss_decision_has_evidence_and_agents(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    boss = MarketBoss(config)
    snap = _make_synthetic_snapshot("MSFT", rows=120, drift=0.004)
    monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

    result = boss.analyze_symbol("MSFT", days=120)
    decision = result.decision
    assert decision is not None
    # Every decision must carry evidence (spec section 19)
    assert len(decision.evidence) > 0
    # And agent attribution
    assert isinstance(decision.supporting_agents, tuple)
    assert isinstance(decision.opposing_agents, tuple)


def test_boss_handles_failed_data_fetch(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    boss = MarketBoss(config)
    failed_snap = MarketSnapshot(symbol="FAIL", ok=False, error="network down")
    monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: failed_snap)

    result = boss.analyze_symbol("FAIL", days=120)
    assert result.error is not None
    assert "network down" in result.error or "data fetch failed" in result.error
    assert result.decision is None


def test_pipeline_run_full_with_synthetic_data(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    pipeline = DecisionPipeline(config)

    # Patch the scanner + boss data client to use synthetic data
    from jexi_market.scanner import ScanCandidate
    candidates = [
        ScanCandidate(symbol="AAA", score=0.5, triggered=["momentum"]),
        ScanCandidate(symbol="BBB", score=0.4, triggered=["unusual_volume"]),
    ]
    monkeypatch.setattr(pipeline.scanner, "scan", lambda universe, days=120: candidates)

    # Patch boss data client to return synthetic data
    for sym in ["AAA", "BBB"]:
        snap = _make_synthetic_snapshot(sym, rows=120, drift=0.003)
        # Need to monkeypatch per-symbol — use a wrapper
    def fake_get_daily(symbol, days=120, **kw):
        return _make_synthetic_snapshot(symbol, rows=120, drift=0.003)
    monkeypatch.setattr(pipeline.boss.data_client, "get_daily", fake_get_daily)

    run = pipeline.run_full(max_candidates=5, days=120, execute_paper=False)
    assert run.elapsed_seconds > 0
    assert len(run.symbol_results) == 2
    assert "n_candidates" in run.summary
    assert run.summary["n_candidates"] == 2


def test_pipeline_rejected_candidates_recorded(monkeypatch):
    """When the risk gate rejects, the candidate goes into `rejected`."""
    config = MarketConfig()
    config.ntfy_url = ""
    pipeline = DecisionPipeline(config)

    # Force the risk gate to halt so everything is rejected
    pipeline.boss.risk_gate.halt("test halt")

    from jexi_market.scanner import ScanCandidate
    candidates = [ScanCandidate(symbol="REJ", score=0.5, triggered=["test"])]
    monkeypatch.setattr(pipeline.scanner, "scan", lambda universe, days=120: candidates)

    def fake_get_daily(symbol, days=120, **kw):
        return _make_synthetic_snapshot(symbol, rows=120, drift=0.003)
    monkeypatch.setattr(pipeline.boss.data_client, "get_daily", fake_get_daily)

    run = pipeline.run_full(max_candidates=5, days=120, execute_paper=False)
    assert len(run.rejected) == 1
    assert run.rejected[0]["symbol"] == "REJ"


def test_boss_records_decision_in_memory(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    boss = MarketBoss(config)
    snap = _make_synthetic_snapshot("MEM", rows=120, drift=0.003)
    monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

    result = boss.analyze_symbol("MEM", days=120)
    # Memory should now have one open trade
    recent = boss.memory.recent_trades(limit=5)
    assert len(recent) == 1
    assert recent[0]["symbol"] == "MEM"
