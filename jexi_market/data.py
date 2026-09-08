# -*- coding: utf-8 -*-
"""Market-data adapter for JEXI Market.

JEXI Market does NOT reinvent the data layer — the repository already
ships a battle-tested multi-source fetcher (``data_provider.DataFetcherManager``
with AkShare/Baostock/YFinance/Tushare/Longbridge/Futu/TickFlow adapters
and graceful fallback).  This module is a thin, typed adapter that:

1. Tries the repository's ``DataFetcherManager`` first.
2. Falls back to ``yfinance`` directly when the manager import fails
   (common in lightweight test environments) — same library the repo uses.
3. Normalises every result to a :class:`MarketSnapshot` with explicit
   provenance, freshness and confidence metadata, per the JEXI Market
   spec section 16 (data quality).

The adapter NEVER fabricates data.  If both providers fail, it returns a
snapshot with ``ok=False`` and the agents downstream treat that as
"unavailable" rather than guessing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Normalised OHLCV frame + provenance metadata.

    ``ok=False`` means data was unavailable.  Downstream agents MUST
    treat ``ok=False`` as "do not analyse" — never as "assume flat".
    """

    symbol: str
    ok: bool = False
    df: Optional[pd.DataFrame] = None
    provider: str = ""
    rows: int = 0
    fetched_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    freshness_score: float = 0.0    # 0..1

    @property
    def latest_price(self) -> Optional[float]:
        if not self.ok or self.df is None or self.df.empty:
            return None
        if "close" not in self.df.columns:
            return None
        try:
            return float(self.df["close"].iloc[-1])
        except (IndexError, ValueError, TypeError):
            return None

    @property
    def last_date(self) -> Optional[str]:
        if not self.ok or self.df is None or self.df.empty:
            return None
        if "date" not in self.df.columns:
            return None
        try:
            return str(self.df["date"].iloc[-1])[:10]
        except (IndexError, TypeError):
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ok": self.ok,
            "provider": self.provider,
            "rows": self.rows,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "freshness_score": round(self.freshness_score, 4),
            "latest_price": self.latest_price,
            "last_date": self.last_date,
        }


def _freshness(rows: int, lookback_days: int) -> float:
    """0..1 — how much of the requested window we actually got."""
    if lookback_days <= 0:
        return 0.0
    return max(0.0, min(1.0, rows / lookback_days))


class MarketDataClient:
    """Typed market-data client with graceful fallback.

    Order of preference:
      1. ``data_provider.DataFetcherManager`` — the repo's multi-source
         manager.  Supports A-share, HK, US, JP, KR, TW out of the box.
      2. ``yfinance`` direct — the same free source the repo falls back
         to; useful in minimal environments where the manager's heavier
         deps (akshare, baostock, ...) are not installed.
    """

    def __init__(self, fetcher: Any = None):
        self._fetcher = fetcher
        if fetcher is None:
            self._fetcher = self._maybe_build_repo_fetcher()

    @staticmethod
    def _maybe_build_repo_fetcher() -> Any:
        try:
            from data_provider import DataFetcherManager  # type: ignore

            return DataFetcherManager()
        except Exception as exc:  # pragma: no cover - depends on env
            logger.debug("repo DataFetcherManager unavailable: %s", exc)
            return None

    def get_daily(
        self,
        symbol: str,
        *,
        days: int = 120,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> MarketSnapshot:
        """Fetch daily OHLCV bars for ``symbol``.

        Returns a :class:`MarketSnapshot` regardless of success; callers
        MUST check ``snapshot.ok`` before consuming the frame.
        """
        # 1. Try the repo fetcher first.
        if self._fetcher is not None:
            try:
                if start_date and end_date:
                    df, provider = self._fetcher.get_daily_data(
                        symbol, start_date=start_date, end_date=end_date
                    )
                else:
                    df, provider = self._fetcher.get_daily_data(symbol, days=days)
                if df is not None and not df.empty:
                    rows = len(df)
                    return MarketSnapshot(
                        symbol=symbol,
                        ok=True,
                        df=df,
                        provider=str(provider or "repo_fetcher"),
                        rows=rows,
                        freshness_score=_freshness(rows, days),
                    )
            except Exception as exc:
                logger.warning("repo fetcher failed for %s: %s", symbol, exc)

        # 2. Fall back to yfinance directly.
        try:
            import yfinance as yf  # type: ignore

            period = "2y" if days > 250 else "1y"
            tkr = yf.Ticker(symbol)
            df = tkr.history(period=period)
            if df is None or df.empty:
                return MarketSnapshot(
                    symbol=symbol, ok=False,
                    error="yfinance returned empty frame",
                    provider="yfinance",
                )
            # Normalise to repo convention: lowercase columns, 'date' string.
            df = df.reset_index()
            df.columns = [str(c).lower() for c in df.columns]
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            elif "datetime" in df.columns:
                df.rename(columns={"datetime": "date"}, inplace=True)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            # Trim to last N rows
            if len(df) > days:
                df = df.tail(days).reset_index(drop=True)
            rows = len(df)
            return MarketSnapshot(
                symbol=symbol,
                ok=True,
                df=df,
                provider="yfinance",
                rows=rows,
                freshness_score=_freshness(rows, days),
            )
        except Exception as exc:
            return MarketSnapshot(
                symbol=symbol,
                ok=False,
                error=f"all providers failed: {exc}",
                provider="none",
            )

    def get_many(self, symbols: List[str], *, days: int = 120) -> Dict[str, MarketSnapshot]:
        return {s: self.get_daily(s, days=days) for s in symbols}


# ---------------------------------------------------------------------------
# Synthetic fixture loader — used by tests and offline CI runs.
# ---------------------------------------------------------------------------


def load_synthetic_frame(symbol: str, days: int = 120, seed: int = 0) -> pd.DataFrame:
    """Deterministic synthetic OHLCV frame for tests.

    Same shape as a real fetcher output: ``date, open, high, low, close,
    volume``.  Uses a simple seeded random walk so backtest math is
    verifiable without external network calls.
    """
    import math
    import random

    rng = random.Random(seed + hash(symbol) % 1000)
    rows = []
    price = 100.0
    start = pd.Timestamp("2024-01-01")
    for i in range(days):
        shock = rng.gauss(0.0, 0.015)
        # Inject a gentle bull drift so trend-following strategies fire.
        price = max(1.0, price * (1.0 + 0.0005 + shock))
        open_ = price * (1.0 - rng.uniform(0.0, 0.005))
        close = price
        high = max(open_, close) * (1.0 + rng.uniform(0.0, 0.008))
        low = min(open_, close) * (1.0 - rng.uniform(0.0, 0.008))
        volume = rng.randint(500_000, 5_000_000)
        rows.append({
            "date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(open_, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": volume,
        })
    return pd.DataFrame(rows)
