# -*- coding: utf-8 -*-
"""Self-evaluation loop for JEXI Market.

Closes open paper trades (using the latest price), records the outcome
in the performance memory, and updates agent adaptive weights.  This is
the spec's section 21 ("Self-Evaluation") + section 22 ("Agent
Performance") made concrete.

The loop is intentionally conservative:
  * It only closes trades that hit their stop / take-profit / max-holding
    conditions (same as the backtester's logic).
  * It NEVER auto-modifies production trading logic — only the agent
    consensus weights, which are clamped to [0.5, 1.5].
  * Every closed trade is journaled with full agent attribution.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from jexi_market.config import MarketConfig
from jexi_market.contracts import SignalDirection
from jexi_market.data import MarketDataClient
from jexi_market.memory import PerformanceMemory

logger = logging.getLogger(__name__)


@dataclass
class ClosedTrade:
    decision_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str
    days_held: int
    agents_correct: List[str] = field(default_factory=list)
    agents_wrong: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "pnl_pct": round(self.pnl_pct, 4),
            "exit_reason": self.exit_reason,
            "days_held": self.days_held,
            "agents_correct": self.agents_correct,
            "agents_wrong": self.agents_wrong,
        }


class SelfEvaluationLoop:
    """Closes open paper trades and updates agent weights.

    Usage::

        loop = SelfEvaluationLoop(config, memory)
        closed = loop.evaluate_open_trades()
        # `closed` is a list of ClosedTrade records; memory is updated.
    """

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        memory: Optional[PerformanceMemory] = None,
        data_client: Optional[MarketDataClient] = None,
    ):
        self.config = config or MarketConfig()
        self.memory = memory or PerformanceMemory(self.config.memory_db_path)
        self.data_client = data_client or MarketDataClient()

    def evaluate_open_trades(self, *, max_to_close: int = 50) -> List[ClosedTrade]:
        """Walk every open trade, fetch the latest price, decide if it
        should close (stop / take-profit / max-holding), and if so record
        the outcome with agent attribution."""
        open_trades = [
            t for t in self.memory.recent_trades(limit=max_to_close * 2)
            if t.get("outcome") == "open"
        ][:max_to_close]
        closed: List[ClosedTrade] = []
        for trade_row in open_trades:
            decision_id = trade_row["decision_id"]
            symbol = trade_row["symbol"]
            direction = trade_row["direction"]
            entry = float(trade_row.get("entry") or 0.0)
            stop = float(trade_row.get("stop_loss") or 0.0)
            target = float(trade_row.get("take_profit") or 0.0)
            decided_at = float(trade_row.get("decided_at") or 0.0)
            supporting = _safe_json_list(trade_row.get("supporting_agents"))
            opposing = _safe_json_list(trade_row.get("opposing_agents"))

            if not entry or entry <= 0:
                continue

            # Fetch latest price
            snap = self.data_client.get_daily(symbol, days=5)
            if not snap.ok or not snap.latest_price:
                continue
            latest = snap.latest_price

            # Decide exit
            exit_price, reason, days_held = self._decide_exit(
                entry=entry,
                stop=stop,
                target=target,
                latest=latest,
                direction=direction,
                decided_at=decided_at,
            )
            if exit_price is None:
                continue  # not yet time to close

            # Compute PnL
            if direction == "long":
                pnl_pct = exit_price / entry - 1.0
            elif direction == "short":
                pnl_pct = 1.0 - exit_price / entry
            else:
                continue  # FLAT — shouldn't be in memory as open

            # Attribute agents: long-direction agents were "correct" if
            # the trade was profitable; short-direction agents were
            # correct if shorting was profitable.
            agents_correct: List[str] = []
            agents_wrong: List[str] = []
            won = pnl_pct > 0
            if direction == "long":
                if won:
                    agents_correct = supporting
                    agents_wrong = opposing
                else:
                    agents_correct = opposing
                    agents_wrong = supporting
            else:  # short
                if won:
                    agents_correct = supporting
                    agents_wrong = opposing
                else:
                    agents_correct = opposing
                    agents_wrong = supporting

            self.memory.close_trade(
                decision_id,
                exit_price=exit_price,
                pnl_pct=pnl_pct,
                exit_reason=reason,
                agents_correct=agents_correct,
                agents_wrong=agents_wrong,
                data_reliable=True,
            )
            closed.append(ClosedTrade(
                decision_id=decision_id,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                exit_price=exit_price,
                pnl_pct=pnl_pct,
                exit_reason=reason,
                days_held=days_held,
                agents_correct=agents_correct,
                agents_wrong=agents_wrong,
            ))
        return closed

    def _decide_exit(
        self,
        *,
        entry: float,
        stop: Optional[float],
        target: Optional[float],
        latest: float,
        direction: str,
        decided_at: float,
        max_holding_days: int = 20,
    ) -> Tuple[Optional[float], str, int]:
        """Return (exit_price, reason, days_held) or (None, "", 0)."""
        now = time.time()
        days_held = int((now - decided_at) / 86400.0) if decided_at else 0
        if direction == "long":
            if stop and latest <= stop:
                return stop, "stop_loss", days_held
            if target and latest >= target:
                return target, "take_profit", days_held
            if days_held >= max_holding_days:
                return latest, "max_holding", days_held
        elif direction == "short":
            if stop and latest >= stop:
                return stop, "stop_loss", days_held
            if target and latest <= target:
                return target, "take_profit", days_held
            if days_held >= max_holding_days:
                return latest, "max_holding", days_held
        return None, "", days_held

    def agent_leaderboard(self, *, min_calls: int = 3) -> List[Dict[str, Any]]:
        """Rank agents by historical accuracy.

        The orchestrator consults this implicitly through
        ``memory.agent_weight()`` — this method just returns a sorted
        view for reporting / dashboards.
        """
        stats = self.memory.agent_stats()
        rows = [
            {
                "agent_id": aid,
                "accuracy": s["accuracy"],
                "n_calls": s["n_calls"],
                "n_correct": s["n_correct"],
                "n_wrong": s["n_wrong"],
                "total_pnl": s["total_pnl"],
                "adaptive_weight": self.memory.agent_weight(aid),
            }
            for aid, s in stats.items()
            if s["n_calls"] >= min_calls
        ]
        rows.sort(key=lambda r: r["accuracy"], reverse=True)
        return rows


def _safe_json_list(value: Any) -> List[str]:
    """Parse a JSON list column safely; never raises."""
    import json
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []
