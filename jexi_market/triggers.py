# -*- coding: utf-8 -*-
"""TriggerEngine — JEXI trades at the RIGHT time, not at a set time.

Instead of running the expensive agent pipeline on a fixed clock, the
TriggerEngine watches the whole universe with cheap indicator checks and
emits **opportunity events** only when market conditions actually line
up.  The heavy analysis (agents, risk gate, orders) wakes up *only* when
something interesting happens — exactly how a good human trader works.

Trigger families (all deterministic — zero LLM involvement):

=====================  ====================================================
kind                   fires when
=====================  ====================================================
breakout_proximity     price within X% of the 20-day Donchian high
momentum_burst         strong short-term move with volume confirmation
oversold_bounce        RSI was oversold and is now turning up
overbought_fade        RSI was overbought and is now rolling over
volatility_squeeze     Bollinger bandwidth at a multi-day low (coil)
trend_pullback         uptrend pulls back to the rising SMA20
volume_spike           volume far above its 20-day average
gap_event              open gapped away from yesterday's close
near_stop / near_target  held position approaching exit (exit timing!)
=====================  ====================================================

Every event carries a ``plain_reason`` — an everyday-English sentence
composed at trigger time — so notifications can be understood by anyone
(no jargon) and the audit log stays self-explanatory.

Cooldowns: the same (symbol, kind) pair will not re-fire within
``cooldown_seconds`` (default 2h) so the watcher can poll every minute
without spamming the pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from jexi_market.config import MarketConfig
from jexi_market.data import MarketDataClient, MarketSnapshot
from jexi_market.indicators import FactorSnapshot, compute_factors


def _money(amount) -> str:
    try:
        return f"${float(amount):,.2f}"
    except (TypeError, ValueError):
        return ""

logger = logging.getLogger(__name__)


@dataclass
class TriggerEvent:
    """One opportunity the watcher spotted."""

    symbol: str
    kind: str
    score: float                       # 0..1 — how compelling
    priority: int                      # 1 (low) .. 5 (urgent)
    direction_hint: str                # "up" | "down" | "either"
    plain_reason: str                  # everyday-English sentence
    price: Optional[float] = None
    triggered_at: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "score": round(self.score, 4),
            "priority": self.priority,
            "direction_hint": self.direction_hint,
            "plain_reason": self.plain_reason,
            "price": self.price,
            "triggered_at": self.triggered_at,
            "meta": self.meta,
        }


@dataclass
class TriggerConfig:
    """Thresholds for every trigger family."""

    # breakout_proximity
    breakout_buffer: float = 0.015          # within 1.5% of the 20d high
    # momentum_burst
    momentum_threshold: float = 0.05        # |5d move| > 5%
    momentum_volume_ratio: float = 1.3      # with 5d/20d volume > 1.3x
    # rsi families
    rsi_oversold: float = 32.0
    rsi_overbought: float = 68.0
    # volatility_squeeze
    squeeze_window: int = 20
    squeeze_ratio: float = 0.60             # bandwidth < 60% of its window avg
    # trend_pullback
    pullback_tolerance: float = 0.02        # within 2% of SMA20
    # volume_spike
    volume_spike_ratio: float = 2.5
    # gap_event
    gap_threshold: float = 0.03             # 3% gap vs previous close
    # exits
    near_stop_fraction: float = 0.15        # within 15% of the way to stop
    near_target_fraction: float = 0.85      # covered 85% of the way to target
    # engine
    min_rows: int = 25
    cooldown_seconds: int = 2 * 60 * 60     # 2 hours per (symbol, kind)
    max_events_per_scan: int = 10


class TriggerEngine:
    """Watch a universe cheaply; emit opportunity events when they appear."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        data_client: Optional[MarketDataClient] = None,
        trigger_config: Optional[TriggerConfig] = None,
        *,
        cooldown_store: Optional[Dict[Tuple[str, str], float]] = None,
        clock: Any = time.time,
    ):
        self.config = config or MarketConfig()
        self.data = data_client or MarketDataClient()
        self.tcfg = trigger_config or TriggerConfig()
        # (symbol, kind) -> last fired epoch.  Injectable so tests (and a
        # future persistent store) can supply their own mapping.
        self._cooldowns: Dict[Tuple[str, str], float] = (
            cooldown_store if cooldown_store is not None else {}
        )
        self._clock = clock
        # last factors per symbol lets callers enrich exits (stop/target)
        self.last_factors: Dict[str, FactorSnapshot] = {}
        # v0.4.1: how many symbols in the last evaluate_universe scan were
        # unusable (fetch failed / too few rows).  The runner uses this as
        # a data-quality outage signal — a blind watcher must not look
        # identical to a quiet market.
        self.last_scan_failures: int = 0
        self._scan_failures: int = 0

    # ------------------------------------------------------------------
    # cooldown
    # ------------------------------------------------------------------
    def _cooled_down(self, symbol: str, kind: str) -> bool:
        last = self._cooldowns.get((symbol, kind))
        if last is None:
            return True
        return (self._clock() - last) >= self.tcfg.cooldown_seconds

    def _mark(self, symbol: str, kind: str) -> None:
        self._cooldowns[(symbol, kind)] = self._clock()

    # ------------------------------------------------------------------
    # main entry points
    # ------------------------------------------------------------------
    def evaluate_symbol(
        self,
        symbol: str,
        snapshot: Optional[MarketSnapshot] = None,
        *,
        open_trade: Optional[Dict[str, Any]] = None,
    ) -> List[TriggerEvent]:
        """Run every trigger against one symbol.

        ``open_trade`` (optional memory record with entry/stop/take_profit)
        enables the exit-timing triggers (near_stop / near_target).
        """
        if snapshot is None:
            snapshot = self.data.get_daily(symbol, days=self.config.scanner_lookback_days)
        if not snapshot.ok or snapshot.df is None or len(snapshot.df) < self.tcfg.min_rows:
            self._scan_failures += 1
            return []

        factors = compute_factors(snapshot.df, symbol=symbol)
        self.last_factors[symbol] = factors
        events: List[TriggerEvent] = []
        price = factors.latest_close

        # -- breakout proximity (bull) ---------------------------------
        # Requires the price to actually be RISING into the high — a flat
        # market always trades "at its own 20d high" and must not fire.
        if factors.donchian_high_20 and price:
            dist = (factors.donchian_high_20 - price) / price
            closes_now = [float(x) for x in snapshot.df["close"].dropna().tolist()]
            rising_into_high = len(closes_now) >= 6 and closes_now[-1] > closes_now[-6]
            if 0.0 <= dist <= self.tcfg.breakout_buffer and rising_into_high:
                events.append(TriggerEvent(
                    symbol=symbol, kind="breakout_proximity",
                    score=0.8, priority=4, direction_hint="up",
                    plain_reason=(
                        f"{symbol} is trading near its highest price of the "
                        f"last month (${price:,.2f} vs a one-month high of "
                        f"${factors.donchian_high_20:,.2f}). When a stock "
                        f"pushes through a level like this it often keeps going."
                    ),
                    price=price,
                    meta={"distance_to_high": round(dist, 5)},
                ))

        # -- momentum burst (either direction, volume confirmed) -------
        if abs(factors.momentum_3d) >= self.tcfg.momentum_threshold and \
                factors.volume_ratio_5_20 >= self.tcfg.momentum_volume_ratio:
            up = factors.momentum_3d > 0
            events.append(TriggerEvent(
                symbol=symbol, kind="momentum_burst",
                score=0.7, priority=3, direction_hint="up" if up else "down",
                plain_reason=(
                    f"{symbol} moved {abs(factors.momentum_3d) * 100:.1f}% in "
                    f"just 3 days {'up' if up else 'down'} on unusually heavy "
                    f"trading ({factors.volume_ratio_5_20:.1f}x the normal "
                    f"amount). Big moves on big volume usually mean large "
                    f"investors are acting."
                ),
                price=price,
                meta={"momentum_3d": round(factors.momentum_3d, 4)},
            ))

        # -- oversold bounce (bull) ------------------------------------
        if factors.rsi_14 is not None:
            rsi = factors.rsi_14
            closes = [float(x) for x in snapshot.df["close"].dropna().tolist()]
            prev_rsi = _prev_rsi(closes, period=14)
            if rsi < self.tcfg.rsi_oversold and prev_rsi is not None and rsi > prev_rsi:
                events.append(TriggerEvent(
                    symbol=symbol, kind="oversold_bounce",
                    score=0.65, priority=3, direction_hint="up",
                    plain_reason=(
                        f"{symbol} has been sold off hard recently and is "
                        f"starting to turn back up (its bounce-meter read "
                        f"{rsi:.0f}, up from {prev_rsi:.0f}). Stocks this "
                        f"beaten-down sometimes snap back quickly."
                    ),
                    price=price,
                    meta={"rsi": round(rsi, 2), "prev_rsi": round(prev_rsi, 2)},
                ))
            # -- overbought fade (bear) --------------------------------
            elif rsi > self.tcfg.rsi_overbought and prev_rsi is not None and rsi < prev_rsi:
                events.append(TriggerEvent(
                    symbol=symbol, kind="overbought_fade",
                    score=0.6, priority=2, direction_hint="down",
                    plain_reason=(
                        f"{symbol} shot up very fast and is now starting to "
                        f"cool off (its heat-meter read {rsi:.0f}, down from "
                        f"{prev_rsi:.0f}). Quick climbers often give some of "
                        f"it back."
                    ),
                    price=price,
                    meta={"rsi": round(rsi, 2), "prev_rsi": round(prev_rsi, 2)},
                ))

        # -- volatility squeeze (either) -------------------------------
        bw = _bollinger_bandwidth(snapshot.df)
        if bw is not None and len(bw) >= self.tcfg.squeeze_window:
            recent = bw[-1]
            avg = sum(bw[-self.tcfg.squeeze_window:]) / self.tcfg.squeeze_window
            if avg > 0 and recent < avg * self.tcfg.squeeze_ratio:
                events.append(TriggerEvent(
                    symbol=symbol, kind="volatility_squeeze",
                    score=0.55, priority=2, direction_hint="either",
                    plain_reason=(
                        f"{symbol} has gone unusually quiet — its price is "
                        f"coiling into a tighter and tighter range. Periods "
                        f"like this often end with a sharp move; JEXI will "
                        f"be ready either way."
                    ),
                    price=price,
                    meta={"bandwidth": round(recent, 5), "avg": round(avg, 5)},
                ))

        # -- trend pullback (bull) --------------------------------------
        if factors.sma_20 and factors.sma_50 and price:
            in_uptrend = factors.sma_20 > factors.sma_50
            near_sma20 = abs(price - factors.sma_20) / factors.sma_20 <= self.tcfg.pullback_tolerance
            if in_uptrend and near_sma20:
                events.append(TriggerEvent(
                    symbol=symbol, kind="trend_pullback",
                    score=0.6, priority=3, direction_hint="up",
                    plain_reason=(
                        f"{symbol} has been in a steady uptrend and just "
                        f"dipped back to a level where it has historically "
                        f"found buyers (around ${factors.sma_20:,.2f}). "
                        f"Buying dips in an uptrend is one of the most "
                        f"reliable patterns there is."
                    ),
                    price=price,
                    meta={"sma20": round(factors.sma_20, 2), "sma50": round(factors.sma_50, 2)},
                ))

        # -- volume spike (either) ---------------------------------------
        if factors.volume_ratio_5_20 >= self.tcfg.volume_spike_ratio:
            events.append(TriggerEvent(
                symbol=symbol, kind="volume_spike",
                score=0.5, priority=2, direction_hint="either",
                plain_reason=(
                    f"{symbol} traded {factors.volume_ratio_5_20:.1f}x its "
                    f"normal volume today. Something is happening — worth "
                    f"taking a closer look."
                ),
                price=price,
                meta={"volume_ratio": round(factors.volume_ratio_5_20, 3)},
            ))

        # -- gap event ----------------------------------------------------
        gap = _gap_ratio(snapshot.df)
        if gap is not None and abs(gap) >= self.tcfg.gap_threshold:
            up = gap > 0
            events.append(TriggerEvent(
                symbol=symbol, kind="gap_event",
                score=0.6, priority=3, direction_hint="up" if up else "down",
                plain_reason=(
                    f"{symbol} opened {'higher' if up else 'lower'} today than "
                    f"it closed yesterday by {abs(gap) * 100:.1f}% — a sudden "
                    f"jump that usually follows news. JEXI is checking what "
                    f"is going on."
                ),
                price=price,
                meta={"gap": round(gap, 4)},
            ))

        # -- exit timing for held positions -------------------------------
        if open_trade and price:
            events.extend(self._exit_triggers(symbol, open_trade, price))

        # cooldown filter + marking
        fired: List[TriggerEvent] = []
        for ev in events:
            if not self._cooled_down(ev.symbol, ev.kind):
                continue
            self._mark(ev.symbol, ev.kind)
            fired.append(ev)

        fired.sort(key=lambda e: (e.priority, e.score), reverse=True)
        return fired[: self.tcfg.max_events_per_scan]

    # ------------------------------------------------------------------
    def _exit_triggers(
        self, symbol: str, trade: Dict[str, Any], price: float
    ) -> List[TriggerEvent]:
        """near_stop / near_target for an open position.

        near_stop: price has travelled >= 75% of the way from entry to
        the stop (long or short) — i.e. the safety net is close.
        near_target: price has covered >= 85% of the entry->target span.
        """
        entry = float(trade.get("entry_price") or trade.get("entry") or 0.0)
        stop = float(trade.get("stop_loss") or 0.0)
        target = float(trade.get("take_profit") or 0.0)
        direction = str(trade.get("direction") or "long")
        out: List[TriggerEvent] = []
        if entry <= 0:
            return out

        if stop > 0:
            if direction == "long" and entry > stop and price < entry:
                progress = (entry - price) / (entry - stop)
            elif direction != "long" and stop > entry and price > entry:
                progress = (price - entry) / (stop - entry)
            else:
                progress = 0.0
            if progress >= 0.75:
                out.append(TriggerEvent(
                    symbol=symbol, kind="near_stop", score=0.9, priority=5,
                    direction_hint="down" if direction == "long" else "up",
                    plain_reason=(
                        f"Heads up: {symbol} has moved most of the way "
                        f"toward the safety net JEXI set when it bought in. "
                        f"If it goes further the wrong way, JEXI will sell "
                        f"automatically so a small loss cannot turn into a "
                        f"big one."
                    ),
                    price=price, meta={"stop": stop, "entry": entry},
                ))
        if target > 0:
            if direction == "long" and target > entry and price > entry:
                gained = (price - entry) / (target - entry)
            elif direction != "long" and target < entry and price < entry:
                gained = (entry - price) / (entry - target)
            else:
                gained = 0.0
            if gained >= self.tcfg.near_target_fraction:
                out.append(TriggerEvent(
                    symbol=symbol, kind="near_target", score=0.85, priority=4,
                    direction_hint="up" if direction == "long" else "down",
                    plain_reason=(
                        f"Good news: {symbol} has come most of the way to "
                        f"the goal price JEXI set when it bought "
                        f"({_money(target)}). JEXI is watching closely and "
                        f"will lock in the profit at the right moment."
                    ),
                    price=price, meta={"target": target, "entry": entry},
                ))
        return out

    # ------------------------------------------------------------------
    def evaluate_universe(
        self,
        symbols: List[str],
        *,
        open_trades: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[TriggerEvent]:
        """Scan the whole universe; return events sorted by urgency.

        After the scan, ``self.last_scan_failures`` holds how many
        symbols could not be evaluated (bad fetch / too few rows) so
        callers can distinguish a quiet market from a data outage.
        """
        open_trades = open_trades or {}
        all_events: List[TriggerEvent] = []
        self._scan_failures = 0
        for symbol in symbols:
            try:
                all_events.extend(self.evaluate_symbol(
                    symbol, open_trade=open_trades.get(symbol)))
            except Exception as exc:  # one bad symbol never kills the watch
                self._scan_failures += 1
                logger.warning("trigger evaluation failed for %s: %s", symbol, exc)
        self.last_scan_failures = self._scan_failures
        all_events.sort(key=lambda e: (e.priority, e.score), reverse=True)
        return all_events


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _prev_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """RSI of closes[:-1] (yesterday's RSI) — minimal Wilder implementation."""
    if len(closes) < period + 2:
        return None
    seq = closes[:-1]
    gains, losses = [], []
    for i in range(1, len(seq)):
        change = seq[i] - seq[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger_bandwidth(df, period: int = 20) -> Optional[List[float]]:
    """Rolling Bollinger bandwidth ((upper-lower)/middle) series."""
    if df is None or "close" not in df.columns or len(df) < period:
        return None
    try:
        import pandas as pd
        closes = pd.Series([float(x) for x in df["close"].dropna().tolist()])
        mid = closes.rolling(period).mean()
        std = closes.rolling(period).std()
        upper = mid + 2.0 * std
        lower = mid - 2.0 * std
        bandwidth = (upper - lower) / mid
        return [float(x) for x in bandwidth.dropna().tolist()]
    except Exception:
        return None


def _gap_ratio(df) -> Optional[float]:
    """Today's open vs yesterday's close (fraction)."""
    if df is None or len(df) < 2:
        return None
    try:
        if "open" not in df.columns or "close" not in df.columns:
            return None
        prev_close = float(df["close"].iloc[-2])
        today_open = float(df["open"].iloc[-1])
        if prev_close <= 0:
            return None
        return (today_open - prev_close) / prev_close
    except (IndexError, TypeError, ValueError):
        return None
