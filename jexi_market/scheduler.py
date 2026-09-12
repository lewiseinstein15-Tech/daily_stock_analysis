# -*- coding: utf-8 -*-
"""Autonomous scheduler for JEXI Market.

Runs the decision pipeline on a schedule, with no human interaction.
This is the spec's section 30 ("Autonomous Operation"): JEXI Market
must be capable of operating continuously, not only when a human types
a question.

Supported jobs:
  * ``scan``         — every N minutes, scan a universe for candidates
  * ``analyze``      — every N minutes, run the full pipeline on top
                       candidates from the scan
  * ``monitor``      — every N minutes, check open positions and close
                       any that hit stop / take-profit / max-holding
  * ``daily_summary`` — once a day, push a summary report

The scheduler is a thin wrapper around Python's ``time.sleep`` so it
has no external dependencies.  For production use, swap in APScheduler
or Celery — the job functions themselves are decoupled from the runner.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from jexi_market.config import MarketConfig
from jexi_market.memory import PerformanceMemory
from jexi_market.orchestrator import MarketBoss
from jexi_market.pipeline import DecisionPipeline

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    job_name: str
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    success: bool = False
    summary: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success": self.success,
            "summary": self.summary,
            "error": self.error,
            "elapsed_seconds": (
                round(self.finished_at - self.started_at, 2)
                if self.finished_at else None
            ),
        }


class AutonomousScheduler:
    """Runs jobs on a schedule.  No external deps; uses ``time.sleep``.

    Construct with a :class:`DecisionPipeline` (or build one from
    :class:`MarketConfig`), then call :meth:`run_forever` or
    :meth:`run_once` for each job.
    """

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        pipeline: Optional[DecisionPipeline] = None,
        boss: Optional[MarketBoss] = None,
        memory: Optional[PerformanceMemory] = None,
    ):
        self.config = config or MarketConfig()
        self.boss = boss or MarketBoss(self.config)
        self.pipeline = pipeline or DecisionPipeline(self.config, boss=self.boss)
        self.memory = memory or self.boss.memory
        self._running = False
        self._stop_requested = False

    def request_stop(self) -> None:
        """Polite stop — finishes the current job, then exits."""
        self._stop_requested = True

    # ------------------------------------------------------------------
    # Individual jobs
    # ------------------------------------------------------------------
    def job_scan(self, *, max_candidates: int = 5) -> JobResult:
        """Scan a universe for trade candidates."""
        result = JobResult(job_name="scan")
        try:
            from jexi_market.scanner import MarketScanner
            scanner = MarketScanner()
            universe = self.config.scanner_symbols
            candidates = scanner.scan(universe, days=self.config.scanner_lookback_days)
            result.success = True
            result.summary = {
                "n_universe": len(universe),
                "n_candidates": len(candidates),
                "top_candidates": [
                    {"symbol": c.symbol, "score": round(c.score, 3), "triggers": c.triggered}
                    for c in candidates[:max_candidates]
                ],
            }
        except Exception as exc:
            result.error = str(exc)
            logger.exception("scan job failed")
        result.finished_at = time.time()
        return result

    def job_analyze(self, *, max_candidates: int = 3, execute_paper: bool = False) -> JobResult:
        """Run the full pipeline: scan -> analyze -> paper-trade."""
        result = JobResult(job_name="analyze")
        try:
            run = self.pipeline.run_full(
                max_candidates=max_candidates,
                days=self.config.scanner_lookback_days,
                execute_paper=execute_paper,
            )
            result.success = True
            result.summary = run.summary
            result.summary["n_paper_orders"] = len(run.paper_orders)
            result.summary["n_rejected"] = len(run.rejected)
        except Exception as exc:
            result.error = str(exc)
            logger.exception("analyze job failed")
        result.finished_at = time.time()
        return result

    def job_monitor(self) -> JobResult:
        """Check open positions and close any that hit risk limits.

        v0.3 fix: this job previously only *counted* open trades and
        never closed anything — the documented stop/TP/max-holding
        monitoring was a no-op, so the memory/learning loop never
        advanced during autonomous runs.  It now runs the
        :class:`SelfEvaluationLoop` (same exit rules as the backtester)
        on every invocation, then reports real venue positions when a
        broker is configured.
        """
        result = JobResult(job_name="monitor")
        try:
            recent = self.memory.recent_trades(limit=50)
            open_trades = [t for t in recent if t.get("outcome") == "open"]
            result.summary = {
                "n_open_trades": len(open_trades),
                "symbols": [t.get("symbol") for t in open_trades],
            }
            # Actually evaluate exits: close stop/TP/max-holding trades
            # against the latest prices and update agent weights.
            try:
                from jexi_market.self_eval import SelfEvaluationLoop
                loop = SelfEvaluationLoop(
                    self.config,
                    self.memory,
                    data_client=self.boss.data_client,
                )
                closed = loop.evaluate_open_trades()
                result.summary["closed_trades"] = len(closed)
                result.summary["closed_symbols"] = [
                    {"symbol": c.symbol, "reason": c.exit_reason, "pnl_pct": round(c.pnl_pct, 4)}
                    for c in closed
                ]
            except Exception as exc:
                result.summary["self_eval_error"] = str(exc)
                logger.warning("self-eval inside monitor failed: %s", exc)
            # If Alpaca is configured, pull real positions
            if self.boss.alpaca.configured:
                try:
                    positions = self.boss.alpaca.get_positions()
                    result.summary["alpaca_positions"] = len(positions)
                    result.summary["alpaca_pnl"] = round(
                        sum(p.unrealized_pl for p in positions), 2
                    )
                except Exception as exc:
                    result.summary["alpaca_error"] = str(exc)
            result.success = True
        except Exception as exc:
            result.error = str(exc)
            logger.exception("monitor job failed")
        result.finished_at = time.time()
        return result

    def job_daily_summary(self) -> JobResult:
        """Push a daily summary report to ntfy."""
        result = JobResult(job_name="daily_summary")
        try:
            stats = self.memory.stats_summary()
            agent_stats = self.memory.agent_stats()
            paper_days = self.memory.paper_trading_days()

            title = f"JEXI Market — Daily Summary ({paper_days} paper days)"
            body_lines = [
                "JEXI MARKET — DAILY SUMMARY",
                "=" * 35,
                f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                f"Paper-trading days: {paper_days}",
                "",
                "Performance:",
                f"  Total trades: {stats.get('n_trades', 0)}",
                f"  Win rate:    {stats.get('win_rate', 0):.1%}",
                f"  Avg PnL:     {stats.get('avg_pnl_pct', 0):+.2%}",
                f"  Total PnL:   {stats.get('total_pnl_pct', 0):+.2%}",
                "",
                "Agent Accuracy:",
            ]
            for agent_id, s in sorted(agent_stats.items(), key=lambda x: -x[1]["accuracy"]):
                body_lines.append(
                    f"  {agent_id:<20} {s['accuracy']:.0%} ({s['n_correct']}/{s['n_calls']})"
                )
            body_lines.append("=" * 35)
            body = "\n".join(body_lines)
            ok = self.boss.reporter.publish(title, body, priority="default", tags=["chart", "summary"])
            result.success = ok
            result.summary = {"published": ok, "stats": stats}
        except Exception as exc:
            result.error = str(exc)
            logger.exception("daily summary job failed")
        result.finished_at = time.time()
        return result

    # ------------------------------------------------------------------
    # Loop runner
    # ------------------------------------------------------------------
    def run_forever(
        self,
        *,
        scan_interval_seconds: int = 300,
        analyze_interval_seconds: int = 600,
        monitor_interval_seconds: int = 180,
        daily_summary_hour_utc: int = 22,
    ) -> None:
        """Run all jobs on their schedules until :meth:`request_stop` is called.

        Defaults: scan every 5 min, analyze every 10 min, monitor every
        3 min, daily summary at 22:00 UTC.  These are intentionally
        conservative — paper trading doesn't need HFT cadence.
        """
        self._running = True
        self._stop_requested = False
        last_scan = 0.0
        last_analyze = 0.0
        last_monitor = 0.0
        last_summary_date = None
        logger.info("autonomous scheduler started — Ctrl-C to stop")
        try:
            while not self._stop_requested:
                now = time.time()
                if now - last_scan >= scan_interval_seconds:
                    self.job_scan()
                    last_scan = now
                if now - last_analyze >= analyze_interval_seconds:
                    self.job_analyze()
                    last_analyze = now
                if now - last_monitor >= monitor_interval_seconds:
                    self.job_monitor()
                    last_monitor = now
                # Daily summary at the configured UTC hour
                current_date = datetime.now(timezone.utc).date()
                current_hour = datetime.now(timezone.utc).hour
                if (
                    current_hour >= daily_summary_hour_utc
                    and last_summary_date != current_date
                ):
                    self.job_daily_summary()
                    last_summary_date = current_date
                # Sleep 30s between checks — fine-grained enough for paper
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("scheduler stopped by user")
        finally:
            self._running = False
            logger.info("autonomous scheduler exited")

    def run_once(self, job: str, **kwargs) -> JobResult:
        """Run a single job by name.  Useful for cron / GitHub Actions."""
        if job == "scan":
            return self.job_scan(**kwargs)
        if job == "analyze":
            return self.job_analyze(**kwargs)
        if job == "monitor":
            return self.job_monitor(**kwargs)
        if job == "daily_summary":
            return self.job_daily_summary()
        raise ValueError(f"unknown job: {job!r} (expected scan/analyze/monitor/daily_summary)")
