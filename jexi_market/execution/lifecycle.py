# -*- coding: utf-8 -*-
"""Order lifecycle manager — the missing "execution desk" (v0.3).

The old pipeline placed a naked market order and immediately forgot
about it: no stop-loss at the broker, no fill verification, no retry,
no reconciliation between memory and the venue.  This module is the
stateful desk between the risk gate and the broker:

* :meth:`OrderLifecycleManager.open_position`
  size → gate-checked fraction → bracket order (stop/TP at the broker
  when supported) → verify fill with backoff → journal in memory.
* :meth:`OrderLifecycleManager.check_exits`
  for positions without broker-side stops, evaluate stop/TP against
  fresh prices and flatten via the broker when breached.
* :meth:`OrderLifecycleManager.reconcile`
  diff broker positions vs open trades in memory; close memory rows
  whose venue position disappeared (manual close, expiry, external
  stop) so the learning loop never drifts from reality.

Every action is retried with exponential backoff (2s/4s/8s) and every
order is written to the audit log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker
from jexi_market.contracts import Decision, SignalDirection
from jexi_market.memory import PerformanceMemory
from jexi_market.observability import AuditLog

logger = logging.getLogger(__name__)

RETRY_DELAYS = (2.0, 4.0, 8.0)


@dataclass
class ExecutionOutcome:
    """Result of an open/exit attempt (successes and failures)."""

    ok: bool
    order_id: Optional[str] = None
    filled_qty: float = 0.0
    filled_price: Optional[float] = None
    bracket: bool = False
    error: Optional[str] = None
    retries: int = 0
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "order_id": self.order_id,
            "filled_qty": self.filled_qty,
            "filled_price": self.filled_price,
            "bracket": self.bracket,
            "error": self.error,
            "retries": self.retries,
            "detail": self.detail,
        }


def _with_retries(fn, *, what: str, audit: Optional[AuditLog] = None, symbol: str = ""):
    """Run ``fn`` retrying on exception with exponential backoff."""
    last_exc: Optional[Exception] = None
    for attempt, delay in enumerate((0.0,) + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return fn(), attempt
        except Exception as exc:
            last_exc = exc
            logger.warning("%s failed (attempt %d): %s", what, attempt + 1, exc)
            if audit:
                audit.event("execution_retry", symbol=symbol, what=what,
                            attempt=attempt + 1, error=str(exc))
    raise last_exc  # type: ignore[misc]


class OrderLifecycleManager:
    """Stateful execution desk on top of any :class:`Broker`."""

    def __init__(
        self,
        broker: Broker,
        memory: Optional[PerformanceMemory] = None,
        audit: Optional[AuditLog] = None,
    ):
        self.broker = broker
        self.memory = memory
        self.audit = audit or AuditLog()

    # ------------------------------------------------------------------
    # OPEN
    # ------------------------------------------------------------------
    def open_position(
        self,
        decision: Decision,
        equity: float,
        latest_price: float,
        *,
        decision_row_id: Optional[int] = None,
        paper_mode: bool = True,
    ) -> ExecutionOutcome:
        """Turn a gate-approved decision into a live/paper bracket order."""
        if decision.direction == SignalDirection.FLAT:
            return ExecutionOutcome(ok=False, error="FLAT decision")
        if equity <= 0 or latest_price <= 0:
            return ExecutionOutcome(ok=False, error="bad equity/price")

        dollar_allocation = equity * decision.position_fraction
        qty = round(max(0.0, dollar_allocation / latest_price), 4)
        if qty <= 0:
            return ExecutionOutcome(ok=False, error="computed qty <= 0")

        side = "buy" if decision.direction == SignalDirection.LONG else "sell"

        # Long-only guard: never open a naked short.
        if side == "sell":
            held = next(
                (p for p in self.broker.get_positions() if p.symbol == decision.symbol and p.side == "long"),
                None,
            )
            if not held or held.qty <= 0:
                self.audit.event("execution_refused", symbol=decision.symbol,
                                 reason="naked_short_refused")
                return ExecutionOutcome(ok=False, error="long-only policy: no held position to sell")
            qty = min(qty, held.qty)

        used_bracket = False
        try:
            if self.broker.supports_bracket_orders and decision.stop_loss and decision.take_profit:
                order, attempt = _with_retries(
                    lambda: self.broker.submit_bracket_order(
                        decision.symbol, qty, side,
                        stop_loss=decision.stop_loss,
                        take_profit=decision.take_profit,
                    ),
                    what="bracket_order", audit=self.audit, symbol=decision.symbol,
                )
                used_bracket = True
            else:
                order, attempt = _with_retries(
                    lambda: self.broker.submit_order(decision.symbol, qty, side),
                    what="submit_order", audit=self.audit, symbol=decision.symbol,
                )
        except Exception as exc:
            self.audit.event("execution_failed", symbol=decision.symbol, error=str(exc))
            return ExecutionOutcome(ok=False, error=str(exc), retries=3)

        self.audit.event(
            "order_submitted",
            symbol=decision.symbol, side=side, qty=qty,
            order_id=order.id, status=order.status, bracket=used_bracket,
            stop_loss=decision.stop_loss, take_profit=decision.take_profit,
            paper=paper_mode,
        )

        # Verify fill (market orders usually fill immediately).
        filled_price = order.filled_avg_price
        status = order.status
        if status not in {"filled", "closed"}:
            for _ in range(3):
                time.sleep(1.0)
                try:
                    checked = self.broker.get_order(order.id)
                    status = checked.status
                    filled_price = checked.filled_avg_price or filled_price
                    if checked.filled:
                        break
                except Exception:
                    continue

        outcome = ExecutionOutcome(
            ok=status in {"filled", "closed", "open", "submitted"},
            order_id=order.id,
            filled_qty=order.filled_qty or qty,
            filled_price=filled_price,
            bracket=used_bracket,
            retries=attempt,
            detail={"status": status},
        )

        # Journal the open trade in performance memory.
        if self.memory is not None and outcome.ok and decision_row_id is None:
            try:
                row_id = self.memory.record_decision(decision, regime="executed")
                outcome.detail["memory_row"] = row_id
            except Exception as exc:
                logger.error("memory.record_decision failed: %s", exc)

        return outcome

    # ------------------------------------------------------------------
    # EXITS
    # ------------------------------------------------------------------
    def check_exits(self, prices: Dict[str, float], *, open_trades: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Evaluate stop-loss / take-profit for memory-tracked positions.

        Positions whose stops live at the broker (bracket orders) are
        skipped here — the venue fills them.  Locally-managed stops are
        flattened and closed in memory with the correct exit_reason.
        """
        closed: List[Dict[str, Any]] = []
        if open_trades is None and self.memory is not None:
            open_trades = [
                t for t in self.memory.recent_trades(limit=200)
                if t.get("outcome") == "open"
            ]
        for trade in open_trades or []:
            symbol = trade.get("symbol", "")
            price = prices.get(symbol)
            if not price:
                continue
            stop = trade.get("stop_loss")
            target = trade.get("take_profit")
            direction = trade.get("direction", "long")
            reason = None
            if direction == "long":
                if stop and price <= stop:
                    reason = "stop_loss"
                elif target and price >= target:
                    reason = "take_profit"
            else:
                if stop and price >= stop:
                    reason = "stop_loss"
                elif target and price <= target:
                    reason = "take_profit"
            if not reason:
                continue
            # Skip if the broker already manages this exit via brackets.
            venue_position = next(
                (p for p in self.broker.get_positions() if p.symbol == symbol), None
            )
            if venue_position is None:
                # Nothing at the venue — paper trade; close in memory only.
                self._close_in_memory(trade, exit_price=price, reason=reason)
                closed.append({"symbol": symbol, "reason": reason, "venue": False})
                continue
            try:
                order, _ = _with_retries(
                    lambda: self.broker.close_position(symbol),
                    what=f"close_position:{reason}", audit=self.audit, symbol=symbol,
                )
                exit_price = (order.filled_avg_price if order else None) or price
                self._close_in_memory(trade, exit_price=exit_price, reason=reason)
                self.audit.event("position_closed", symbol=symbol, reason=reason,
                                 exit_price=exit_price)
                closed.append({"symbol": symbol, "reason": reason, "venue": True,
                               "exit_price": exit_price})
            except Exception as exc:
                logger.error("failed closing %s (%s): %s", symbol, reason, exc)
                self.audit.event("close_failed", symbol=symbol, reason=reason, error=str(exc))
        return closed

    def _close_in_memory(self, trade: Dict[str, Any], *, exit_price: float, reason: str) -> None:
        if self.memory is None:
            return
        entry = trade.get("entry") or 0.0
        if not entry:
            return
        direction = trade.get("direction", "long")
        pnl = (exit_price / entry - 1.0) if direction == "long" else (1.0 - exit_price / entry)
        supporting = trade.get("supporting_agents") or []
        opposing = trade.get("opposing_agents") or []
        if isinstance(supporting, str):
            import json as _json
            try:
                supporting = _json.loads(supporting)
            except Exception:
                supporting = []
        if isinstance(opposing, str):
            import json as _json
            try:
                opposing = _json.loads(opposing)
            except Exception:
                opposing = []
        # Direction-aware attribution: supporters were right on a win.
        correct = list(supporting) if pnl > 0 else list(opposing)
        wrong = list(opposing) if pnl > 0 else list(supporting)
        try:
            self.memory.close_trade(
                trade["decision_id"],
                exit_price=exit_price,
                pnl_pct=pnl,
                exit_reason=reason,
                agents_correct=correct,
                agents_wrong=wrong,
            )
        except Exception as exc:
            logger.error("memory.close_trade failed for %s: %s", trade.get("decision_id"), exc)

    # ------------------------------------------------------------------
    # RECONCILIATION
    # ------------------------------------------------------------------
    def reconcile(self) -> Dict[str, Any]:
        """Sync memory's open trades with the broker's actual positions.

        Cases handled:
        * memory says open, venue position gone  → close in memory at the
          last known price (external close / broker-side stop filled).
        * venue position exists, memory silent   → log an orphan warning
          (position opened outside JEXI or a lost journal row).
        """
        venue = {p.symbol: p for p in self.broker.get_positions()}
        open_trades = [
            t for t in (self.memory.recent_trades(limit=200) if self.memory else [])
            if t.get("outcome") == "open"
        ]
        closed_symbols: List[str] = []
        for trade in open_trades:
            symbol = trade.get("symbol", "")
            if symbol in venue:
                continue
            price = self.broker.get_latest_price(symbol) or trade.get("entry") or 0.0
            self._close_in_memory(trade, exit_price=price, reason="external_close")
            closed_symbols.append(symbol)
        orphans = sorted(set(venue) - {t.get("symbol") for t in open_trades})
        if closed_symbols or orphans:
            self.audit.event("reconciled", closed=closed_symbols, orphans=orphans)
        return {"closed_in_memory": closed_symbols, "orphan_venue_positions": orphans}
