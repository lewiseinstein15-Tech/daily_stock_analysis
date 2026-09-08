# -*- coding: utf-8 -*-
"""Tests for the dashboard (FastAPI)."""

from fastapi.testclient import TestClient

from jexi_market.config import MarketConfig
from jexi_market.dashboard import build_app
from jexi_market.memory import PerformanceMemory


def _build_test_app(tmp_path):
    config = MarketConfig()
    config.ntfy_url = ""
    memory = PerformanceMemory(str(tmp_path / "test.sqlite"))
    app = build_app(config, memory=memory)
    return app, memory


def test_health_endpoint(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "JEXI Market" in body["service"]


def test_overview_endpoint(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert "config" in body
    assert "memory_stats" in body
    assert "paper_trading_days" in body
    assert "n_agents" in body
    assert "n_strategies" in body
    assert body["system_halted"] is False
    # Alpaca not configured in tests
    assert body["alpaca_account"] is None


def test_agents_endpoint(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] >= 10
    agent_ids = [a["id"] for a in body["agents"]]
    for expected in ("technical", "fundamental", "quant", "macro", "news", "risk", "aldric", "vic"):
        assert expected in agent_ids


def test_strategies_endpoint(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/strategies")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] >= 8
    names = [s["name"] for s in body["strategies"]]
    for expected in ("trend_following", "momentum", "mean_reversion", "breakout", "factor_value", "event_driven", "statistical_arb", "volatility_breakout"):
        assert expected in names


def test_recent_trades_endpoint_empty(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/recent-trades")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 0
    assert body["trades"] == []


def test_agent_stats_endpoint(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/agent-stats")
    assert r.status_code == 200
    assert r.json() == {}


def test_scan_candidates_endpoint_initially_empty(tmp_path):
    app, _ = _build_test_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/scan-candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 0


def test_analyze_endpoint_with_synthetic_data(tmp_path, monkeypatch):
    app, memory = _build_test_app(tmp_path)
    client = TestClient(app)
    # Patch the boss's data client to return synthetic data
    from jexi_market.data import load_synthetic_frame, MarketSnapshot
    snap = MarketSnapshot(
        symbol="TEST", ok=True,
        df=load_synthetic_frame("TEST", days=120),
        provider="synthetic", rows=120, freshness_score=1.0,
    )
    # Disable enrichment to avoid network calls
    app.state.boss.enable_enrichment = False
    monkeypatch.setattr(app.state.boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)
    # POST with query parameters (FastAPI's signature-based routing)
    r = client.post("/api/analyze/TEST?days=120")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "TEST"
    assert body["error"] is None
    assert body["decision"] is not None
