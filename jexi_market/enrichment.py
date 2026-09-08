# -*- coding: utf-8 -*-
"""Free data enrichment adapters for JEXI Market.

These adapters pull REAL fundamentals, news, and sector classification
from free sources (yfinance by default).  They are deliberately separate
from the deterministic specialist agents so that:

1. The agents stay pure-Python and testable without network.
2. The enrichment can fail without crashing the agent pipeline — when
   yfinance is unavailable or returns no data, the adapter returns
   ``None`` and the agent treats that as "no opinion" (never invents).
3. The same adapters can be swapped for paid sources (Longbridge,
   AlphaVantage) by changing one function.

This module closes the three "genuine limitations" flagged in the
first build:
  * FundamentalAgent now has real data
  * NewsAgent now has real data
  * Sector classification is no longer a placeholder
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


@dataclass
class Fundamentals:
    """Normalised fundamental snapshot for one symbol."""

    symbol: str
    ok: bool = False
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    profit_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    quarterly_earnings_growth: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    total_cash: Optional[float] = None
    total_debt: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    fetched_at: float = field(default_factory=time.time)
    source: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "symbol": self.symbol,
            "ok": self.ok,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "sector": self.sector,
            "industry": self.industry,
        }
        for k in (
            "pe_ratio", "forward_pe", "price_to_book", "profit_margin",
            "gross_margin", "operating_margin", "return_on_equity",
            "revenue_growth", "earnings_growth", "quarterly_earnings_growth",
            "debt_to_equity", "current_ratio", "market_cap",
            "total_cash", "total_debt",
        ):
            v = getattr(self, k)
            if v is not None:
                out[k] = round(float(v), 4) if isinstance(v, (int, float)) else v
        if self.error:
            out["error"] = self.error
        return out


class FundamentalAdapter:
    """Free-source fundamental adapter (yfinance by default).

    When yfinance is unavailable, every method returns a Fundamentals
    object with ``ok=False`` — agents treat that as "no opinion",
    never as "neutral".  This is the spec's "DO NOT INVENT DATA" rule.
    """

    def __init__(self, source: str = "yfinance"):
        self.source = source

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        try:
            import yfinance as yf  # type: ignore
        except ImportError:
            return Fundamentals(symbol=symbol, ok=False, error="yfinance not installed")

        try:
            tkr = yf.Ticker(symbol)
            info = tkr.info or {}
            if not info:
                return Fundamentals(symbol=symbol, ok=False, error="empty info", source=self.source)
            return Fundamentals(
                symbol=symbol,
                ok=True,
                pe_ratio=_safe_float(info.get("trailingPE")),
                forward_pe=_safe_float(info.get("forwardPE")),
                price_to_book=_safe_float(info.get("priceToBook")),
                profit_margin=_safe_float(info.get("profitMargins")),
                gross_margin=_safe_float(info.get("grossMargins")),
                operating_margin=_safe_float(info.get("operatingMargins")),
                return_on_equity=_safe_float(info.get("returnOnEquity")),
                revenue_growth=_safe_float(info.get("revenueGrowth")),
                earnings_growth=_safe_float(info.get("earningsGrowth")),
                quarterly_earnings_growth=_safe_float(info.get("earningsQuarterlyGrowth")),
                debt_to_equity=_safe_float(info.get("debtToEquity")),
                current_ratio=_safe_float(info.get("currentRatio")),
                market_cap=_safe_float(info.get("marketCap")),
                total_cash=_safe_float(info.get("totalCash")),
                total_debt=_safe_float(info.get("totalDebt")),
                sector=info.get("sector"),
                industry=info.get("industry"),
                source=self.source,
            )
        except Exception as exc:
            logger.warning("fundamental fetch failed for %s: %s", symbol, exc)
            return Fundamentals(symbol=symbol, ok=False, error=str(exc), source=self.source)


# ---------------------------------------------------------------------------
# News / sentiment
# ---------------------------------------------------------------------------


@dataclass
class NewsItem:
    title: str
    publisher: str = ""
    published_at: float = 0.0
    url: str = ""
    summary: str = ""


@dataclass
class NewsSnapshot:
    symbol: str
    ok: bool = False
    items: List[NewsItem] = field(default_factory=list)
    sentiment: str = "neutral"          # positive / negative / neutral
    sentiment_score: float = 0.0         # -1..1
    fetched_at: float = field(default_factory=time.time)
    source: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ok": self.ok,
            "sentiment": self.sentiment,
            "sentiment_score": round(self.sentiment_score, 4),
            "n_items": len(self.items),
            "items": [
                {
                    "title": it.title,
                    "publisher": it.publisher,
                    "url": it.url,
                    "published_at": it.published_at,
                }
                for it in self.items[:5]
            ],
            "source": self.source,
            "error": self.error,
        }


class NewsAdapter:
    """Free-source news adapter (yfinance + lightweight keyword sentiment).

    Sentiment is computed via a simple keyword-based classifier (no LLM
    required, no API key, deterministic).  When yfinance is unavailable
    or returns no news, the snapshot has ``ok=False`` and the NewsAgent
    returns ``None`` (no opinion).
    """

    POSITIVE_KEYWORDS = frozenset({
        "beat", "beats", "surge", "surges", "jump", "jumps", "rally",
        "rallies", "gain", "gains", "soar", "soars", "rise", "rises",
        "rising", "upgrade", "upgraded", "buy", "bullish", "outperform",
        "raise", "raises", "boost", "boosts", "win", "wins", "record",
        "strong", "growth", "profit", "profits", "exceed", "exceeds",
        "optimis", "optimist", "breakthrough", "innovat", "expand",
        "expansion", "milestone", "achieve",
    })

    NEGATIVE_KEYWORDS = frozenset({
        "miss", "misses", "missed", "fall", "falls", "falling", "drop",
        "drops", "dropping", "plunge", "plunges", "crash", "crashes",
        "sell", "selling", "downgrade", "downgraded", "bearish",
        "underperform", "cut", "cuts", "reduce", "reduces", "loss",
        "losses", "weak", "weakness", "decline", "declines", "lower",
        "fear", "fears", "risk", "risks", "warning", "warns", "alert",
        "investigation", "lawsuit", "sue", "sued", "fraud", "recall",
        "bankrupt", "default", "misses", "disappoint",
    })

    def __init__(self, source: str = "yfinance"):
        self.source = source

    def get_news(self, symbol: str, *, max_items: int = 20) -> NewsSnapshot:
        try:
            import yfinance as yf  # type: ignore
        except ImportError:
            return NewsSnapshot(symbol=symbol, ok=False, error="yfinance not installed")

        try:
            tkr = yf.Ticker(symbol)
            raw_news = tkr.news or []
            items: List[NewsItem] = []
            for item in raw_news[:max_items]:
                content = item.get("content") or {}
                title = content.get("title") or item.get("title") or ""
                if not title:
                    continue
                publisher = (
                    content.get("provider") or {}
                    if isinstance(content.get("provider"), dict)
                    else content.get("provider", "")
                )
                if isinstance(publisher, dict):
                    publisher = publisher.get("displayName", "")
                items.append(NewsItem(
                    title=title,
                    publisher=str(publisher or ""),
                    published_at=_safe_float(content.get("pubDate") or item.get("providerPublishTime")) or 0.0,
                    url=content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else "",
                    summary=content.get("summary", ""),
                ))
            if not items:
                return NewsSnapshot(symbol=symbol, ok=False, error="no news items", source=self.source)

            sentiment, score = self._classify_sentiment(items)
            return NewsSnapshot(
                symbol=symbol,
                ok=True,
                items=items,
                sentiment=sentiment,
                sentiment_score=score,
                source=self.source,
            )
        except Exception as exc:
            logger.warning("news fetch failed for %s: %s", symbol, exc)
            return NewsSnapshot(symbol=symbol, ok=False, error=str(exc), source=self.source)

    def _classify_sentiment(self, items: List[NewsItem]) -> tuple:
        """Simple keyword-based sentiment classifier.

        Counts positive/negative keyword hits across all titles.  Returns
        (label, score) where score is in [-1, 1].  This is intentionally
        simple — no LLM, no API key, deterministic.  For higher quality
        sentiment, swap in Anspire / SerpAPI / a fine-tuned model.
        """
        pos = 0
        neg = 0
        for item in items:
            title_lower = item.title.lower()
            for kw in self.POSITIVE_KEYWORDS:
                if kw in title_lower:
                    pos += 1
                    break
            for kw in self.NEGATIVE_KEYWORDS:
                if kw in title_lower:
                    neg += 1
                    break
        total = pos + neg
        if total == 0:
            return "neutral", 0.0
        score = (pos - neg) / total
        if score > 0.2:
            return "positive", score
        if score < -0.2:
            return "negative", score
        return "neutral", score


# ---------------------------------------------------------------------------
# Sector classification
# ---------------------------------------------------------------------------


class SectorClassifier:
    """Maps symbols to sectors using the fundamental adapter.

    This fixes the risk gate's sector-concentration check (previously
    the symbol itself was used as the sector placeholder).
    """

    def __init__(self, adapter: Optional[FundamentalAdapter] = None):
        self.adapter = adapter or FundamentalAdapter()
        self._cache: Dict[str, str] = {}

    def classify(self, symbol: str) -> str:
        if symbol in self._cache:
            return self._cache[symbol]
        fund = self.adapter.get_fundamentals(symbol)
        sector = fund.sector or "Unknown"
        self._cache[symbol] = sector
        return sector

    def classify_many(self, symbols: List[str]) -> Dict[str, str]:
        return {s: self.classify(s) for s in symbols}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        # yfinance sometimes returns NaN for missing fields
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None
