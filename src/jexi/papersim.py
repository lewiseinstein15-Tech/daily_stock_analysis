# -*- coding: utf-8 -*-
"""Historical paper-trading simulation for the J.E.X.I. loop.

Each *scenario ticker* receives one recommended position for the scenario
window (produced by the Jexi orchestrator from the specialist consensus).
This simulator walks the daily bars with stop-loss / take-profit / max-holding
rules and risk-based position sizing (default ≤2% risk per trade), then
returns an equity curve plus closed trades for metrics.

Everything here is in-sample *fake money*; output is used only by the
self-improvement loop and reports.  See ``src/core/backtest_engine.py`` for
the repository's other evaluation path (stored analysis vs subsequent price).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class SignalPlan:
    code: str
    name: str = ""
    signal: str = "flat"          # long | flat | short
    target_direction: Optional[str] = None
    confidence: float = 0.0
    stop_loss_pct: float = 0.08   # max loss per trade, fraction of entry
    take_profit_pct: float = 0.15
    max_holding_days: int = 20
    entry_price: float = 0.0


@dataclass
class Trade:
    code: str
    name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    reason: str
    days_held: int = 0
    direction: str = "long"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "pnl_pct": round(self.pnl_pct, 4),
            "reason": self.reason,
            "days_held": self.days_held,
            "direction": self.direction,
        }


@dataclass
class SimulationResult:
    equity_series: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)


def _date_key(value) -> str:
    return str(value)[:10]


def simulate_plans(
    plans: List[SignalPlan],
    frames: Dict[str, pd.DataFrame],
    *,
    start_cash: float = 100_000.0,
    risk_per_trade: float = 0.02,
    max_position_fraction: float = 0.25,
) -> SimulationResult:
    """Simulate all plans against their daily frames on a shared calendar.

    Position sizing: ``fraction = min(risk_per_trade / stop_distance,
    max_position_fraction)``.  One open position is allowed per ticker at a
    time; a ticker enters at most once per simulation call (i.e. per
    rebalance) so stop/take-profit exits cannot be re-opened the next day
    and compound the same signal.  Equity compounds daily across open
    positions.
    """
    result = SimulationResult()
    if not plans:
        result.equity_series = [start_cash]
        return result

    active: Dict[str, Trade] = {}
    fractions: Dict[str, float] = {}
    already_entered: set = set()
    entry_day_no: Dict[str, int] = {}
    prev_mark: Dict[str, float] = {}

    all_dates: List[str] = []
    for frame in frames.values():
        if frame is None or frame.empty:
            continue
        for value in frame["date"]:
            day = _date_key(value)
            if day not in all_dates:
                all_dates.append(day)
    all_dates.sort()

    equity = start_cash
    equity_by_day: List[float] = []
    dates_by_day: List[str] = []

    # Precompute a per-code day -> row-index map to keep the loop O(n).
    day_index = {
        code: dict(zip(frames[code]["date"].astype(str).map(_date_key), range(len(frames[code]))))
        for code in frames
        if frames.get(code) is not None and not frames[code].empty
    }

    for day_no, day in enumerate(all_dates):
        for plan in plans:
            frame = frames.get(plan.code)
            if frame is None or frame.empty:
                continue
            row_index = (day_index.get(plan.code) or {}).get(day)
            if row_index is None:
                continue
            row = frame.iloc[row_index]
            close = float(row["close"])
            low = float(row["low"] if "low" in row else close)
            high = float(row["high"] if "high" in row else close)

            trade = active.get(plan.code)
            if trade is not None:
                entry = trade.entry_price
                if trade.reason == "open" and trade.direction == "long":
                    stop = entry * (1.0 - plan.stop_loss_pct)
                    target = entry * (1.0 + plan.take_profit_pct)
                    reason = None
                    if low <= stop:
                        reason = "stop_loss"
                    elif high >= target:
                        reason = "take_profit"
                    elif day_no - entry_day_no.get(plan.code, day_no) >= max(plan.max_holding_days, 1):
                        reason = "max_holding"
                        exit_price = close
                    if reason:
                        exit_price = stop if reason == "stop_loss" else target if reason == "take_profit" else close
                        trade.pnl_pct = exit_price / entry - 1.0
                        trade.exit_price = exit_price
                        trade.exit_date = day
                        trade.reason = reason
                        trade.days_held = day_no - entry_day_no.get(plan.code, day_no)
                        result.trades.append(trade)
                        del active[plan.code]
                        del fractions[plan.code]
                        del prev_mark[plan.code]
                elif trade.reason == "open" and trade.direction == "short":
                    stop = entry * (1.0 + plan.stop_loss_pct)
                    target = entry * (1.0 - plan.take_profit_pct)
                    reason = None
                    if high >= stop:
                        reason = "stop_loss"
                    elif low <= target:
                        reason = "take_profit"
                    elif day_no - entry_day_no.get(plan.code, day_no) >= max(plan.max_holding_days, 1):
                        reason = "max_holding"
                        exit_price = close
                    if reason:
                        exit_price = stop if reason == "stop_loss" else target if reason == "take_profit" else close
                        trade.pnl_pct = 1.0 - exit_price / entry
                        trade.exit_price = exit_price
                        trade.exit_date = day
                        trade.reason = reason
                        trade.days_held = day_no - entry_day_no.get(plan.code, day_no)
                        result.trades.append(trade)
                        del active[plan.code]
                        del fractions[plan.code]
                        del prev_mark[plan.code]
        # Apply each day's mark-to-market **delta** on open positions
        # (cumulative gain since entry must not be re-multiplied daily).
        day_pnl = 0.0
        for code, trade in list(active.items()):
            frame = frames.get(code)
            if frame is None or frame.empty:
                continue
            row_index = (day_index.get(code) or {}).get(day)
            if row_index is None:
                continue
            day_close = float(frame.iloc[row_index]["close"])
            frac = fractions.get(code, 0.0)
            previous = prev_mark.get(code, trade.entry_price)
            if day_close == previous:
                continue
            if trade.direction == "long":
                day_pnl += frac * (day_close - previous) / previous
            elif trade.direction == "short":
                day_pnl += frac * (previous - day_close) / previous
            prev_mark[code] = day_close
        equity *= 1.0 + day_pnl
        equity_by_day.append(equity)
        dates_by_day.append(day)

        for plan in plans:
            if plan.code in already_entered or plan.signal not in ("long", "short"):
                continue
            frame = frames.get(plan.code)
            if frame is None or frame.empty:
                continue
            rows = frame[frame["date"].astype(str).map(_date_key) == day]
            if rows.empty:
                continue
            row = rows.iloc[0]
            entry = float(row["close"])
            if entry <= 0:
                continue
            stop_distance = max(plan.stop_loss_pct, 0.01)
            fraction = min(risk_per_trade / stop_distance, max_position_fraction)
            trade = Trade(
                code=plan.code,
                name=plan.name,
                entry_date=day,
                exit_date="",
                entry_price=entry,
                exit_price=entry,
                pnl_pct=0.0,
                reason="open",
            )
            trade.direction = plan.signal
            active[plan.code] = trade
            fractions[plan.code] = fraction
            already_entered.add(plan.code)
            entry_day_no[plan.code] = day_no
            prev_mark[plan.code] = entry

    # Close anything still open at the last bar.
    last_frame_by_code = {c: f for c, f in frames.items() if f is not None and not f.empty}
    for code, trade in list(active.items()):
        frame = last_frame_by_code.get(code)
        if frame is None:
            continue
        last = frame.iloc[-1]
        trade.exit_price = float(last["close"])
        trade.pnl_pct = (
            1.0 - trade.exit_price / trade.entry_price
            if trade.direction == "short"
            else trade.exit_price / trade.entry_price - 1.0
        )
        trade.exit_date = _date_key(last["date"])
        trade.reason = "end_of_window"
        result.trades.append(trade)

    result.equity_series = equity_by_day or [start_cash]
    result.dates = dates_by_day
    return result


def build_signals_from_opinions(opinions: Dict[str, List], weight_fn=None) -> List[SignalPlan]:
    """Convert per-code specialist opinions into one consensus SignalPlan each.

    Consensus = confidence-weighted average score; direction follows the sign
    of the weighted score; conviction threshold filters flattish calls.
    """
    plans: List[SignalPlan] = []
    for code, opinion_list in opinions.items():
        if not opinion_list:
            continue
        total_w = 0.0
        weighted = 0.0
        for op in opinion_list:
            w = op["confidence"] if weight_fn is None else weight_fn(op)
            weighted += w * op["score"]
            total_w += w
        consensus = weighted / total_w if total_w > 0 else 0.0
        conf = min(1.0, 0.4 + 0.5 * abs(consensus))
        signal = "long" if consensus >= 0.06 else ("short" if consensus <= -0.06 else "flat")
        plans.append(
            SignalPlan(
                code=code,
                name=op["name"] if opinion_list else code,
                signal=signal,
                target_direction="up" if signal == "long" else ("down" if signal == "short" else None),
                confidence=round(conf, 4),
            )
        )
    return plans
