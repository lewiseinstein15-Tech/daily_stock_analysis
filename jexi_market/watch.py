# -*- coding: utf-8 -*-
"""OpportunityRunner — the "trade at the right time" loop (v0.4).

Unlike :class:`~jexi_market.runner.MarketRunner247` (fixed cadence), the
OpportunityRunner is **event-driven**:

    ┌─────────────────────────────────────────────────────────────┐
    │ every JEXI_WATCH_INTERVAL seconds (cheap, no LLM, no agents) │
    │  1. watch the universe with the TriggerEngine                │
    │  2. held positions: check exits with fresh prices            │
    ├─────────────────────────────────────────────────────────────┤
    │ first watch of the day (optional)                            │
    │  • AccountPlanner builds today's plan from the real account  │
    │  • ntfy: "Good morning — here is my plan" (plain English)    │
    ├─────────────────────────────────────────────────────────────┤
    │ when a trigger fires (priority >= threshold, cooldown ok)    │
    │  3. ntfy: "I spotted something ..." (plain English)          │
    │  4. run the FULL agent pipeline on that symbol only          │
    │  5. if the risk gate + confidence gate approve -> order      │
    │     via the OrderLifecycleManager (bracket stop/target)      │
    │  6. ntfy: what I did and why, with real dollar amounts       │
    └─────────────────────────────────────────────────────────────┘

All the v0.3 safety gates still apply on every order: persisted halt /
pause / kill-file / market hours / min confidence.  The runner adds a
**data-failure budget** — repeated broken market-data cycles trip the
same watchdog halt as pipeline crashes (a bot that cannot see the
market must not pretend everything is fine).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker
from jexi_market.brokers.factory import build_broker
from jexi_market.config import MarketConfig
from jexi_market.data import MarketDataClient
from jexi_market.execution.lifecycle import OrderLifecycleManager
from jexi_market.memory import PerformanceMemory
from jexi_market.notifications import make_reporter
from jexi_market.observability import AuditLog
from jexi_market.pipeline import DecisionPipeline
from jexi_market.planner import AccountPlanner, TradingPlan
from jexi_market.plain_english import (
    translate_decision,
    translate_halt_cleared,
    translate_plan,
    translate_trade_closed,
    translate_trade_opened,
    translate_trigger,
    translate_watchdog_halt,
)
from jexi_market.risk.state import RiskStateStore
from jexi_market.triggers import TriggerConfig, TriggerEngine, TriggerEvent

logger = logging.getLogger(__name__)


@dataclass
class WatchStats:
    """Operational counters for the watch loop."""

    watches: int = 0
    triggers_fired: int = 0
    pipeline_runs: int = 0
    orders_placed: int = 0
    trades_closed: int = 0
    consecutive_failures: int = 0
    last_plan_date: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "watches": self.watches,
            "triggers_fired": self.triggers_fired,
            "pipeline_runs": self.pipeline_runs,
            "orders_placed": self.orders_placed,
            "trades_closed": self.trades_closed,
            "consecutive_failures": self.consecutive_failures,
            "last_plan_date": self.last_plan_date,
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }


class OpportunityRunner:
    """Trigger-driven trading loop with plain-English ntfy updates."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        broker: Optional[Broker] = None,
        pipeline: Optional[DecisionPipeline] = None,
        memory: Optional[PerformanceMemory] = None,
        state_store: Optional[RiskStateStore] = None,
        audit: Optional[AuditLog] = None,
        trigger_engine: Optional[TriggerEngine] = None,
        reporter: Optional[Any] = None,
        enable_telegram: Optional[bool] = None,
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
        self.triggers = trigger_engine or TriggerEngine(
            self.config,
            trigger_config=TriggerConfig(cooldown_seconds=max(600, self.config.watch_interval_seconds * 30)),
        )
        self.reporter = reporter or make_reporter(self.config)
        self.planner = AccountPlanner(
            self.config, broker=self.broker, memory=self.memory, state_store=self.state
        )
        self.stats = WatchStats()
        # v0.4.1: persist the "morning plan already sent" flag so a
        # restart does not re-send the same plan (and never skips it).
        try:
            self.stats.last_plan_date = self.state.get_kv("last_plan_date", "") or ""
        except Exception:
            self.stats.last_plan_date = ""
        self._stop = threading.Event()

        self._telegram = None
        want_tg = enable_telegram if enable_telegram is not None else bool(self.config.telegram_bot_token)
        if want_tg and self.config.telegram_bot_token:
            try:
                from jexi_market.telegram_control import TelegramController
                self._telegram = TelegramController(self.config, runner=None)
            except Exception as exc:
                logger.warning("telegram controller unavailable: %s", exc)

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    def notify(self, title: str, body: str, *, priority: str = "default", tags: Optional[List[str]] = None) -> bool:
        if self._telegram:
            try:
                self._telegram.send(f"{title}\n\n{body}")
            except Exception:
                pass
        return self.reporter.publish(title, body, priority=priority, tags=tags or ["chart"])

    # ------------------------------------------------------------------
    # gates (same layered safety as runner247)
    # ------------------------------------------------------------------
    def trading_allowed(self) -> tuple:
        if self.state.is_halted():
            return False, f"risk halt active: {self.state.load().get('halt_reason', '')}"
        if self.state.is_paused():
            return False, f"operator pause active: {self.state.load().get('paused_reason', '')}"
        if self.config.kill_switch_file:
            import os
            if os.path.exists(self.config.kill_switch_file):
                return False, f"kill-switch file present: {self.config.kill_switch_file}"
        if not self.config.trade_247 and self.config.asset_class == "equity":
            from jexi_market.runner import is_equity_session
            if not is_equity_session():
                return False, "outside US equity session"
        return True, "ok"

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    def job_morning_plan(self) -> Optional[TradingPlan]:
        """Once per calendar day: build + announce the plan."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.stats.last_plan_date == today:
            return None
        if not self.config.notify_daily_plan:
            self.stats.last_plan_date = today
            try:
                self.state.set_kv("last_plan_date", today)
            except Exception:
                pass
            return None
        plan = self.planner.build()
        self.stats.last_plan_date = today
        try:
            self.state.set_kv("last_plan_date", today)
        except Exception:
            pass
        account_line = (
            f"Account: ${plan.equity:,.2f} total, ${plan.cash:,.2f} ready to invest, "
            f"{plan.n_positions} open."
        )
        body = translate_plan(
            equity=plan.equity,
            cash=plan.cash,
            max_new_positions=plan.max_new_positions,
            risk_per_trade_amount=plan.risk_per_trade_amount,
            daily_budget_left=plan.daily_budget_left,
            watch_out=plan.watch_out,
            notes=plan.notes,
        )
        self.notify(
            "JEXI — today's plan",
            f"Good morning. {account_line}\n\n{body}",
            priority="default",
            tags=["sun", "chart"],
        )
        self.audit.event("morning_plan", plan=plan.to_dict())
        return plan

    def job_watch(self) -> Dict[str, Any]:
        """One cheap watch: triggers + exits. Returns what happened."""
        self.stats.watches += 1
        allowed, reason = self.trading_allowed()
        open_trades = self._open_trades_by_symbol()

        # 1. exit management always runs (even when halted — protect capital)
        closed = self._manage_exits(open_trades)
        for t in closed:
            profit = t.get("profit")
            self.notify(
                f"{t.get('symbol', 'A trade')} — position closed",
                translate_trade_closed(
                    t.get("symbol", ""),
                    entry=t.get("entry"),
                    exit_price=t.get("exit_price"),
                    profit=profit,
                    reason=t.get("reason", ""),
                ),
                priority="default" if (profit or 0) >= 0 else "high",
                tags=["money", "chart"],
            )

        if not allowed:
            return {"watched": True, "trading_allowed": False, "reason": reason,
                    "triggers": [], "deep_dives": [], "exits_closed": closed}

        # 2. morning plan (first cycle of the day) — never break the watch
        try:
            self.job_morning_plan()
        except Exception as exc:
            logger.warning("morning plan failed (non-fatal): %s", exc)

        # 3. triggers
        universe = self.config.scanner_symbols
        events = self.triggers.evaluate_universe(universe, open_trades=open_trades)
        # v0.4.1: data-failure budget — a watcher that cannot see ANY
        # market must not pretend everything is quiet.  If every symbol
        # in the universe came back unusable, treat it like a crashed
        # cycle so the watchdog halt (and its emergency ntfy) trips.
        failed = int(getattr(self.triggers, "last_scan_failures", 0) or 0)
        if universe and failed >= len(universe):
            self.audit.event("data_outage", symbols=len(universe), consecutive_failures=self.stats.consecutive_failures)
            raise RuntimeError(
                f"market data unavailable for all {len(universe)} universe symbols "
                f"(data-failure budget {self.stats.consecutive_failures + 1}/"
                f"{self.config.max_consecutive_failures})"
            )
        # v0.4.1: one position per symbol — never re-enter a market we
        # already hold (pyramiding without limit was possible before).
        # Exit-timing triggers (near_stop / near_target) stay live.
        exit_kinds = {"near_stop", "near_target"}
        kept: List[TriggerEvent] = []
        for ev in events:
            if ev.symbol in open_trades and ev.kind not in exit_kinds:
                self.audit.event("trigger_suppressed", symbol=ev.symbol,
                                 trigger_kind=ev.kind, reason="position already open")
                continue
            kept.append(ev)
        events = kept
        self.stats.triggers_fired += len(events)
        for ev in events:
            self.audit.event("trigger", trigger=ev.to_dict())

        if self.config.notify_triggers:
            for ev in events[:3]:
                self.notify(
                    f"JEXI spotted something: {ev.symbol}",
                    translate_trigger(ev),
                    priority="default" if ev.priority <= 3 else "high",
                    tags=["eyes", "chart"],
                )

        # 4. deep analysis only for strong-enough triggers
        worth_analyzing = [
            ev for ev in events if ev.priority >= self.config.trigger_min_priority
        ]
        results: List[Dict[str, Any]] = []
        for ev in worth_analyzing[:3]:  # cap deep dives per watch
            results.append(self._deep_dive(ev))

        return {
            "watched": True,
            "trading_allowed": True,
            "triggers": [e.to_dict() for e in events],
            "deep_dives": results,
            "exits_closed": closed,
        }

    # ------------------------------------------------------------------
    def _deep_dive(self, ev: TriggerEvent) -> Dict[str, Any]:
        """Full agent pipeline on one triggered symbol + gated execution."""
        self.stats.pipeline_runs += 1
        # v0.4.1: one position per symbol — a trigger on a market we
        # already hold (e.g. near_target) must never open a second order.
        if ev.symbol in self._open_trades_by_symbol():
            return {"symbol": ev.symbol, "outcome": "already_held",
                    "reason": "one position per symbol"}
        try:
            result = self.pipeline.boss.analyze_symbol(ev.symbol, days=self.config.scanner_lookback_days)
        except Exception as exc:
            logger.warning("deep dive failed for %s: %s", ev.symbol, exc)
            return {"symbol": ev.symbol, "error": str(exc)}

        decision = result.decision
        if decision is None or decision.direction.value == "flat":
            return {"symbol": ev.symbol, "outcome": "no_trade", "reason": "consensus: stay out"}

        if not result.gate_approved:
            self.audit.event("rejected", symbol=ev.symbol,
                             violations=result.gate_violations, reason="risk gate")
            return {"symbol": ev.symbol, "outcome": "rejected", "violations": result.gate_violations}

        conf = decision.confidence.score
        if conf < self.config.min_confidence:
            self.audit.event("held_back", symbol=ev.symbol, confidence=conf)
            return {"symbol": ev.symbol, "outcome": "not_sure_yet",
                    "confidence": round(conf, 4)}

        # --- execute ------------------------------------------------------
        acct = self.broker.get_account()
        equity = acct.equity if acct.equity > 0 else 100_000.0
        price = decision.entry or ev.price or 0.0
        if price <= 0:
            return {"symbol": ev.symbol, "outcome": "no_price"}
        # v0.4.1: give the simulator the exact price this decision was
        # made on, so paper fills never stall for lack of a quote.
        if hasattr(self.broker, "seed_price"):
            try:
                self.broker.seed_price(ev.symbol, price)
            except Exception:
                pass
        outcome = self.lifecycle.open_position(
            decision, equity, price, paper_mode=self.broker.paper)
        title, body = translate_decision(
            decision,
            account_equity=equity,
            position_value=(outcome.filled_qty or 0) * (outcome.filled_price or price),
            executed=bool(outcome.ok),
        )
        err = (outcome.error or "").lower()
        if outcome.ok:
            self.notify(
                title,
                body,
                priority="high",
                tags=["moneybag", "chart"],
            )
            self.stats.orders_placed += 1
            self.audit.event("order", symbol=ev.symbol, trigger=ev.kind,
                             order_id=outcome.order_id, qty=outcome.filled_qty,
                             price=outcome.filled_price)
            return {"symbol": ev.symbol, "outcome": "ordered",
                    "order_id": outcome.order_id, "qty": outcome.filled_qty}
        # v0.4.1: honest plain-English reasons — an execution failure is
        # NOT the same as a safety rejection, and a long-only account
        # skipping a short idea is not "a safety check did not pass".
        if "long-only" in err or "no held position" in err or "naked_short" in err:
            self.notify(
                f"{ev.symbol}: skip — this account buys only",
                (
                    f"I spotted a chance to profit if {ev.symbol} falls, but "
                    f"this account can only buy (not short), so I am staying "
                    f"out. Protecting your money comes first."
                ),
                priority="default",
                tags=["warning", "chart"],
            )
            return {"symbol": ev.symbol, "outcome": "skipped_long_only"}
        if "gate" in err or outcome.error == "FLAT decision" or "bad equity" in err:
            self.notify(
                f"{ev.symbol}: decided against it",
                body + "\n\nRight now I am NOT buying — a safety check did "
                "not pass, so I am staying out. Protecting your money "
                "comes first.",
                priority="default",
                tags=["warning", "chart"],
            )
            return {"symbol": ev.symbol, "outcome": "order_failed", "error": outcome.error}
        self.notify(
            f"{ev.symbol}: trade could not be placed",
            (
                f"I wanted to invest in {ev.symbol} and all my checks "
                f"passed, but the broker did not accept the trade just now. "
                f"Your money stays safe — I am keeping an eye on it and will "
                f"speak up next time the moment looks right."
            ),
            priority="high",
            tags=["warning", "chart"],
        )
        return {"symbol": ev.symbol, "outcome": "order_failed", "error": outcome.error}

    # ------------------------------------------------------------------
    # exits
    # ------------------------------------------------------------------
    def _open_trades_by_symbol(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        try:
            for t in self.memory.recent_trades(limit=100):
                if t.get("outcome") == "open" and t.get("symbol"):
                    out[t["symbol"]] = t
        except Exception:
            pass
        return out

    def _manage_exits(self, open_trades: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        prices: Dict[str, float] = {}
        for sym in open_trades:
            try:
                px = self.broker.get_latest_price(sym)
                if not px:
                    # v0.4.1 fix: the market-data client is the universal
                    # fallback whenever the broker cannot quote a price —
                    # previously it only ran for unconfigured brokers, so
                    # paper-mode positions were never exit-checked.
                    snap = self.pipeline.boss.data_client.get_daily(sym, days=2)
                    if snap.ok:
                        px = float(snap.latest_price or 0.0)
                if px:
                    prices[sym] = float(px)
            except Exception:
                continue
        try:
            closed = self.lifecycle.check_exits(prices)
            self.stats.trades_closed += len(closed)
        except Exception as exc:
            logger.warning("exit check failed: %s", exc)
            return []
        # Enrich the close records so notifications can state real profit.
        for rec in closed:
            trade = open_trades.get(rec.get("symbol", "")) or {}
            entry = float(trade.get("entry") or 0.0)
            exit_price = float(rec.get("exit_price") or 0.0)
            if entry > 0 and exit_price > 0:
                direction = trade.get("direction", "long")
                rec["entry"] = entry
                rec["profit"] = round(
                    (exit_price - entry) if direction == "long" else (entry - exit_price), 2)
            rec.setdefault("exit_price", exit_price or None)
        return closed

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    def watch_once(self) -> Dict[str, Any]:
        """Single watch cycle (used by CI / GitHub Actions / tests)."""
        try:
            result = self.job_watch()
            self.stats.consecutive_failures = 0
            self.state.reset_failures()
            return result
        except Exception as exc:
            logger.exception("watch cycle failed")
            n = self.state.bump_failures()
            self.stats.consecutive_failures = n
            self.audit.event("watch_failed", error=str(exc), consecutive=n)
            if n >= self.config.max_consecutive_failures:
                self.state.set_halt(f"watchdog: {n} consecutive watch failures")
                self.notify(
                    "JEXI paused itself — needs your attention",
                    translate_watchdog_halt(n, str(exc)),
                    priority="emergency",
                    tags=["rotating_light"],
                )
            return {"watched": False, "error": str(exc)}

    def watch_forever(self) -> None:
        """Run until stop() or SIGINT/SIGTERM."""
        import signal
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self.audit.event("watcher_started", broker=self.broker.name,
                         paper=self.broker.paper, config=self.config.summary())
        detected = getattr(self.broker, "name", "paper")
        self.notify(
            "JEXI is on duty",
            (
                f"Hi! I am now watching {len(self.config.scanner_symbols)} markets "
                f"for good moments to invest, connected to "
                f"{'practice trading' if self.broker.paper else 'your LIVE account'} "
                f"({detected}). You do not need to do anything — I will only "
                f"message you when something important happens: an opportunity, "
                f"a trade, or anything that needs your attention."
            ),
            priority="default",
            tags=["wave", "chart"],
        )
        interval = max(30, self.config.watch_interval_seconds)
        while not self._stop.is_set():
            started = time.time()
            self.watch_once()
            self.state.heartbeat()
            elapsed = time.time() - started
            self._stop.wait(max(5.0, interval - elapsed))
        self.audit.event("watcher_stopped", watches=self.stats.watches)

    def stop(self) -> None:
        self._stop.set()

    def _handle_signal(self, signum, _frame) -> None:
        logger.info("signal %s — shutting down watcher", signum)
        self.stop()
