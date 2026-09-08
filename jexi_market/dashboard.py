# -*- coding: utf-8 -*-
"""FastAPI dashboard for JEXI Market.

A lightweight HTTP dashboard that exposes REAL system state — no
fabricated numbers.  When the orchestrator hasn't run, the endpoints
return empty lists / "unavailable" rather than mock data.

This is the spec's section 25 ("Dashboard"): the interface should
expose real system state.  It does NOT replace the CLI — it's a
read-only view that consumes the same orchestrator + memory.

Endpoints:
  GET /                          — health
  GET /api/overview               — portfolio + system state
  GET /api/agents                 — agent roster + performance
  GET /api/strategies             — strategy registry
  GET /api/recent-trades          — last N paper trades from memory
  GET /api/agent-stats            — agent accuracy / adaptive weights
  POST /api/analyze/{symbol}      — trigger an analysis (sync)
  POST /api/scan                  — trigger a scan (sync)
  GET /api/scan-candidates        — last scan results (in-memory)

The dashboard never exposes Alpaca credentials.  It only reports
``alpaca_configured: True/False`` and the (non-sensitive) account
summary when available.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from jexi_market.agents import list_agent_ids
from jexi_market.config import MarketConfig
from jexi_market.memory import PerformanceMemory
from jexi_market.orchestrator import MarketBoss
from jexi_market.strategies import all_strategies, list_strategies

logger = logging.getLogger(__name__)


def build_app(
    config: Optional[MarketConfig] = None,
    *,
    boss: Optional[MarketBoss] = None,
    memory: Optional[PerformanceMemory] = None,
) -> FastAPI:
    """Build the FastAPI dashboard app.

    Constructed with shared ``boss`` and ``memory`` instances so the
    dashboard reflects real state.  All endpoints are read-only except
    the explicit POST triggers.
    """
    config = config or MarketConfig()
    app = FastAPI(
        title="JEXI Market Dashboard",
        description="Autonomous multi-agent market intelligence & paper-trading system",
        version="0.1.0",
    )
    # State — single shared boss/memory per app instance.
    app.state.config = config
    app.state.boss = boss or MarketBoss(config)
    app.state.memory = memory or app.state.boss.memory
    app.state.last_scan: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------
    class AnalyzeRequest(BaseModel):
        days: int = 120

    class ScanRequest(BaseModel):
        universe: Optional[List[str]] = None
        days: int = 120
        max_results: int = 20

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    @app.get("/")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "JEXI Market Dashboard",
            "version": "0.1.0",
        }

    @app.get("/api/overview")
    def overview() -> Dict[str, Any]:
        cfg: MarketConfig = app.state.config
        mem: PerformanceMemory = app.state.memory
        summary = cfg.summary()
        stats = mem.stats_summary()
        paper_days = mem.paper_trading_days()
        # If Alpaca is configured, include account info (no secrets)
        alpaca_account: Optional[Dict[str, Any]] = None
        if app.state.boss.alpaca.configured:
            try:
                acct = app.state.boss.alpaca.get_account()
                alpaca_account = acct.to_dict()
            except Exception as exc:
                alpaca_account = {"error": str(exc)}
        return {
            "config": summary,
            "memory_stats": stats,
            "paper_trading_days": paper_days,
            "n_agents": len(list_agent_ids()),
            "n_strategies": len(list_strategies()),
            "alpaca_account": alpaca_account,
            "system_halted": app.state.boss.risk_gate.halted,
            "halt_reason": app.state.boss.risk_gate.halt_reason,
        }

    @app.get("/api/agents")
    def agents() -> Dict[str, Any]:
        from jexi_market.agents import build_all_agents
        all_agents = build_all_agents()
        agent_stats = app.state.memory.agent_stats()
        roster = []
        for agent_id in list_agent_ids():
            agent = all_agents.get(agent_id)
            if agent is None:
                continue
            stats = agent_stats.get(agent_id, {})
            roster.append({
                "id": agent.id,
                "name": agent.name,
                "kind": agent.kind.value,
                "n_calls": stats.get("n_calls", 0),
                "accuracy": round(stats.get("accuracy", 0.0), 4),
                "adaptive_weight": round(app.state.memory.agent_weight(agent_id), 4),
                "total_pnl": round(stats.get("total_pnl", 0.0), 4),
            })
        return {"agents": roster, "n": len(roster)}

    @app.get("/api/strategies")
    def strategies() -> Dict[str, Any]:
        out = []
        for name, strat in all_strategies().items():
            out.append({
                "name": strat.name,
                "description": strat.description,
                "regime": strat.regime,
                "benchmark": strat.benchmark,
                "validation_status": strat.validation_status,
            })
        return {"strategies": out, "n": len(out)}

    @app.get("/api/recent-trades")
    def recent_trades(limit: int = 20) -> Dict[str, Any]:
        rows = app.state.memory.recent_trades(limit=limit)
        return {"trades": rows, "n": len(rows)}

    @app.get("/api/agent-stats")
    def agent_stats() -> Dict[str, Any]:
        return app.state.memory.agent_stats()

    @app.get("/api/scan-candidates")
    def scan_candidates() -> Dict[str, Any]:
        return {"candidates": app.state.last_scan, "n": len(app.state.last_scan)}

    @app.post("/api/analyze/{symbol}")
    def analyze(symbol: str, days: int = 120) -> Dict[str, Any]:
        boss: MarketBoss = app.state.boss
        result = boss.analyze_symbol(symbol, days=days)
        return result.to_dict()

    @app.post("/api/scan")
    def scan(universe: Optional[List[str]] = None, days: int = 120, max_results: int = 20) -> Dict[str, Any]:
        from jexi_market.scanner import MarketScanner
        scanner = MarketScanner()
        symbols = universe or app.state.config.scanner_symbols
        candidates = scanner.scan(symbols, days=days)
        app.state.last_scan = [c.to_dict() for c in candidates[:max_results]]
        return {"candidates": app.state.last_scan, "n": len(app.state.last_scan)}

    return app


# Convenience: build the app at import time so `uvicorn jexi_market.dashboard:app` works.
app = build_app()
