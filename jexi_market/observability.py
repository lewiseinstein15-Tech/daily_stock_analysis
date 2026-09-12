# -*- coding: utf-8 -*-
"""Observability for JEXI Market (v0.3).

* :class:`AuditLog` — append-only JSONL audit trail at
  ``data/jexi_market/audit.jsonl``.  Every gate decision, order,
  exit, halt and reconciliation is one JSON line with a UTC timestamp
  (tamper-evident enough for post-trade review; the SQLite memory stays
  the querying layer).
* :func:`health_snapshot` — a single dict describing the live system
  (broker status, risk state, memory stats, heartbeat age).
* :func:`prometheus_metrics_text` — minimal Prometheus exposition format
  scraped by any monitor (no client dependency).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class AuditLog:
    """Append-only JSONL audit trail (process-safe via a lock)."""

    def __init__(self, path: Optional[str] = None, *, enabled: bool = True):
        self.path = path or "data/jexi_market/audit.jsonl"
        self.enabled = enabled
        self._lock = threading.Lock()
        if enabled:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **fields: Any) -> None:
        if not self.enabled:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        line = json.dumps(record, default=str, separators=(",", ":"))
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:
                pass  # auditing must never crash trading

    def tail(self, n: int = 50) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()[-n:]
            out = []
            for ln in lines:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
            return out
        except FileNotFoundError:
            return []


def health_snapshot(
    *,
    broker_status: Dict[str, Any],
    risk_state: Dict[str, Any],
    memory_stats: Dict[str, Any],
    runner_state: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "broker": broker_status,
        "risk": risk_state,
        "memory": memory_stats,
        "runner": runner_state or {},
    }
    if extra:
        snap.update(extra)
    return snap


def prometheus_metrics_text(stats: Iterable[Dict[str, Any]]) -> str:
    """Render a tiny Prometheus text exposition from memory stats dicts.

    Accepts the dict from ``PerformanceMemory.stats_summary()`` plus
    optional ``risk``/``runner`` dicts.
    """
    lines: list = []

    def emit(name: str, mtype: str, help_: str, value: Any) -> None:
        if not isinstance(value, (int, float)):
            return
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {mtype}")
        lines.append(f"{name} {value}")

    if isinstance(stats, dict):
        s = stats
        emit("jexi_trades_total", "counter", "Closed trades recorded", s.get("n_trades", 0))
        emit("jexi_wins_total", "counter", "Winning trades", s.get("n_win", 0))
        emit("jexi_losses_total", "counter", "Losing trades", s.get("n_loss", 0))
        emit("jexi_win_rate", "gauge", "Win rate (0..1)", s.get("win_rate", 0.0))
        emit("jexi_total_pnl_pct", "gauge", "Total PnL percent", s.get("total_pnl_pct", 0.0))
        risk = s.get("risk") or {}
        emit("jexi_risk_halted", "gauge", "1 when risk halt active", 1 if risk.get("halted") else 0)
        emit("jexi_risk_paused", "gauge", "1 when operator pause active", 1 if risk.get("paused") else 0)
        emit("jexi_peak_equity", "gauge", "Peak equity high-water mark", risk.get("peak_equity", 0.0))
        runner = s.get("runner") or {}
        hb = runner.get("heartbeat_age_seconds")
        if hb is not None:
            emit("jexi_heartbeat_age_seconds", "gauge", "Seconds since runner heartbeat", hb)
    return "\n".join(lines) + "\n"
