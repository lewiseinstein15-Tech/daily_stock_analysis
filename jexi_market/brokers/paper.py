# -*- coding: utf-8 -*-
"""Offline paper broker — a persistent, deterministic trading simulator.

Unlike the Alpaca paper account, this broker needs **no credentials and
no network**: orders fill instantly at the provided reference price with
configurable slippage and commission, positions persist in SQLite, and
stop-loss / take-profit legs are evaluated on every
:meth:`PaperBroker.process_fills` call (the 24/7 runner feeds it prices
each cycle).

This is what makes JEXI Market runnable 24/7 from day zero — you can
validate the full pipeline (scan → decision → gate → order → exit →
memory) before ever wiring a real brokerage account.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from jexi_market.brokers.base import Broker, BrokerAccount, BrokerOrder, BrokerPosition

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orders (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    order_type TEXT,
    status TEXT,
    filled_qty REAL DEFAULT 0,
    filled_avg_price REAL,
    stop_loss REAL,
    take_profit REAL,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS paper_positions (
    symbol TEXT PRIMARY KEY,
    qty REAL NOT NULL,
    side TEXT NOT NULL,
    avg_entry REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS paper_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class PaperBroker(Broker):
    """SQLite-backed paper trading simulator implementing :class:`Broker`."""

    name = "paper"
    supports_bracket_orders = True   # stops/TPs tracked locally

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        starting_cash: float = 100_000.0,
        slippage_bps: float = 5.0,
        commission_bps: float = 0.0,
        price_provider: Optional[Any] = None,
    ):
        self.db_path = db_path or "data/jexi_market/paper_broker.sqlite"
        self.slippage_rate = slippage_bps / 10_000.0
        self.commission_rate = commission_bps / 10_000.0
        # Optional callable(symbol) -> float used when no explicit price
        # is passed to submit_order (e.g. the MarketDataClient).
        self.price_provider = price_provider
        self._lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT value FROM paper_meta WHERE key = 'cash'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO paper_meta (key, value) VALUES ('cash', ?)",
                    (str(starting_cash),),
                )
                self._conn.commit()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return True

    def _cash(self) -> float:
        row = self._conn.execute(
            "SELECT value FROM paper_meta WHERE key = 'cash'"
        ).fetchone()
        return float(row["value"]) if row else 0.0

    def _set_cash(self, value: float) -> None:
        self._conn.execute(
            "INSERT INTO paper_meta (key, value) VALUES ('cash', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(value),),
        )

    def _reference_price(self, symbol: str, explicit: Optional[float]) -> float:
        if explicit and explicit > 0:
            return float(explicit)
        if self.price_provider is not None:
            try:
                p = float(self.price_provider(symbol))  # type: ignore[misc]
                if p > 0:
                    return p
            except Exception:
                pass
        # Fall back to the last known fill price for the symbol.
        row = self._conn.execute(
            "SELECT filled_avg_price FROM paper_orders "
            "WHERE symbol = ? AND filled_avg_price IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row and row["filled_avg_price"]:
            return float(row["filled_avg_price"])
        raise ValueError(f"no price available for paper fill: {symbol}")

    # ------------------------------------------------------------------
    # account / positions
    # ------------------------------------------------------------------
    def get_account(self) -> BrokerAccount:
        with self._lock:
            cash = self._cash()
            positions = self._positions_rows()
        positions_value = sum(r["qty"] * r["avg_entry"] for r in positions)
        # Mark-to-market using current prices when available.
        mtm = 0.0
        for r in positions:
            try:
                px = self._reference_price(r["symbol"], None)
            except ValueError:
                px = r["avg_entry"]
            mtm += r["qty"] * px
        equity = cash + mtm if positions else cash + positions_value
        return BrokerAccount(
            equity=equity if positions else cash,
            cash=cash,
            buying_power=cash,
            positions_value=mtm if positions else 0.0,
            paper=True,
        )

    def _positions_rows(self) -> List[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM paper_positions").fetchall()

    def get_positions(self) -> List[BrokerPosition]:
        out: List[BrokerPosition] = []
        with self._lock:
            rows = self._positions_rows()
        for r in rows:
            try:
                px = self._reference_price(r["symbol"], None)
            except ValueError:
                px = r["avg_entry"]
            mv = r["qty"] * px
            cb = r["qty"] * r["avg_entry"]
            pl = mv - cb if r["side"] == "long" else cb - mv
            out.append(BrokerPosition(
                symbol=r["symbol"],
                qty=r["qty"],
                side=r["side"],
                market_value=mv,
                cost_basis=cb,
                unrealized_pl=pl,
                unrealized_plpc=(pl / cb) if cb else 0.0,
                current_price=px,
            ))
        return out

    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> BrokerOrder:
        """Fill a market order instantly at reference price ± slippage.

        Extra kwargs ``stop_loss`` / ``take_profit`` attach local exit
        legs (stored on the position; evaluated in ``process_fills``).
        """
        qty = round(max(0.0, float(qty)), 4)
        if qty <= 0:
            raise ValueError("paper order qty must be > 0")

        # Long-only paper policy: a SELL with nothing held is rejected
        # immediately (no price lookup needed).
        with self._lock:
            if side == "sell":
                row = self._conn.execute(
                    "SELECT * FROM paper_positions WHERE symbol = ?", (symbol,)
                ).fetchone()
                held = row["qty"] if (row and row["side"] == "long") else 0.0
                if held <= 0:
                    order = BrokerOrder(
                        id=f"paper_{uuid.uuid4().hex[:12]}", status="rejected",
                        symbol=symbol, qty=qty, side=side, type=order_type,
                        created_at=str(time.time()),
                        raw={"reason": "no_position_to_sell"},
                    )
                    self._record_order(order, None, None)
                    return order

        px = self._reference_price(symbol, limit_price if order_type == "limit" else None)
        if side == "buy":
            fill_px = px * (1.0 + self.slippage_rate)
        else:
            fill_px = px * (1.0 - self.slippage_rate)

        sell_qty = 0.0
        order_id = f"paper_{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            cash = self._cash()
            notional = qty * fill_px
            commission = notional * self.commission_rate
            if side == "buy":
                if notional + commission > cash + 1e-9:
                    # Auto-reject: insufficient paper funds.
                    order = BrokerOrder(
                        id=order_id, status="rejected", symbol=symbol,
                        qty=qty, side=side, type=order_type,
                        created_at=str(now),
                        raw={"reason": "insufficient_cash"},
                    )
                    self._record_order(order, stop_loss, take_profit)
                    return order
                cash -= notional + commission
                self._set_cash(cash)
                self._apply_fill_position(symbol, "long", qty, fill_px, stop_loss, take_profit)
            else:
                # Selling: only what we hold (long-only paper policy).
                row = self._conn.execute(
                    "SELECT * FROM paper_positions WHERE symbol = ?", (symbol,)
                ).fetchone()
                held = row["qty"] if (row and row["side"] == "long") else 0.0
                sell_qty = min(qty, held)
                if sell_qty <= 0:
                    order = BrokerOrder(
                        id=order_id, status="rejected", symbol=symbol,
                        qty=qty, side=side, type=order_type,
                        created_at=str(now),
                        raw={"reason": "no_position_to_sell"},
                    )
                    self._record_order(order, stop_loss, take_profit)
                    return order
                proceeds = sell_qty * fill_px - commission
                cash += proceeds
                self._set_cash(cash)
                remaining = held - sell_qty
                if remaining <= 1e-9:
                    self._conn.execute("DELETE FROM paper_positions WHERE symbol = ?", (symbol,))
                else:
                    self._conn.execute(
                        "UPDATE paper_positions SET qty = ?, updated_at = ? WHERE symbol = ?",
                        (remaining, now, symbol),
                    )
            order = BrokerOrder(
                id=order_id, status="filled", symbol=symbol,
                qty=qty, side=side, type=order_type,
                filled_qty=sell_qty if side == "sell" else qty,
                filled_avg_price=fill_px,
                created_at=str(now),
                raw={"commission": round(commission, 4)},
            )
            self._record_order(order, stop_loss, take_profit)
            self._conn.commit()
        return order

    def _apply_fill_position(
        self,
        symbol: str,
        side: str,
        qty: float,
        px: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> None:
        now = time.time()
        row = self._conn.execute(
            "SELECT * FROM paper_positions WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO paper_positions (symbol, qty, side, avg_entry, stop_loss, take_profit, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, qty, side, px, stop_loss, take_profit, now),
            )
        else:
            total_qty = row["qty"] + qty
            avg = (row["avg_entry"] * row["qty"] + px * qty) / total_qty
            self._conn.execute(
                "UPDATE paper_positions SET qty = ?, avg_entry = ?, stop_loss = COALESCE(?, stop_loss), "
                "take_profit = COALESCE(?, take_profit), updated_at = ? WHERE symbol = ?",
                (total_qty, avg, stop_loss, take_profit, now, symbol),
            )

    def _record_order(self, order: BrokerOrder, stop_loss, take_profit) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO paper_orders (id, symbol, side, qty, order_type, status, filled_qty, "
            "filled_avg_price, stop_loss, take_profit, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.id, order.symbol, order.side, order.qty, order.type, order.status,
                order.filled_qty, order.filled_avg_price, stop_loss, take_profit,
                time.time(), time.time(),
            ),
        )
        self._conn.commit()

    def get_order(self, order_id: str) -> BrokerOrder:
        row = self._conn.execute(
            "SELECT * FROM paper_orders WHERE id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return BrokerOrder(
            id=row["id"], status=row["status"], symbol=row["symbol"],
            qty=row["qty"], side=row["side"], type=row["order_type"] or "market",
            filled_qty=row["filled_qty"] or 0.0,
            filled_avg_price=row["filled_avg_price"],
            created_at=str(row["created_at"]),
        )

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE paper_orders SET status = 'canceled', updated_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (time.time(), order_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def submit_bracket_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        time_in_force: str = "day",
    ) -> BrokerOrder:
        return self.submit_order(
            symbol, qty, side, time_in_force=time_in_force,
            stop_loss=stop_loss, take_profit=take_profit,
        )

    # ------------------------------------------------------------------
    # Local stop / take-profit engine
    # ------------------------------------------------------------------
    def process_fills(self, prices: Dict[str, float]) -> List[BrokerOrder]:
        """Evaluate local stop-loss / take-profit legs for all positions.

        ``prices`` maps symbol -> latest price.  Returns the list of
        exit orders that fired (already filled, positions updated).
        """
        fired: List[BrokerOrder] = []
        with self._lock:
            rows = self._positions_rows()
        for row in rows:
            px = prices.get(row["symbol"])
            if not px:
                continue
            exit_reason = None
            if row["stop_loss"] and row["side"] == "long" and px <= row["stop_loss"]:
                exit_reason = "stop_loss"
            elif row["take_profit"] and row["side"] == "long" and px >= row["take_profit"]:
                exit_reason = "take_profit"
            if exit_reason:
                order = self.submit_order(row["symbol"], row["qty"], "sell")
                if order.status == "filled":
                    order.raw["exit_reason"] = exit_reason
                    fired.append(order)
        return fired

    # ------------------------------------------------------------------
    # market data passthrough
    # ------------------------------------------------------------------
    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            return self._reference_price(symbol, None)
        except ValueError:
            return None

    def is_market_open(self) -> bool:
        return True

    def reset(self, starting_cash: float = 100_000.0) -> None:
        """Wipe the simulator (testing convenience)."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM paper_orders; DELETE FROM paper_positions;"
            )
            self._set_cash(starting_cash)
            self._conn.commit()
