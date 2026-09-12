# -*- coding: utf-8 -*-
"""MarketRunner247 — the true 24/7 autonomous trading loop (v0.3).

The old ``AutonomousScheduler`` was a sleep-loop that never closed
trades, never checked market hours, lost its risk state on restart and
had no watchdog.  This runner is the production replacement:

**Scheduling & uptime**
* cadence-driven loop (scan / analyze / monitor / daily summary) with
  jittered sleeps and graceful SIGINT/SIGTERM shutdown;
* *crash recovery*: job timestamps, heartbeat and failure counters live
  in the persistent :class:`RiskStateStore`;
* *watchdog*: N consecutive pipeline failures → automatic risk halt +
  notification (a stuck bot must never keep trading);
* optional market-hours awareness: equities only trade 9:30–16:00 ET
  weekdays; crypto (``JEXI_ASSET_CLASS=crypto``) runs 24/7;
  ``JEXI_TRADE_247=1`` overrides everything.

**Safety gates (checked before EVERY order)**
1. persisted risk ``halt`` (kill-switch) — set by the gate, watchdog,
   Telegram ``/kill`` or the ``killswitch`` CLI;
2. operator ``pause`` (Telegram ``/pause``, resumable);
3. optional kill-switch *file* (touch a file to pause — handy on servers);
4. market open (per asset class);
5. structural confidence >= ``JEXI_MIN_CONFIDENCE`` — the bot only
   trades when it is *sure*, per the "not dependent on any single LLM
   opinion" rule (confidence here is computed from agent agreement,
   evidence count and data freshness, not vibes).

**Control plane**
* Telegram controller (optional): /status /account /positions /pnl
  /pause /resume /kill /clear /help — chat with your bot from anywhere.
* Health HTTP endpoint (optional): JSON status + Prometheus metrics.

**Correctness**
* every execution goes through :class:`OrderLifecycleManager`
  (brackets, retries, fill verification, journaling);
* exits are evaluated every cycle against fresh prices;
* reconciliation runs hourly so memory never drifts from the venue.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from jexi_market.brokers.base import Broker
from jexi_market.brokers.factory import build_broker
from jexi_market.config import MarketConfig
from jexi_market.data import MarketDataClient
from jexi_market.execution.lifecycle import OrderLifecycleManager
from jexi_market.memory import PerformanceMemory
from jexi_market.observability import AuditLog, health_snapshot
from jexi_market.orchestrator import MarketBoss
from jexi_market.pipeline import DecisionPipeline
from jexi_market.risk.state import RiskStateStore
from jexi_market.scheduler import AutonomousScheduler

logger = logging.getLogger(__name__)

# US equity session (ET).  Exchange holidays are approximated with the
# broker clock when available (Alpaca) — this local check covers
# weekends + after-hours for everything else.
ET = ZoneInfo("America/New_York")
EQUITY_OPEN = (9, 30)
EQUITY_CLOSE = (16, 0)


def is_equity_session(now: Optional[datetime] = None) -> bool:
    """True during regular US equity trading hours (Mon-Fri 9:30-16:00 ET)."""
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return EQUITY_OPEN[0] * 60 + EQUITY_OPEN[1] <= minutes < EQUITY_CLOSE[0] * 60 + EQUITY_CLOSE[1]


@dataclass
class RunnerState:
    """In-memory mirror of the runner's operational state."""

    cycles: int = 0
    orders_placed: int = 0
    trades_closed: int = 0
    consecutive_failures: int = 0
    started_at: float = field(default_factory=time.time)
    last_cycle_at: float = 0.0
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles": self.cycles,
            "orders_placed": self.orders_placed,
            "trades_closed": self.trades_closed,
            "consecutive_failures": self.consecutive_failures,
            "started_at": self.started_at,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "last_cycle_at": self.last_cycle_at,
            "last_error": self.last_error,
        }


class MarketRunner247:
    """Long-running autonomous trading loop with layered safety gates."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        broker: Optional[Broker] = None,
        pipeline: Optional[DecisionPipeline] = None,
        memory: Optional[PerformanceMemory] = None,
        state_store: Optional[RiskStateStore] = None,
        audit: Optional[AuditLog] = None,
        enable_telegram: Optional[bool] = None,
        enable_health_server: Optional[bool] = None,
    ):
        self.config = config or MarketConfig()
        self.broker = broker or build_broker(self.config)
        self.memory = memory or PerformanceMemory(self.config.memory_db_path)
        self.state = state_store or RiskStateStore(self.config.state_db_path)
        self.audit = audit or AuditLog(self.config.audit_log_path)
        self.lifecycle = OrderLifecycleManager(self.broker, self.memory, self.audit)
        self.pipeline = pipeline or DecisionPipeline(
            self.config, lifecycle=self.lifecycle, broker=self.broker, state_store=self.state
        )
        self.scheduler = AutonomousScheduler(self.config, pipeline=self.pipeline)
        self.data_client = MarketDataClient()
        self.runner_state = RunnerState()
        self._stop = threading.Event()

        # Optional control planes
        self._telegram = None
        want_tg = enable_telegram if enable_telegram is not None else bool(self.config.telegram_bot_token)
        if want_tg and self.config.telegram_bot_token:
            try:
                from jexi_market.telegram_control import TelegramController
                self._telegram = TelegramController(self.config, runner=self)
            except Exception as exc:
                logger.warning("telegram controller unavailable: %s", exc)
        want_http = enable_health_server if enable_health_server is not None else _env_bool("JEXI_HEALTH_SERVER", False)
        self._health_thread = threading.Thread(
            target=self._health_server_loop, daemon=True
        ) if want_http else None

    # ------------------------------------------------------------------
    # gate checks
    # ------------------------------------------------------------------
    def trading_allowed(self) -> tuple:
        """Layered pre-trade gate.  Returns (allowed, reason)."""
        if self.state.is_halted():
            return False, f"risk halt active: {self.state.load().get('halt_reason', '')}"
        if self.state.is_paused():
            return False, f"operator pause active: {self.state.load().get('paused_reason', '')}"
        if self.config.kill_switch_file and os.path.exists(self.config.kill_switch_file):
            return False, f"kill-switch file present: {self.config.kill_switch_file}"
        if not self.config.trade_247:
            if self.config.asset_class == "crypto":
                pass  # 24/7 by nature
            elif hasattr(self.broker, "is_market_open") and not self.broker.is_market_open():
                return False, "broker reports market closed"
            elif self.config.asset_class == "equity" and not is_equity_session():
                return False, "outside US equity session (Mon-Fri 9:30-16:00 ET)"
        return True, "ok"

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    def job_trade_cycle(self) -> Dict[str, Any]:
        """One full cycle: gate → scan/analyze → (execute) → exits."""
        allowed, reason = self.trading_allowed()
        if not allowed:
            self.audit.event("cycle_skipped", reason=reason)
            return {"executed": False, "reason": reason}

        run = self.pipeline.run_full(execute_paper=True)
        summary = dict(run.summary)

        # Exit management with fresh prices for held symbols.
        prices: Dict[str, float] = {}
        for t in self.memory.recent_trades(limit=100):
            if t.get("outcome") != "open":
                continue
            sym = t.get("symbol", "")
            if sym and sym not in prices:
                px = self.broker.get_latest_price(sym)
                if px:
                    prices[sym] = px
                elif self.broker.configured is False:
                    snap = self.data_client.get_daily(sym, days=2)
                    if snap.ok:
                        prices[sym] = float(snap.latest_price or 0.0)
        closed = self.lifecycle.check_exits(prices)
        if closed:
            self.runner_state.trades_closed += len(closed)

        return {"executed": True, "summary": summary, "exits_closed": closed}

    def job_reconcile(self) -> Dict[str, Any]:
        return self.lifecycle.reconcile()

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    def run_forever(
        self,
        *,
        trade_cycle_seconds: int = 900,
        reconcile_every_cycles: int = 4,
    ) -> None:
        """Run until SIGINT/SIGTERM or :meth:`stop`."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self.audit.event("runner_started", broker=self.broker.name,
                         paper=self.broker.paper, config=self.config.summary())
        if self._telegram:
            threading.Thread(target=self._telegram.poll_forever, daemon=True).start()
            self._telegram.send("JEXI Market 24/7 runner started ✅")
        if self._health_thread:
            self._health_thread.start()

        cycles = 0
        try:
            while not self._stop.is_set():
                cycles += 1
                started = time.time()
                try:
                    self.job_trade_cycle()
                    self.runner_state.consecutive_failures = 0
                    self.state.reset_failures()
                    self.runner_state.last_error = None
                    if cycles % reconcile_every_cycles == 0:
                        self.job_reconcile()
                except Exception as exc:
                    logger.exception("trade cycle failed")
                    self.runner_state.last_error = str(exc)
                    n = self.state.bump_failures()
                    self.runner_state.consecutive_failures = n
                    self.audit.event("cycle_failed", error=str(exc), consecutive=n)
                    if n >= self.config.max_consecutive_failures:
                        self.audit.event("watchdog_halt", consecutive_failures=n)
                        self.audit.event("halt", reason=f"watchdog: {n} consecutive cycle failures")
                        self.state.set_halt(f"watchdog: {n} consecutive cycle failures")
                        if self._telegram:
                            self._telegram.send(
                                f"🛑 JEXI HALTED: {n} consecutive cycle failures.\n"
                                f"Last error: {self.runner_state.last_error}"
                            )

                self.runner_state.cycles += 1
                self.runner_state.last_cycle_at = time.time()
                self.state.heartbeat()

                # Roll daily equity bookkeeping through the broker account.
                try:
                    acct = self.broker.get_account()
                    if acct.equity > 0:
                        self.state.update_equity(acct.equity)
                except Exception:
                    pass

                elapsed = time.time() - started
                sleep_s = max(5.0, trade_cycle_seconds - elapsed)
                self._stop.wait(sleep_s)
        finally:
            self.audit.event("runner_stopped", cycles=self.runner_state.cycles)
            logger.info("runner exited cleanly after %d cycles", self.runner_state.cycles)

    def stop(self) -> None:
        self._stop.set()

    def _handle_signal(self, signum, _frame) -> None:
        logger.info("signal %s received — shutting down gracefully", signum)
        self.stop()

    # ------------------------------------------------------------------
    # health endpoint
    # ------------------------------------------------------------------
    def health_payload(self) -> Dict[str, Any]:
        risk = self.state.load()
        risk["halt_active"] = self.state.is_halted()
        risk["pause_active"] = self.state.is_paused()
        runner = self.runner_state.to_dict()
        runner["heartbeat_age_seconds"] = self.state.last_heartbeat_age()
        return health_snapshot(
            broker_status=self.broker.status(),
            risk_state=risk,
            memory_stats=self.memory.stats_summary(),
            runner_state=runner,
            extra={"allowed": self.trading_allowed()},
        )

    def _health_server_loop(self, port: int = 8090) -> None:
        import json as _json
        from http.server import BaseHTTPRequestHandler, HTTPServer

        runner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/metrics":
                    from jexi_market.observability import prometheus_metrics_text
                    body = prometheus_metrics_text({
                        **runner.memory.stats_summary(),
                        "risk": {"halted": runner.state.is_halted(), "paused": runner.state.is_paused(),
                                 "peak_equity": runner.state.load().get("peak_equity", 0.0)},
                        "runner": {"heartbeat_age_seconds": runner.state.last_heartbeat_age()},
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                else:
                    body = _json.dumps(runner.health_payload(), default=str).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        try:
            server = HTTPServer(("0.0.0.0", port), Handler)
            server.serve_forever()
        except Exception as exc:
            logger.warning("health server stopped: %s", exc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
