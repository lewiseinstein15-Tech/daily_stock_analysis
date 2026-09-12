# -*- coding: utf-8 -*-
"""Persistent risk state for JEXI Market.

The risk gate used to keep its halt flag purely in memory — restarting
the process silently cleared a "only a human can clear this" halt.  This
module persists the operationally-critical risk state in SQLite so it
survives restarts, crashes and deploys:

* ``halted`` / ``halt_reason`` / ``halted_at``  — kill-switch (survives restart)
* ``paused`` / ``paused_reason``               — operator pause (resume-able)
* ``peak_equity``                              — high-water mark for drawdown
* ``day_date`` / ``day_start_equity``          — daily-loss accounting
* ``consecutive_failures``                     — pipeline watchdog counter
* ``last_heartbeat``                           — liveness for the 24/7 runner

Storage: a single-row key/value table at ``data/jexi_market/state.sqlite``
(configurable via ``JEXI_STATE_DB``).  Cheap, atomic, inspectable.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS risk_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);
"""


class RiskStateStore:
    """Tiny persistent key/value store for operational risk state."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "data/jexi_market/state.sqlite"
        self._lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def _set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO risk_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, str(value), time.time()),
            )
            self._conn.commit()

    def _get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM risk_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    # ------------------------------------------------------------------
    # Halt / pause (kill-switch)
    # ------------------------------------------------------------------
    def set_halt(self, reason: str) -> None:
        self._set("halted", "1")
        self._set("halt_reason", reason)
        self._set("halted_at", str(time.time()))

    def clear_halt(self) -> None:
        self._set("halted", "0")
        self._set("halt_reason", "")
        self._set("halted_at", "")

    def set_pause(self, reason: str) -> None:
        self._set("paused", "1")
        self._set("paused_reason", reason)

    def clear_pause(self) -> None:
        self._set("paused", "0")
        self._set("paused_reason", "")

    def is_halted(self) -> bool:
        return self._get("halted", "0") == "1"

    def is_paused(self) -> bool:
        return self._get("paused", "0") == "1"

    # ------------------------------------------------------------------
    # Equity tracking (peak + daily loss accounting)
    # ------------------------------------------------------------------
    def update_equity(self, equity: float) -> Dict[str, Any]:
        """Record the latest equity; roll the day counter at midnight UTC.

        Returns the derived state: peak_equity, day_start_equity,
        daily_pnl, day_date.
        """
        now_utc = datetime.now(timezone.utc)
        today = now_utc.strftime("%Y-%m-%d")
        peak = float(self._get("peak_equity", "0") or 0.0)
        day_date = self._get("day_date", "")
        day_start = float(self._get("day_start_equity", "0") or 0.0)

        if day_date != today:
            # New UTC day: reset the daily baseline to current equity.
            day_date = today
            day_start = equity
            self._set("day_date", today)
            self._set("day_start_equity", str(equity))

        if equity > peak:
            peak = equity
            self._set("peak_equity", str(peak))
        # Bootstrap the peak on first ever observation.
        if peak <= 0:
            peak = equity
            self._set("peak_equity", str(peak))
        if day_start <= 0:
            day_start = equity
            self._set("day_start_equity", str(day_start))

        return {
            "peak_equity": peak,
            "day_start_equity": day_start,
            "day_date": day_date,
            "daily_pnl": equity - day_start,
        }

    # ------------------------------------------------------------------
    # Watchdog + heartbeat
    # ------------------------------------------------------------------
    def bump_failures(self) -> int:
        n = int(self._get("consecutive_failures", "0") or 0) + 1
        self._set("consecutive_failures", str(n))
        return n

    def reset_failures(self) -> None:
        self._set("consecutive_failures", "0")

    def consecutive_failures(self) -> int:
        return int(self._get("consecutive_failures", "0") or 0)

    def heartbeat(self) -> None:
        self._set("last_heartbeat", str(time.time()))

    def last_heartbeat_age(self) -> Optional[float]:
        raw = self._get("last_heartbeat")
        if not raw:
            return None
        try:
            return max(0.0, time.time() - float(raw))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        """Full state dict (used by RiskGate to restore halts)."""
        halted_at = self._get("halted_at")
        return {
            "halted": self.is_halted(),
            "halt_reason": self._get("halt_reason", "") or "",
            "halted_at": float(halted_at) if halted_at else None,
            "paused": self.is_paused(),
            "paused_reason": self._get("paused_reason", "") or "",
            "peak_equity": float(self._get("peak_equity", "0") or 0.0),
            "day_start_equity": float(self._get("day_start_equity", "0") or 0.0),
            "day_date": self._get("day_date", "") or "",
            "consecutive_failures": self.consecutive_failures(),
            "last_heartbeat_age": self.last_heartbeat_age(),
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
