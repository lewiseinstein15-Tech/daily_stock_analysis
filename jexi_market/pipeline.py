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
    ORDER (broker / paper)
    ↓
    MONITORING
    ↓
    POST-TRADE ANALYSIS

v0.3 changes:

* **Confidence gate**: decisions below ``JEXI_MIN_CONFIDENCE`` are never
  executed — the bot trades only when it is *sure*.  Held-back
  decisions are reported separately from rejections.
* **FLAT is not a rejection** (audit fix B14): clean FLAT decisions no
  longer corrupt the rejection audit trail.
* **Real execution**: orders go through
  :class:`~jexi_market.execution.lifecycle.OrderLifecycleManager`
  (bracket stop/TP, retries, fill verification, memory journaling) on
  the configured :class:`~jexi_market.brokers.base.Broker`, with the
  legacy Alpaca path kept as fallback.
* **Audit trail**: every gate decision / order / hold is appended to
  the JSONL audit log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker
from jexi_market.brokers.factory import build_broker
from jexi_market.config import MarketConfig
from jexi_market.contracts import Decision, SignalDirection
from jexi_market.data import MarketDataClient
from jexi_market.execution import AlpacaClient, Order
from jexi_market.execution.lifecycle import OrderLifecycleManager
from jexi_market.memory import PerformanceMemory
from jexi_market.observability import AuditLog
from jexi_market.orchestrator import MarketBoss, RunResult
from jexi_market.risk import PortfolioState, RiskGate
from jexi_market.risk.state import RiskStateStore
from jexi_market.scanner import MarketScanner, ScanCandidate

logger = logging.getLogger(__name__)


@dataclass
class PipelineRun:
    """Result of a full pipeline run."""

    scan_candidates: List[ScanCandidate] = field(default_factory=list)
    symbol_results: List[RunResult] = field(default_factory=list)
    paper_orders: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    held_back: List[Dict[str, Any]] = field(default_factory=list)   # low confidence
    no_action: List[Dict[str, Any]] = field(default_factory=list)   # clean FLAT
    elapsed_seconds: float = 0.0
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_candidates": [c.to_dict() for c in self.scan_candidates],
            "symbol_results": [r.to_dict() for r in self.symbol_results],
            "paper_orders": self.paper_orders,
            "rejected": self.rejected,
            "held_back": self.held_back,
            "no_action": self.no_action,
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
        broker: Optional[Broker] = None,
        lifecycle: Optional[OrderLifecycleManager] = None,
        state_store: Optional[RiskStateStore] = None,
        audit: Optional[AuditLog] = None,
    ):
        self.config = config or MarketConfig()
        self.boss = boss or MarketBoss(self.config, state_store=state_store)
        self.scanner = scanner or MarketScanner(MarketDataClient())
        self.alpaca = alpaca or AlpacaClient(self.config)
        self.memory = memory or self.boss.memory
        self.state_store = state_store or RiskStateStore(self.config.state_db_path)
        self.audit = audit or AuditLog(self.config.audit_log_path)
        self.broker = broker or build_broker(self.config)
        self.lifecycle = lifecycle or OrderLifecycleManager(self.broker, self.memory, self.audit)

    # ------------------------------------------------------------------
    # Full scan + analyze + execute pipeline
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

        ``execute_paper=True`` will actually submit orders via the
        configured broker when the whole gate chain approves.  The
        legacy Alpaca client is used when no broker is configured.
        """
        started = time.time()
        run = PipelineRun()

        # 1. SCAN
        universe = scan_universe or self.config.scanner_symbols
        run.scan_candidates = self.scanner.scan(universe, days=days)[:max_candidates]
        logger.info("scan: %d candidates from %d symbols", len(run.scan_candidates), len(universe))

        # 2-13. Per-candidate analysis + gating + execution
        for candidate in run.scan_candidates:
            result = self.boss.analyze_symbol(candidate.symbol, days=days)
            run.symbol_results.append(result)
            decision = result.decision

            # -- no decision -------------------------------------------
            if decision is None:
                run.rejected.append({
                    "symbol": candidate.symbol,
                    "direction": "none",
                    "violations": result.gate_violations,
                    "reason": "no decision",
                })
                self.audit.event("rejected", symbol=candidate.symbol, reason="no decision")
                continue

            # -- clean FLAT is a no-action, NOT a rejection (B14 fix) ---
            if decision.direction == SignalDirection.FLAT:
                run.no_action.append({
                    "symbol": candidate.symbol,
                    "reason": "FLAT consensus",
                })
                continue

            # -- gate rejected -------------------------------------------
            if not result.gate_approved:
                run.rejected.append({
                    "symbol": candidate.symbol,
                    "direction": decision.direction.value,
                    "violations": result.gate_violations,
                    "reason": "risk gate rejected",
                })
                self.audit.event("rejected", symbol=candidate.symbol,
                                 reason="risk gate",
                                 violations=result.gate_violations)
                continue

            # -- confidence gate (trade only when sure) -----------------
            conf = decision.confidence.score
            if conf < self.config.min_confidence:
                run.held_back.append({
                    "symbol": candidate.symbol,
                    "direction": decision.direction.value,
                    "confidence": round(conf, 4),
                    "threshold": self.config.min_confidence,
                    "reason": "below min confidence",
                })
                self.audit.event("held_back", symbol=candidate.symbol,
                                 confidence=conf, threshold=self.config.min_confidence)
                continue

            # -- execution -----------------------------------------------
            if execute_paper:
                order_dict = self._execute_order(decision, result)
                if order_dict:
                    run.paper_orders.append(order_dict)
            else:
                run.paper_orders.append({
                    "symbol": decision.symbol,
                    "direction": decision.direction.value,
                    "position_fraction": decision.position_fraction,
                    "entry": decision.entry,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "confidence": round(conf, 4),
                    "status": "simulated (execute_paper=False)",
                })

        # 14. Summary
        run.summary = {
            "n_scanned": len(universe),
            "n_candidates": len(run.scan_candidates),
            "n_approved": len(run.paper_orders),
            "n_rejected": len(run.rejected),
            "n_held_back": len(run.held_back),
            "n_no_action": len(run.no_action),
            "min_confidence": self.config.min_confidence,
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
    # Order execution (v0.3: lifecycle manager + broker abstraction)
    # ------------------------------------------------------------------
    def _execute_order(self, decision: Decision, run_result: RunResult) -> Optional[Dict[str, Any]]:
        """Execute via the broker through the lifecycle manager."""
        try:
            account = self.broker.get_account()
            equity = account.equity if account.equity > 0 else 100_000.0
            latest_price = decision.entry
            if not latest_price:
                snap = self.boss.data_client.get_daily(decision.symbol, days=5)
                latest_price = snap.latest_price if snap.ok else None
            if not latest_price:
                logger.warning("cannot size order for %s — no latest price", decision.symbol)
                return None

            outcome = self.lifecycle.open_position(
                decision, equity, latest_price,
                paper_mode=self.broker.paper,
            )
            return {
                "symbol": decision.symbol,
                "direction": decision.direction.value,
                "order_id": outcome.order_id,
                "status": "filled" if outcome.ok else "failed",
                "filled_qty": outcome.filled_qty,
                "filled_price": outcome.filled_price,
                "bracket": outcome.bracket,
                "error": outcome.error,
                "qty_notional": round(equity * decision.position_fraction, 2),
                "entry": decision.entry,
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
                "position_fraction": decision.position_fraction,
                "confidence": round(decision.confidence.score, 4),
                "broker": self.broker.name,
            }
        except Exception as exc:
            logger.error("order failed for %s: %s", decision.symbol, exc)
            self.audit.event("order_failed", symbol=decision.symbol, error=str(exc))
            return {
                "symbol": decision.symbol,
                "error": str(exc),
                "status": "failed",
            }
