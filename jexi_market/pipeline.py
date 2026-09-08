# -*- coding: utf-8 -*-
"""Decision pipeline for JEXI Market.

The pipeline is the *full* end-to-end flow described in spec section 20:

    MARKET SCANNER
    ↓
    DATA VALIDATION
    ↓
    FUNDAMENTAL ANALYSIS
    ↓
    TECHNICAL ANALYSIS
    ↓
    QUANT ANALYSIS
    ↓
    MACRO ANALYSIS
    ↓
    NEWS/SENTIMENT
    ↓
    RISK ANALYSIS
    ↓
    PROF. ALDRIC REVIEW
    ↓
    JEXI MARKET BOSS DECISION
    ↓
    VIC EXECUTION PLAN
    ↓
    RISK GATE
    ↓
    PAPER ORDER
    ↓
    MONITORING
    ↓
    POST-TRADE ANALYSIS

The :class:`MarketBoss` orchestrates steps 3-12; this module adds the
*outer* loop: scan -> analyze candidates -> optionally paper-trade ->
monitor -> close -> record outcome.

No single AI response directly creates an unrestricted trade.  Every
paper order goes through the risk gate; every closed trade is recorded
in the performance memory so the orchestrator can learn.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.config import MarketConfig
from jexi_market.contracts import Decision, SignalDirection
from jexi_market.data import MarketDataClient
from jexi_market.execution import AlpacaClient, Order
from jexi_market.memory import PerformanceMemory
from jexi_market.orchestrator import MarketBoss, RunResult
from jexi_market.risk import PortfolioState, RiskGate
from jexi_market.scanner import MarketScanner, ScanCandidate

logger = logging.getLogger(__name__)


@dataclass
class PipelineRun:
    """Result of a full pipeline run."""

    scan_candidates: List[ScanCandidate] = field(default_factory=list)
    symbol_results: List[RunResult] = field(default_factory=list)
    paper_orders: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_candidates": [c.to_dict() for c in self.scan_candidates],
            "symbol_results": [r.to_dict() for r in self.symbol_results],
            "paper_orders": self.paper_orders,
            "rejected": self.rejected,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "summary": self.summary,
        }


class DecisionPipeline:
    """Full end-to-end decision pipeline."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        boss: Optional[MarketBoss] = None,
        scanner: Optional[MarketScanner] = None,
        alpaca: Optional[AlpacaClient] = None,
        memory: Optional[PerformanceMemory] = None,
    ):
        self.config = config or MarketConfig()
        self.boss = boss or MarketBoss(self.config)
        self.scanner = scanner or MarketScanner(MarketDataClient())
        self.alpaca = alpaca or AlpacaClient(self.config)
        self.memory = memory or self.boss.memory

    # ------------------------------------------------------------------
    # Full scan + analyze + paper-trade pipeline
    # ------------------------------------------------------------------
    def run_full(
        self,
        *,
        scan_universe: Optional[List[str]] = None,
        days: int = 120,
        max_candidates: int = 5,
        execute_paper: bool = False,
    ) -> PipelineRun:
        """Run the full pipeline.

        ``execute_paper=True`` will actually submit paper orders via the
        Alpaca client when configured.  When Alpaca is not configured or
        ``execute_paper=False``, the pipeline stops at the decision +
        gate step and logs the would-be order.
        """
        started = time.time()
        run = PipelineRun()

        # 1. SCAN
        universe = scan_universe or self.config.scanner_symbols
        run.scan_candidates = self.scanner.scan(universe, days=days)[:max_candidates]
        logger.info("scan: %d candidates from %d symbols", len(run.scan_candidates), len(universe))

        # 2-12. Per-candidate: analyze (which itself runs the multi-agent
        # flow, Aldric review, decision synthesis, Vic plan, risk gate).
        for candidate in run.scan_candidates:
            result = self.boss.analyze_symbol(candidate.symbol, days=days)
            run.symbol_results.append(result)

            # 13. Paper order (if approved + execution enabled)
            if result.gate_approved and result.decision and result.decision.direction != SignalDirection.FLAT:
                if execute_paper and self.alpaca.configured:
                    order_dict = self._execute_paper_order(result.decision, result)
                    if order_dict:
                        run.paper_orders.append(order_dict)
                else:
                    run.paper_orders.append({
                        "symbol": result.decision.symbol,
                        "direction": result.decision.direction.value,
                        "position_fraction": result.decision.position_fraction,
                        "entry": result.decision.entry,
                        "stop_loss": result.decision.stop_loss,
                        "take_profit": result.decision.take_profit,
                        "status": "paper_simulated (Alpaca not configured or execute_paper=False)",
                    })
            else:
                run.rejected.append({
                    "symbol": candidate.symbol,
                    "direction": result.decision.direction.value if result.decision else "none",
                    "violations": result.gate_violations,
                    "reason": "risk gate rejected" if result.decision else "no decision",
                })

        # 14. Summary
        run.summary = {
            "n_scanned": len(universe),
            "n_candidates": len(run.scan_candidates),
            "n_approved": len(run.paper_orders),
            "n_rejected": len(run.rejected),
            "memory_stats": self.memory.stats_summary(),
            "agent_stats": self.memory.agent_stats(),
        }
        run.elapsed_seconds = time.time() - started
        return run

    # ------------------------------------------------------------------
    # Single-symbol convenience
    # ------------------------------------------------------------------
    def analyze_one(self, symbol: str, *, days: int = 120) -> RunResult:
        return self.boss.analyze_symbol(symbol, days=days)

    # ------------------------------------------------------------------
    # Paper order execution
    # ------------------------------------------------------------------
    def _execute_paper_order(self, decision: Decision, run_result: RunResult) -> Optional[Dict[str, Any]]:
        """Submit a paper order via Alpaca (if configured)."""
        try:
            account = self.alpaca.get_account()
            equity = account.equity if account.equity > 0 else 100_000.0
            latest_price = decision.entry
            if not latest_price:
                snap = self.boss.data_client.get_daily(decision.symbol, days=5)
                latest_price = snap.latest_price if snap.ok else None
            if not latest_price:
                logger.warning("cannot size order for %s — no latest price", decision.symbol)
                return None
            order = self.alpaca.execute_decision(decision, equity, latest_price=latest_price)
            return {
                "symbol": decision.symbol,
                "direction": decision.direction.value,
                "order_id": order.id,
                "status": order.status,
                "qty": order.qty,
                "side": order.side,
                "type": order.type,
                "entry": decision.entry,
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
                "position_fraction": decision.position_fraction,
            }
        except Exception as exc:
            logger.error("paper order failed for %s: %s", decision.symbol, exc)
            return {
                "symbol": decision.symbol,
                "error": str(exc),
                "status": "failed",
            }
