# -*- coding: utf-8 -*-
"""Performance memory for JEXI Market.

Tracks every closed paper trade and attributes the outcome to the
agents that contributed to the decision.  The orchestrator uses this
to weight future consensus — agents with better hit rates get more
influence over time.

Storage: SQLite at ``data/jexi_market/memory.sqlite`` (configurable via
``JEXI_MEMORY_DB``).  Lightweight, no server, easy to inspect with
``sqlite3`` from the CLI.  Schema is simple and additive — we never
run destructive migrations.

Per spec section 21/22: after each completed paper trade we record:
  * original thesis
  * predicted direction, confidence
  * entry / stop / target
  * actual outcome (pnl, exit reason)
  * market regime
  * which agents were correct vs wrong
  * data reliability

We do NOT allow this memory to auto-modify production trading logic —
that requires explicit human review.  The memory only adjusts
consensus *weights* within safe bounds (the orchestrator clamps the
multiplier to [0.5, 1.5]).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from jexi_market.contracts import Decision, SignalDirection

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL NOT NULL,
    entry REAL,
    stop_loss REAL,
    take_profit REAL,
    thesis TEXT,
    regime TEXT,
    supporting_agents TEXT,    -- JSON list
    opposing_agents TEXT,        -- JSON list
    decided_at REAL,
    -- Outcome (filled in on close)
    exit_price REAL,
    pnl_pct REAL,
    outcome TEXT,                -- "win" | "loss" | "open" | "breakeven"
    exit_reason TEXT,
    closed_at REAL,
    -- Agent attribution (filled in on close)
    agents_correct TEXT,         -- JSON list
    agents_wrong TEXT,            -- JSON list
    data_reliable INTEGER        -- 0/1
);

CREATE TABLE IF NOT EXISTS agent_stats (
    agent_id TEXT PRIMARY KEY,
    n_calls INTEGER DEFAULT 0,
    n_correct INTEGER DEFAULT 0,
    n_wrong INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    last_updated REAL
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
"""


@dataclass
class TradeRecord:
    decision_id: str
    symbol: str
    direction: str
    confidence: float
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    thesis: str = ""
    regime: str = "unknown"
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    decided_at: float = 0.0
    # Outcome
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    outcome: str = "open"           # "open" | "win" | "loss" | "breakeven"
    exit_reason: str = ""
    closed_at: Optional[float] = None
    agents_correct: List[str] = field(default_factory=list)
    agents_wrong: List[str] = field(default_factory=list)
    data_reliable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "thesis": self.thesis,
            "regime": self.regime,
            "supporting_agents": self.supporting_agents,
            "opposing_agents": self.opposing_agents,
            "decided_at": self.decided_at,
            "exit_price": self.exit_price,
            "pnl_pct": round(self.pnl_pct, 4) if self.pnl_pct is not None else None,
            "outcome": self.outcome,
            "exit_reason": self.exit_reason,
            "closed_at": self.closed_at,
            "agents_correct": self.agents_correct,
            "agents_wrong": self.agents_wrong,
            "data_reliable": self.data_reliable,
        }


class PerformanceMemory:
    """SQLite-backed performance memory.

    Note on ``:memory:`` databases: SQLite creates a *new* in-memory DB
    for every connection, so a connection-per-call pattern would lose
    the schema between calls.  To support ``:memory:`` (used heavily in
    tests) we keep a single long-lived connection when the path is
    ``:memory:``; for file paths we use the standard context-manager
    pattern.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "data/jexi_market/memory.sqlite"
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            # check_same_thread=False lets FastAPI request threads share the
            # in-memory DB.  We serialise writes with a lock at the call site.
            import threading
            self._lock = threading.Lock()
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.executescript(SCHEMA)
            self._persistent_conn.commit()
        else:
            self._lock = None
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()

    @contextmanager
    def _conn(self):
        if self._persistent_conn is not None:
            # In-memory DB — reuse the persistent connection (thread-safe
            # via the lock acquired here).
            if self._lock is not None:
                self._lock.acquire()
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            finally:
                if self._lock is not None:
                    self._lock.release()
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Trade lifecycle
    # ------------------------------------------------------------------
    def record_decision(self, decision: Decision, regime: str = "unknown") -> int:
        """Record an open trade from a Decision."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    decision_id, symbol, direction, confidence, entry, stop_loss,
                    take_profit, thesis, regime, supporting_agents, opposing_agents,
                    decided_at, outcome, data_reliable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 1)
                """,
                (
                    decision.decision_id,
                    decision.symbol,
                    decision.direction.value,
                    float(decision.confidence.score),
                    decision.entry,
                    decision.stop_loss,
                    decision.take_profit,
                    decision.thesis,
                    regime,
                    json.dumps(list(decision.supporting_agents)),
                    json.dumps(list(decision.opposing_agents)),
                    decision.decided_at,
                ),
            )
            return int(cur.lastrowid)

    def close_trade(
        self,
        decision_id: str,
        *,
        exit_price: float,
        pnl_pct: float,
        exit_reason: str,
        agents_correct: List[str],
        agents_wrong: List[str],
        data_reliable: bool = True,
    ) -> None:
        outcome = "win" if pnl_pct > 0 else ("loss" if pnl_pct < 0 else "breakeven")
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE trades SET
                    exit_price = ?, pnl_pct = ?, outcome = ?, exit_reason = ?,
                    closed_at = ?, agents_correct = ?, agents_wrong = ?,
                    data_reliable = ?
                WHERE decision_id = ?
                """,
                (
                    exit_price, pnl_pct, outcome, exit_reason,
                    time.time(), json.dumps(agents_correct), json.dumps(agents_wrong),
                    1 if data_reliable else 0, decision_id,
                ),
            )
            # Update agent_stats
            for agent_id in agents_correct:
                self._bump_agent(conn, agent_id, correct=True, pnl=pnl_pct)
            for agent_id in agents_wrong:
                self._bump_agent(conn, agent_id, correct=False, pnl=pnl_pct)

    def _bump_agent(self, conn, agent_id: str, *, correct: bool, pnl: float) -> None:
        """Insert or update agent_stats row.

        INSERT columns: agent_id, n_calls, n_correct, n_wrong, total_pnl, last_updated
        VALUES placeholders:           ?        ?        ?         ?       ?           ?
        """
        now = time.time()
        n_correct_inc = 1 if correct else 0
        n_wrong_inc = 0 if correct else 1
        # First arg set for INSERT, second for the ON CONFLICT UPDATE
        conn.execute(
            """
            INSERT INTO agent_stats (agent_id, n_calls, n_correct, n_wrong, total_pnl, last_updated)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                n_calls = n_calls + 1,
                n_correct = n_correct + ?,
                n_wrong = n_wrong + ?,
                total_pnl = total_pnl + ?,
                last_updated = ?
            """,
            # INSERT args: agent_id, n_correct, n_wrong, pnl, now
            # UPDATE args: n_correct_inc, n_wrong_inc, pnl, now
            (agent_id, n_correct_inc, n_wrong_inc, pnl, now,
             n_correct_inc, n_wrong_inc, pnl, now),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def agent_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agent_stats").fetchall()
            return {
                row["agent_id"]: {
                    "n_calls": row["n_calls"],
                    "n_correct": row["n_correct"],
                    "n_wrong": row["n_wrong"],
                    "accuracy": (row["n_correct"] / row["n_calls"]) if row["n_calls"] else 0.0,
                    "total_pnl": round(row["total_pnl"], 4),
                    "last_updated": row["last_updated"],
                }
                for row in rows
            }

    def agent_weight(self, agent_id: str, *, clamp: Tuple[float, float] = (0.5, 1.5)) -> float:
        """Compute an adaptive weight for an agent based on historical accuracy.

        Returned value is clamped to ``clamp`` so no agent can dominate
        or be silenced entirely — this is the spec's "do NOT allow
        uncontrolled self-modification" rule.
        """
        stats = self.agent_stats()
        s = stats.get(agent_id)
        if not s or s["n_calls"] < 3:
            return 1.0  # default weight until we have enough data
        accuracy = s["accuracy"]
        # Linear: 0% accuracy -> clamp[0], 100% accuracy -> clamp[1]
        weight = clamp[0] + (clamp[1] - clamp[0]) * accuracy
        return weight

    def recent_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY decided_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def paper_trading_days(self) -> int:
        """Distinct trading days since first open trade — for the 30-day gate."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT date(decided_at, 'unixepoch')) AS n FROM trades"
            ).fetchone()
            return int(row["n"]) if row else 0

    def stats_summary(self) -> Dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS n_trades,
                    SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) AS n_win,
                    SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) AS n_loss,
                    AVG(pnl_pct) AS avg_pnl,
                    SUM(pnl_pct) AS total_pnl
                FROM trades WHERE outcome != 'open'
                """
            ).fetchone()
            if not row or not row["n_trades"]:
                return {"n_trades": 0}
            return {
                "n_trades": row["n_trades"],
                "n_win": row["n_win"],
                "n_loss": row["n_loss"],
                "win_rate": (row["n_win"] / row["n_trades"]) if row["n_trades"] else 0.0,
                "avg_pnl_pct": round(row["avg_pnl"] or 0.0, 4),
                "total_pnl_pct": round(row["total_pnl"] or 0.0, 4),
            }
