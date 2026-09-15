# -*- coding: utf-8 -*-
"""AccountPlanner — "check your account, then plan the day".

Before JEXI hunts for opportunities it looks at the *actual* broker
account and the *actual* performance memory, then writes a concrete
trading plan:

* how much cash is deployable,
* how many new positions it will open today,
* the dollar risk budget per trade (from the risk envelope),
* the daily loss budget still available (from persisted risk state),
* which setups are currently "working" (from performance memory —
  strategies/agents with positive expectancy get priority),
* what to watch out for (open positions near stops, concentration).

The plan is produced deterministically (no LLM) and is available both as
structured data (:class:`TradingPlan`) and as a plain-English paragraph
for ntfy via :mod:`jexi_market.plain_english`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.config import MarketConfig
from jexi_market.memory import PerformanceMemory
from jexi_market.risk.state import RiskStateStore

logger = logging.getLogger(__name__)


@dataclass
class TradingPlan:
    """What JEXI intends to do today, derived from the real account."""

    broker_name: str = ""
    paper: bool = True
    equity: float = 0.0
    cash: float = 0.0
    n_positions: int = 0
    open_profit: Optional[float] = None

    max_new_positions: int = 0
    risk_per_trade_amount: float = 0.0
    daily_budget_left: Optional[float] = None

    best_setups: List[str] = field(default_factory=list)
    watch_out: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    halted: bool = False
    paused: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "broker": self.broker_name,
            "paper": self.paper,
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "n_positions": self.n_positions,
            "open_profit": None if self.open_profit is None else round(self.open_profit, 2),
            "max_new_positions": self.max_new_positions,
            "risk_per_trade_amount": round(self.risk_per_trade_amount, 2),
            "daily_budget_left": None if self.daily_budget_left is None else round(self.daily_budget_left, 2),
            "best_setups": self.best_setups,
            "watch_out": self.watch_out,
            "notes": self.notes,
            "halted": self.halted,
            "paused": self.paused,
        }


class AccountPlanner:
    """Build a daily TradingPlan from broker + memory + risk state."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        broker: Any = None,
        memory: Optional[PerformanceMemory] = None,
        state_store: Optional[RiskStateStore] = None,
    ):
        self.config = config or MarketConfig()
        self.broker = broker
        self.memory = memory
        self.state = state_store

    # ------------------------------------------------------------------
    def build(self) -> TradingPlan:
        plan = TradingPlan()
        plan.broker_name = getattr(self.broker, "name", "paper") if self.broker else "paper"
        plan.paper = bool(getattr(self.broker, "paper", True)) if self.broker else True

        # -- gate state -------------------------------------------------
        if self.state is not None:
            plan.halted = self.state.is_halted()
            plan.paused = self.state.is_paused()

        # -- account ------------------------------------------------------
        equity, cash, n_pos, open_profit = self._read_account(plan)
        plan.equity = equity
        plan.cash = cash
        plan.n_positions = n_pos
        plan.open_profit = open_profit

        # -- risk budget ---------------------------------------------------
        risk_fraction = max(0.0, min(self.config.max_risk_per_trade, 0.05))
        plan.risk_per_trade_amount = equity * risk_fraction

        # daily budget remaining from persisted state (peak/day-start)
        if self.state is not None and equity > 0:
            try:
                day_start = float(self.state.load().get("day_start_equity") or 0.0)
                if day_start > 0:
                    day_loss_fraction = max(0.0, (day_start - equity) / day_start)
                    plan.daily_budget_left = max(
                        0.0, (self.config.daily_loss_limit - day_loss_fraction)) * day_start
            except Exception:
                pass
        if plan.daily_budget_left is None:
            plan.daily_budget_left = equity * self.config.daily_loss_limit

        # -- position count budget ------------------------------------------
        # Room in the portfolio: hard cap 8 concurrent names, less whatever
        # is open, further capped by available cash.
        max_total = 8
        plan.max_new_positions = max(0, max_total - n_pos)
        if equity > 0 and cash <= equity * 0.05:
            plan.max_new_positions = 0
            plan.notes.append("Almost no cash left — today is about managing what I hold.")

        # -- what has been working (performance memory) -----------------------
        best = self._best_setups()
        plan.best_setups = best
        if best:
            plan.notes.append(
                "Lately the best results came from: " + ", ".join(best[:3]) + ".")

        # -- reflection lessons (v0.5, FinMem pattern) -------------------
        if self.memory is not None:
            try:
                reflection = self.memory.reflect()
                for lesson in reflection.get("lessons", [])[:3]:
                    plan.notes.append(lesson)
            except Exception as exc:  # reflection must never break the plan
                logger.debug("reflection unavailable: %s", exc)

        # -- watch-outs from open positions ------------------------------------
        plan.watch_out = self._watch_outs()

        # -- gate notes ------------------------------------------------------
        if plan.halted:
            plan.max_new_positions = 0
            plan.notes.append("Trading is HALTED (safety stop). I will only watch.")
        elif plan.paused:
            plan.max_new_positions = 0
            plan.notes.append("Trading is paused by you. I will only watch.")
        return plan

    # ------------------------------------------------------------------
    def _read_account(self, plan: TradingPlan) -> tuple:
        equity, cash, n_pos, open_profit = 0.0, 0.0, 0, None
        if self.broker is None:
            return equity, cash, n_pos, open_profit
        try:
            acct = self.broker.get_account()
            equity = float(acct.equity or 0.0)
            cash = float(acct.cash or 0.0)
        except Exception as exc:
            plan.notes.append(f"Could not read the account ({exc}).")
            return equity, cash, n_pos, open_profit
        try:
            positions = self.broker.get_positions()
            n_pos = len(positions or [])
            open_profit = sum(float(getattr(p, "unrealized_pl", 0.0) or 0.0) for p in (positions or []))
        except Exception:
            pass
        return equity, cash, n_pos, open_profit

    # ------------------------------------------------------------------
    def _best_setups(self) -> List[str]:
        if self.memory is None:
            return []
        try:
            stats = self.memory.agent_stats()
        except Exception:
            return []
        out: List[str] = []
        # agent_stats exposes per-agent accuracy + attributed P&L; pick
        # the agents with accuracy >= 55% over >= 5 calls and positive
        # attributed pnl — those are the setups currently "working".
        for agent, s in stats.items():
            try:
                acc = float(s.get("accuracy", 0.0))
                n = int(s.get("n_calls", 0))
                pnl = float(s.get("total_pnl", 0.0))
                if n >= 5 and acc >= 0.55 and pnl > 0:
                    out.append(agent.replace("_", " "))
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    def _watch_outs(self) -> List[str]:
        if self.memory is None:
            return []
        outs: List[str] = []
        try:
            for t in self.memory.recent_trades(limit=50):
                if t.get("outcome") != "open":
                    continue
                sym = t.get("symbol", "")
                entry = float(t.get("entry") or t.get("entry_price") or 0.0)
                stop = float(t.get("stop_loss") or 0.0)
                if sym and entry > 0 and stop > 0:
                    outs.append(
                        f"{sym} would be sold automatically if it falls to ${stop:,.2f}.")
        except Exception:
            pass
        return outs
