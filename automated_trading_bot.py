#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production AI Trading Bot — multi-agent pipeline.

Architecture (each agent has one job; they communicate through CycleContext):

  MarketAgent     US market clock (Alpaca /v2/clock with ET-hours fallback) and
                  market-regime signal from SPY daily bars.
  ResearchAgent   Per-symbol scoring. Uses the repository's own analysis engine
                  (src.stock_analyzer.StockTrendAnalyzer — the same technical core
                  that feeds the LLM analysis pipeline) when its dependencies are
                  importable; otherwise falls back to a built-in pure-Python
                  scorer (MA alignment, RSI-14, momentum, bias guard).
  RiskAgent       Position sizing (equity-based with cash reserve + per-position
                  cap), take-profit / stop-loss exits, regime exits, and a
                  double-sell guard based on open orders.
  ExecutionAgent  Submits market orders to Alpaca (dry-run aware).
  ReportAgent     Sends a structured ntfy report EVERY cycle via the ntfy JSON
                  publish API (Bearer auth, timeout, long-report attachment
                  fallback so oversized reports never die with HTTP 413).

Key fixes over the previous version:
  * Market data is fetched from https://data.alpaca.markets (the old code called
    /v2/stocks/<sym>/quotes and /bars on paper-api.alpaca.markets, which returns
    404 — prices were always 0 and the signal always defaulted to 50/HOLD).
  * Quote/bar payloads are parsed with the real data-API v2 schema
    ({"quote": {"ap", "bp"}} and {"bars": {"SYM": [{"c", "v", ...}]}}).
  * Market-open check uses the Alpaca clock endpoint (holiday-aware) with a
    local ET-hours fallback.
  * Position sizing is equity-based (not leveraged buying power), keeps the cash
    reserve, caps each position, and decrements the remaining budget per fill so
    two buys can never double-allocate the same cash.
  * No double sells: symbols with pending sell orders are skipped and sell qty
    is reduced by anything already in flight.
  * A structured report is sent to ntfy every cycle (including HOLD and
    market-closed cycles), with JSON publish, optional Bearer token, timeouts,
    and a file-attachment fallback for long reports.

Environment (see .env.example → "Automated Trading Bot"):
  ALPACA_API_KEY / ALPACA_SECRET_KEY     required
  APCA_API_BASE_URL                      default https://paper-api.alpaca.markets
  ALPACA_DATA_BASE_URL                   default https://data.alpaca.markets
  NTFY_TOPIC / NTFY_SERVER / NTFY_TOKEN  notification channel
  BOT_FORCE_RUN=1                        trade even when market closed (manual runs)
  BOT_DRY_RUN=1                          plan + report, but never submit orders
  threshold/sizing overrides             see BotConfig.from_env
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Optional dependencies (the workflow installs these; local runs may not have
# them — every use site degrades gracefully).
# ---------------------------------------------------------------------------
try:  # pragma: no cover - environment dependent
    from zoneinfo import ZoneInfo  # Python 3.9+

    def _et_now() -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))

except Exception:  # pragma: no cover - fallback
    try:
        import pytz

        def _et_now() -> datetime:
            return datetime.now(pytz.timezone("America/New_York"))

    except Exception:

        def _et_now() -> datetime:
            # Last resort: rough ET via fixed UTC-5 (no DST). Only used for the
            # fallback clock heuristic when the Alpaca clock API is unreachable.
            from datetime import timedelta, timezone

            return datetime.now(timezone(timedelta(hours=-5)))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default)
    return [item.strip().upper() for item in raw.replace(";", ",").split(",") if item.strip()]


# ============================================
# 🔑 CONFIGURATION
# ============================================

DEFAULT_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_DATA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_NTFY_TOPIC = "my-stock-report-kenya"
# ntfy.sh rejects messages larger than 4096 bytes with HTTP 413; keep margin.
DEFAULT_NTFY_MESSAGE_BYTE_LIMIT = 3900


@dataclass
class BotConfig:
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    trading_base_url: str = DEFAULT_TRADING_BASE_URL
    data_base_url: str = DEFAULT_DATA_BASE_URL

    # ntfy
    ntfy_server: str = DEFAULT_NTFY_SERVER
    ntfy_topic: str = DEFAULT_NTFY_TOPIC
    ntfy_token: Optional[str] = None
    ntfy_timeout: float = 15.0
    ntfy_message_byte_limit: int = DEFAULT_NTFY_MESSAGE_BYTE_LIMIT
    notify_when_closed: bool = True

    # Trading rules
    buy_signal_threshold: int = 60        # buy when score >= 60
    sell_signal_threshold: int = 30       # regime exit when score <= 30
    take_profit_percent: float = 10.0     # take profit at +10%
    stop_loss_percent: float = 5.0        # stop loss at -5%
    max_position_percent: float = 40.0    # max 40% of EQUITY per stock
    cash_reserve_percent: float = 20.0    # keep 20% of equity in cash
    max_stocks: int = 3                   # max 3 positions at once
    max_buys_per_cycle: int = 2           # max 2 new buys per cycle
    min_order_usd: float = 10.0           # skip dust orders
    stocks_to_trade: List[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA"])

    # Behaviour switches
    force_run: bool = False
    dry_run: bool = False
    use_repo_analyzer: bool = True
    request_timeout: float = 20.0
    bars_limit: int = 120                 # >= 60 so MA60/MACD/RSI have history

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            api_key=(os.environ.get("ALPACA_API_KEY") or "").strip() or None,
            secret_key=(os.environ.get("ALPACA_SECRET_KEY") or "").strip() or None,
            trading_base_url=(os.environ.get("APCA_API_BASE_URL") or DEFAULT_TRADING_BASE_URL).rstrip("/"),
            data_base_url=(os.environ.get("ALPACA_DATA_BASE_URL") or DEFAULT_DATA_BASE_URL).rstrip("/"),
            ntfy_server=(os.environ.get("NTFY_SERVER") or DEFAULT_NTFY_SERVER).rstrip("/"),
            ntfy_topic=(os.environ.get("NTFY_TOPIC") or DEFAULT_NTFY_TOPIC).strip(),
            ntfy_token=(os.environ.get("NTFY_TOKEN") or "").strip() or None,
            ntfy_timeout=_env_float("NTFY_TIMEOUT", 15.0),
            ntfy_message_byte_limit=_env_int("NTFY_MESSAGE_BYTE_LIMIT", DEFAULT_NTFY_MESSAGE_BYTE_LIMIT),
            notify_when_closed=_env_bool("BOT_NOTIFY_CLOSED", True),
            buy_signal_threshold=_env_int("BUY_SIGNAL_THRESHOLD", 60),
            sell_signal_threshold=_env_int("SELL_SIGNAL_THRESHOLD", 30),
            take_profit_percent=_env_float("TAKE_PROFIT_PERCENT", 10.0),
            stop_loss_percent=_env_float("STOP_LOSS_PERCENT", 5.0),
            max_position_percent=_env_float("MAX_POSITION_PERCENT", 40.0),
            cash_reserve_percent=_env_float("CASH_RESERVE_PERCENT", 20.0),
            max_stocks=_env_int("MAX_STOCKS", 3),
            max_buys_per_cycle=_env_int("MAX_BUYS_PER_CYCLE", 2),
            min_order_usd=_env_float("MIN_ORDER_USD", 10.0),
            stocks_to_trade=_env_list("STOCKS_TO_TRADE", ["AAPL", "MSFT", "NVDA"]),
            force_run=_env_bool("BOT_FORCE_RUN", False),
            dry_run=_env_bool("BOT_DRY_RUN", False),
            use_repo_analyzer=_env_bool("BOT_USE_REPO_ANALYZER", True),
            request_timeout=_env_float("BOT_REQUEST_TIMEOUT", 20.0),
            bars_limit=_env_int("BOT_BARS_LIMIT", 120),
        )


# ============================================
# 📡 NTFY NOTIFIER (JSON publish API)
# ============================================

class NtfyNotifier:
    """Publish to ntfy using the JSON publish API.

    * POST {server} with {"topic", "title", "message", "priority", "tags"}
    * Bearer-token auth when NTFY_TOKEN is configured
    * Hard timeout — never hangs the workflow
    * Long reports: the message is truncated into the push notification and the
      full report is attached as a file (fixes HTTP 413 for oversized bodies).
      The fallback is also triggered reactively when the server answers 413.
    """

    def __init__(self, config: BotConfig):
        self.config = config

    # -- internals ----------------------------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "daily-stock-analysis-trading-bot"}
        token = (self.config.ntfy_token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post_json(self, payload: Dict[str, Any]) -> Tuple[bool, int]:
        try:
            response = requests.post(
                self.config.ntfy_server,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=self.config.ntfy_timeout,
            )
            return 200 <= response.status_code < 300, response.status_code
        except requests.RequestException as exc:
            print(f"[ntfy] request failed: {type(exc).__name__}: {exc}")
            return False, -1

    def _truncate_utf8(self, text: str, limit: int) -> str:
        encoded = text.encode("utf-8")[:limit]
        return encoded.decode("utf-8", errors="ignore").rstrip()

    @staticmethod
    def _latin1_header(value: str, limit: int = 200) -> str:
        """HTTP headers must be latin-1 — emojis/CJK would crash the request.

        Only used for header values (Title/Filename); message bodies stay UTF-8.
        """
        return (value or "").encode("latin-1", "replace").decode("latin-1").strip()[:limit]

    def _send_with_attachment(self, title: str, message: str, priority: int) -> bool:
        """Send a truncated summary message plus the full report as a file."""
        # Target the well-known ntfy.sh cap unless the operator configured a
        # smaller limit; shrink adaptively if the server still answers 413
        # (self-hosted servers can enforce tighter caps).
        summary_limit = max(
            200,
            min(self.config.ntfy_message_byte_limit, DEFAULT_NTFY_MESSAGE_BYTE_LIMIT) - 250,
        )
        ok, status = False, -1
        for _ in range(3):
            summary = self._truncate_utf8(message, summary_limit)
            if summary != message:
                summary += "\n\n[…report truncated — full text attached]"
            ok, status = self._post_json(
                {
                    "topic": self.config.ntfy_topic,
                    "title": title,
                    "message": summary,
                    "priority": priority,
                }
            )
            if ok or status != 413:
                break
            summary_limit = max(200, summary_limit // 2)
            print(f"[ntfy] summary still too large (HTTP 413) — retrying with {summary_limit} bytes")
        if not ok:
            print(f"[ntfy] summary publish failed (HTTP {status})")
            return False

        filename = f"trading-report-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.txt"
        try:
            response = requests.post(
                f"{self.config.ntfy_server}/{self.config.ntfy_topic}",
                data=message.encode("utf-8"),
                headers={
                    **self._auth_headers(),
                    "Title": self._latin1_header(f"{title} (full report)"),
                    "Filename": self._latin1_header(filename),
                    "Priority": str(priority),
                    "Message": "Full trading report attached.",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                timeout=max(self.config.ntfy_timeout, 30.0),
            )
            if 200 <= response.status_code < 300:
                print(f"[ntfy] attached full report as {filename}")
                return True
            print(f"[ntfy] attachment failed: HTTP {response.status_code}")
            return False
        except Exception as exc:
            print(f"[ntfy] attachment request failed: {type(exc).__name__}: {exc}")
            return False

    # -- public API ----------------------------------------------------------
    def send(self, title: str, message: str, priority: int = 3, tags: Optional[List[str]] = None) -> bool:
        """Publish one notification. Never raises. Returns success."""
        title = (title or "").strip()[:250] or "Trading Bot"
        message = message or ""

        if len(message.encode("utf-8")) > self.config.ntfy_message_byte_limit:
            print("[ntfy] message too large — using attachment fallback")
            return self._send_with_attachment(title, message, priority)

        payload: Dict[str, Any] = {
            "topic": self.config.ntfy_topic,
            "title": title,
            "message": message,
            "priority": priority,
        }
        if tags:
            payload["tags"] = list(tags)

        ok, status = self._post_json(payload)
        if ok:
            print(f"[ntfy] sent: {title}")
            return True
        if status == 413:
            print("[ntfy] server rejected size (HTTP 413) — retrying with attachment fallback")
            return self._send_with_attachment(title, message, priority)
        print(f"[ntfy] publish failed (HTTP {status})")
        return False


# Keep a simple module-level helper for backwards compatibility.
_DEFAULT_NOTIFIER: Optional[NtfyNotifier] = None


def send_notification(title: str, message: str, priority: int = 3, config: Optional[BotConfig] = None) -> bool:
    global _DEFAULT_NOTIFIER
    if config is not None or _DEFAULT_NOTIFIER is None:
        _DEFAULT_NOTIFIER = NtfyNotifier(config or BotConfig.from_env())
    return _DEFAULT_NOTIFIER.send(title, message, priority=priority)


# ============================================
# 🦙 ALPACA CLIENT (correct hosts & schemas)
# ============================================

class AlpacaClient:
    """Thin Alpaca REST client.

    Trading endpoints (account/positions/orders/clock) live on the trading host
    (paper-api.alpaca.markets by default). Market data (quotes/bars) lives on
    https://data.alpaca.markets — NOT on the trading host (that 404s).
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._headers = {
            "APCA-API-KEY-ID": config.api_key or "",
            "APCA-API-SECRET-KEY": config.secret_key or "",
        }

    # -- helpers -------------------------------------------------------------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        try:
            response = requests.get(url, headers=self._headers, params=params, timeout=self.config.request_timeout)
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, None
        except requests.RequestException as exc:
            print(f"[alpaca] GET {url} failed: {type(exc).__name__}: {exc}")
            return -1, None

    def _post(self, url: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
        try:
            response = requests.post(url, headers=self._headers, json=payload, timeout=self.config.request_timeout)
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, None
        except requests.RequestException as exc:
            print(f"[alpaca] POST {url} failed: {type(exc).__name__}: {exc}")
            return -1, None

    # -- trading endpoints ---------------------------------------------------
    def get_account(self) -> Optional[Dict[str, Any]]:
        status, data = self._get(f"{self.config.trading_base_url}/v2/account")
        return data if status == 200 and isinstance(data, dict) else None

    def get_positions(self) -> List[Dict[str, Any]]:
        status, data = self._get(f"{self.config.trading_base_url}/v2/positions")
        return data if status == 200 and isinstance(data, list) else []

    def get_open_orders(self) -> List[Dict[str, Any]]:
        status, data = self._get(
            f"{self.config.trading_base_url}/v2/orders", params={"status": "open", "direction": "asc"}
        )
        return data if status == 200 and isinstance(data, list) else []

    def get_clock(self) -> Optional[Dict[str, Any]]:
        status, data = self._get(f"{self.config.trading_base_url}/v2/clock")
        return data if status == 200 and isinstance(data, dict) else None

    def submit_order(self, order: Dict[str, Any]) -> Tuple[bool, Any]:
        status, data = self._post(f"{self.config.trading_base_url}/v2/orders", order)
        return status in (200, 201), data

    # -- market data endpoints (data.alpaca.markets) --------------------------
    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        status, data = self._get(f"{self.config.data_base_url}/v2/stocks/{symbol}/quotes/latest")
        if status == 200 and isinstance(data, dict):
            quote = data.get("quote")
            if isinstance(quote, dict):
                return quote
        return None

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"timeframe": timeframe, "limit": limit or self.config.bars_limit}
        status, data = self._get(f"{self.config.data_base_url}/v2/stocks/{symbol}/bars", params=params)
        if status == 200 and isinstance(data, dict):
            bars = data.get("bars")
            if isinstance(bars, dict):
                symbol_bars = bars.get(symbol)
                if isinstance(symbol_bars, list):
                    return symbol_bars
            if isinstance(bars, list):  # defensive: some feeds return a flat list
                return bars
        return []


# ============================================
# 📈 MARKET AGENT
# ============================================

class MarketAgent:
    """Market clock + regime signal."""

    def __init__(self, client: AlpacaClient):
        self.client = client

    def clock_status(self) -> Dict[str, Any]:
        clock = self.client.get_clock()
        if isinstance(clock, dict) and "is_open" in clock:
            return {"is_open": bool(clock["is_open"]), "source": "alpaca-clock", "raw": clock}
        # Fallback: weekday + 09:30–16:00 America/New_York (holidays unknown).
        now_et = _et_now()
        open_at = datetime.combine(now_et.date(), dtime(9, 30))
        close_at = datetime.combine(now_et.date(), dtime(16, 0))
        naive_now = now_et.replace(tzinfo=None)
        is_open = now_et.weekday() < 5 and open_at <= naive_now <= close_at
        return {"is_open": is_open, "source": "et-hours-fallback"}

    @staticmethod
    def score_regime(change_percent: float) -> int:
        if change_percent > 3:
            return 85
        if change_percent > 1:
            return 70
        if change_percent > -1:
            return 50
        if change_percent > -3:
            return 35
        return 15

    def regime_signal(self, spy_symbol: str = "SPY", lookback: int = 5) -> Dict[str, Any]:
        """0–100 market-regime score from SPY daily bars (data.alpaca.markets)."""
        bars = self.client.get_bars(spy_symbol, timeframe="1Day", limit=lookback)
        closes = [float(bar.get("c", 0)) for bar in bars if bar.get("c")]
        if len(closes) >= 2 and closes[0] > 0:
            change = (closes[-1] - closes[0]) / closes[0] * 100.0
            score = self.score_regime(change)
            label = "BULLISH" if score >= 70 else "BEARISH" if score <= 35 else "NEUTRAL"
            return {"score": score, "change_percent": round(change, 2), "bars": len(closes), "label": label}
        return {"score": 50, "change_percent": 0.0, "bars": len(closes), "label": "NEUTRAL", "note": "insufficient SPY data — defaulting to neutral"}


# ============================================
# 🔬 RESEARCH AGENT
# ============================================

def _load_repo_analyzer():
    """Import the repo's StockTrendAnalyzer lazily; None when unavailable."""
    try:
        from src.stock_analyzer import analyze_stock  # type: ignore

        return analyze_stock
    except Exception as exc:  # ImportError and anything the config chain raises
        print(f"[research] repo analyzer unavailable ({type(exc).__name__}); using built-in scorer")
        return None


class ResearchAgent:
    """Scores each watchlist symbol 0–100.

    Preferred path: the repository's own analysis engine (src.stock_analyzer —
    MA5/10/20/60 alignment, bias guard, volume shape, MACD, RSI, support &
    resistance). That is the same technical core the LLM analysis pipeline
    consumes, so the trading bot now trades off the fork's real system.

    Fallback path (no pandas/deps): built-in pure-Python scorer implementing the
    same philosophy (trend alignment, RSI-14, 5-day momentum, no-chase bias).
    """

    def __init__(self, client: AlpacaClient, config: BotConfig):
        self.client = client
        self.config = config
        self._repo_analyzer: Any = False  # False = not loaded yet

    # -- price ----------------------------------------------------------------
    def latest_price(self, symbol: str) -> float:
        quote = self.client.get_latest_quote(symbol)
        if quote:
            ask = float(quote.get("ap") or 0)
            bid = float(quote.get("bp") or 0)
            if ask > 0:
                return ask
            if bid > 0:
                return bid
        # Last resort: most recent daily close.
        bars = self.client.get_bars(symbol, timeframe="1Day", limit=1)
        if bars:
            return float(bars[-1].get("c") or 0)
        return 0.0

    # -- repo analyzer path -----------------------------------------------------
    @staticmethod
    def _bars_to_dataframe(bars: List[Dict[str, Any]]):
        try:
            import pandas as pd  # noqa: F401
        except Exception:
            return None
        rows = [
            {
                "date": bar.get("t"),
                "open": float(bar.get("o", 0)),
                "high": float(bar.get("h", 0)),
                "low": float(bar.get("l", 0)),
                "close": float(bar.get("c", 0)),
                "volume": float(bar.get("v", 0)),
            }
            for bar in bars
            if bar.get("t") and bar.get("c")
        ]
        if len(rows) < 20:
            return None
        return pd.DataFrame(rows)

    def _score_with_repo_analyzer(self, symbol: str, bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if self._repo_analyzer is False:
            self._repo_analyzer = _load_repo_analyzer() or None
        if not self._repo_analyzer:
            return None
        df = self._bars_to_dataframe(bars)
        if df is None:
            return None
        try:
            result = self._repo_analyzer(df, symbol)
            summary_lines = []
            try:
                from src.stock_analyzer import StockTrendAnalyzer  # type: ignore

                formatted = StockTrendAnalyzer().format_analysis(result)
                summary_lines = [line for line in formatted.splitlines() if line.strip()][:8]
            except Exception:
                pass
            return {
                "symbol": symbol,
                "score": int(result.signal_score),
                "signal": result.buy_signal.name,
                "source": "repo-analyzer",
                "reasons": list(result.signal_reasons)[:5],
                "risks": list(result.risk_factors)[:3],
                "summary": summary_lines,
            }
        except Exception as exc:
            print(f"[research] repo analyzer failed for {symbol}: {type(exc).__name__}: {exc}")
            return None

    # -- built-in fallback ------------------------------------------------------
    @staticmethod
    def _rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) <= period:
            return 50.0
        gains, losses = [], []
        for prev, cur in zip(closes[-period - 1:-1], closes[-period:]):
            delta = cur - prev
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _score_builtin(self, symbol: str, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        closes = [float(bar.get("c", 0)) for bar in bars if bar.get("c")]
        reasons: List[str] = []
        if len(closes) < 20:
            return {
                "symbol": symbol,
                "score": 50,
                "signal": "HOLD",
                "source": "builtin-technical",
                "reasons": ["insufficient bar history"],
                "risks": [],
                "summary": [],
            }
        ma = lambda n: sum(closes[-n:]) / n  # noqa: E731
        ma5, ma10, ma20 = ma(5), ma(10), ma(20)
        rsi = self._rsi(closes)
        momentum5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] > 0 else 0.0
        bias5 = (closes[-1] - ma5) / ma5 * 100 if ma5 > 0 else 0.0

        score = 50.0
        if ma5 > ma10 > ma20:
            score += 15
            reasons.append("MA5>MA10>MA20 bullish alignment")
        elif ma5 < ma10 < ma20:
            score -= 15
            reasons.append("MA5<MA10<MA20 bearish alignment")
        else:
            reasons.append("mixed MA alignment")

        if 55 <= rsi < 70:
            score += 10
            reasons.append(f"RSI14 {rsi:.0f} healthy momentum")
        elif rsi >= 75:
            score -= 10
            reasons.append(f"RSI14 {rsi:.0f} overbought")
        elif rsi < 45:
            score -= 10
            reasons.append(f"RSI14 {rsi:.0f} weak")

        score += max(-10.0, min(10.0, momentum5 * 2))
        reasons.append(f"5d momentum {momentum5:+.2f}%")

        if bias5 > 5:
            score -= 5
            reasons.append(f"extended {bias5:+.1f}% above MA5 — no chasing")

        score = int(max(0, min(100, round(score))))
        if score >= 80:
            signal = "STRONG_BUY"
        elif score >= 60:
            signal = "BUY"
        elif score >= 40:
            signal = "HOLD"
        elif score >= 25:
            signal = "WAIT"
        else:
            signal = "SELL"
        return {
            "symbol": symbol,
            "score": score,
            "signal": signal,
            "source": "builtin-technical",
            "reasons": reasons,
            "risks": [],
            "summary": [],
        }

    # -- public -----------------------------------------------------------------
    def research_symbol(self, symbol: str) -> Dict[str, Any]:
        price = self.latest_price(symbol)
        bars = self.client.get_bars(symbol, timeframe="1Day", limit=self.config.bars_limit)
        scored = None
        if self.config.use_repo_analyzer:
            scored = self._score_with_repo_analyzer(symbol, bars)
        if scored is None:
            scored = self._score_builtin(symbol, bars)
        scored["price"] = price
        scored["bars"] = len(bars)
        return scored

    def research(self, symbols: List[str]) -> List[Dict[str, Any]]:
        out = []
        for symbol in symbols:
            try:
                out.append(self.research_symbol(symbol))
            except Exception as exc:
                print(f"[research] {symbol} failed: {type(exc).__name__}: {exc}")
                out.append(
                    {"symbol": symbol, "score": 50, "signal": "HOLD", "source": "error",
                     "reasons": [f"research failed: {type(exc).__name__}"], "risks": [], "summary": [],
                     "price": 0.0, "bars": 0}
                )
        return out


# ============================================
# 🛡️ RISK AGENT
# ============================================

@dataclass
class ExitPlan:
    symbol: str
    qty: float
    reason: str
    pnl_percent: float = 0.0


@dataclass
class EntryPlan:
    symbol: str
    qty: int
    est_price: float
    budget: float
    score: int


class RiskAgent:
    """Sizing and exit logic with hard double-sell protection."""

    def __init__(self, config: BotConfig):
        self.config = config

    @staticmethod
    def _pending_qty_by_side(open_orders: List[Dict[str, Any]], side: str) -> Dict[str, float]:
        pending: Dict[str, float] = {}
        for order in open_orders or []:
            if str(order.get("side", "")).lower() != side:
                continue
            symbol = order.get("symbol")
            try:
                qty = float(order.get("qty") or order.get("remaining_qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if symbol and qty > 0:
                pending[symbol] = pending.get(symbol, 0.0) + qty
        return pending

    def plan_exits(
        self,
        positions: List[Dict[str, Any]],
        prices: Dict[str, float],
        open_orders: List[Dict[str, Any]],
        regime_score: Optional[int],
    ) -> List[ExitPlan]:
        exits: List[ExitPlan] = []
        pending_sells = self._pending_qty_by_side(open_orders, "sell")

        for pos in positions or []:
            symbol = pos.get("symbol")
            if not symbol:
                continue
            held = float(pos.get("qty", 0))
            already_selling = pending_sells.get(symbol, 0.0)
            sellable = held - already_selling
            if sellable <= 0:
                # Double-sell guard: an exit order is already in flight.
                if already_selling > 0:
                    print(f"[risk] {symbol}: sell order already pending — skipping (no double-sell)")
                continue

            entry_price = float(pos.get("avg_entry_price", 0) or 0)
            current_price = prices.get(symbol) or float(pos.get("current_price", 0) or 0)
            pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 and current_price > 0 else 0.0

            reason: Optional[str] = None
            if pnl_pct >= self.config.take_profit_percent:
                reason = f"take-profit {pnl_pct:+.1f}%"
            elif pnl_pct <= -self.config.stop_loss_percent:
                reason = f"stop-loss {pnl_pct:+.1f}%"
            elif regime_score is not None and regime_score <= self.config.sell_signal_threshold:
                reason = f"regime exit (market signal {regime_score}/100)"

            if reason:
                exits.append(ExitPlan(symbol=symbol, qty=sellable, reason=reason, pnl_percent=round(pnl_pct, 2)))
        return exits

    def plan_entries(
        self,
        candidates: List[Dict[str, Any]],
        account: Dict[str, Any],
        positions: List[Dict[str, Any]],
        open_orders: List[Dict[str, Any]],
    ) -> List[EntryPlan]:
        entries: List[EntryPlan] = []
        equity = float(account.get("equity", 0) or 0)
        buying_power = float(account.get("buying_power", 0) or 0)
        if equity <= 0:
            return entries

        reserve = equity * (self.config.cash_reserve_percent / 100.0)
        investable = max(0.0, buying_power - reserve)
        slot_budget = equity * (self.config.max_position_percent / 100.0)

        owned = {pos.get("symbol") for pos in positions or [] if pos.get("symbol")}
        pending_buys = set(self._pending_qty_by_side(open_orders, "buy").keys())

        committed = 0.0
        planned_positions = len(owned)
        ranked = sorted(candidates or [], key=lambda c: int(c.get("score", 0)), reverse=True)

        for cand in ranked:
            if len(entries) >= self.config.max_buys_per_cycle:
                break
            if planned_positions >= self.config.max_stocks:
                break
            symbol = cand.get("symbol")
            score = int(cand.get("score", 0))
            price = float(cand.get("price", 0) or 0)
            if not symbol or price <= 0:
                continue
            if score < self.config.buy_signal_threshold:
                continue
            if symbol in owned:
                print(f"[risk] {symbol}: already held — skipping")
                continue
            if symbol in pending_buys:
                print(f"[risk] {symbol}: buy order already pending — skipping")
                continue

            remaining = investable - committed
            budget = min(slot_budget, remaining)
            qty = int(budget // price)
            cost = qty * price
            if qty < 1 or cost < self.config.min_order_usd or cost > remaining + 1e-9:
                print(f"[risk] {symbol}: qty {qty} @ {price:.2f} not viable (remaining ${remaining:.2f})")
                continue

            entries.append(EntryPlan(symbol=symbol, qty=qty, est_price=price, budget=round(cost, 2), score=score))
            committed += cost
            planned_positions += 1

        return entries


# ============================================
# 💼 EXECUTION AGENT
# ============================================

class ExecutionAgent:
    def __init__(self, client: AlpacaClient, config: BotConfig):
        self.client = client
        self.config = config

    def _submit(self, side: str, symbol: str, qty: Any) -> Dict[str, Any]:
        # "8.0" → "8" (Alpaca accepts both, but integer reads stay integers)
        try:
            qty_str = f"{float(qty):g}"
        except (TypeError, ValueError):
            qty_str = str(qty)
        order = {
            "symbol": symbol,
            "qty": qty_str,
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        if self.config.dry_run:
            print(f"[exec] DRY-RUN would {side.upper()} {qty} {symbol}")
            return {"symbol": symbol, "side": side, "qty": qty, "status": "dry-run", "order_id": None}
        ok, data = self.client.submit_order(order)
        if ok and isinstance(data, dict):
            print(f"[exec] {side.upper()} {qty} {symbol} accepted (order {data.get('id')}, status {data.get('status')})")
            return {"symbol": symbol, "side": side, "qty": qty, "status": data.get("status", "accepted"), "order_id": data.get("id")}
        print(f"[exec] {side.upper()} {qty} {symbol} REJECTED: {json.dumps(data)[:300] if data else 'no response'}")
        return {"symbol": symbol, "side": side, "qty": qty, "status": "rejected", "error": data}

    def execute_exits(self, exits: List[ExitPlan]) -> List[Dict[str, Any]]:
        return [self._submit("sell", plan.symbol, plan.qty) for plan in exits]

    def execute_entries(self, entries: List[EntryPlan]) -> List[Dict[str, Any]]:
        return [self._submit("buy", plan.symbol, plan.qty) for plan in entries]


# ============================================
# 📝 REPORT AGENT
# ============================================

@dataclass
class CycleContext:
    started_at: str = ""
    market: Dict[str, Any] = field(default_factory=dict)
    account: Optional[Dict[str, Any]] = None
    regime: Dict[str, Any] = field(default_factory=dict)
    research: List[Dict[str, Any]] = field(default_factory=list)
    positions_before: List[Dict[str, Any]] = field(default_factory=list)
    positions_after: List[Dict[str, Any]] = field(default_factory=list)
    exit_plans: List[ExitPlan] = field(default_factory=list)
    entry_plans: List[EntryPlan] = field(default_factory=list)
    exit_results: List[Dict[str, Any]] = field(default_factory=list)
    entry_results: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = "LIVE"


class ReportAgent:
    """Builds and sends the structured per-cycle ntfy report."""

    def __init__(self, notifier: NtfyNotifier, config: BotConfig):
        self.notifier = notifier
        self.config = config

    def build_report(self, ctx: CycleContext) -> str:
        lines: List[str] = []
        lines.append(f"🤖 TRADING CYCLE REPORT — {ctx.started_at} UTC")
        market_state = "OPEN" if ctx.market.get("is_open") else "CLOSED"
        lines.append(f"Market: {market_state} ({ctx.market.get('source', 'unknown')}) | Mode: {ctx.mode}"
                     + (" | FORCED" if self.config.force_run and not ctx.market.get("is_open") else ""))
        lines.append("")

        account = ctx.account or {}
        lines.append("── ACCOUNT ──")
        lines.append(f"Equity: ${float(account.get('equity', 0) or 0):,.2f}")
        lines.append(f"Buying power: ${float(account.get('buying_power', 0) or 0):,.2f}")
        lines.append(f"Positions: {len(ctx.positions_after or ctx.positions_before)}/{self.config.max_stocks}")
        lines.append("")

        regime = ctx.regime or {}
        lines.append("── MARKET REGIME (SPY) ──")
        lines.append(f"Signal: {regime.get('score', 'n/a')}/100 {regime.get('label', '')} "
                     f"({regime.get('change_percent', 0):+.2f}% over {regime.get('bars', 0)} bars)")
        if regime.get("note"):
            lines.append(f"Note: {regime['note']}")
        lines.append("")

        lines.append("── RESEARCH ──")
        if ctx.research:
            for item in ctx.research:
                lines.append(
                    f"{item.get('symbol'):<5} ${float(item.get('price', 0) or 0):>8.2f}  "
                    f"score {item.get('score', 0):>3}/100  {item.get('signal', '')}  [{item.get('source', '')}]"
                )
                for reason in (item.get("reasons") or [])[:3]:
                    lines.append(f"      · {reason}")
        else:
            lines.append("(no research performed this cycle)")
        lines.append("")

        lines.append("── ACTIONS ──")
        actions = 0
        for plan, result in zip(ctx.exit_plans, ctx.exit_results):
            status = result.get("status", "?")
            mark = "✅" if status not in ("rejected",) else "❌"
            lines.append(f"{mark} SOLD {plan.qty:g} {plan.symbol} — {plan.reason} ({status})")
            actions += 1
        for plan, result in zip(ctx.entry_plans, ctx.entry_results):
            status = result.get("status", "?")
            mark = "✅" if status not in ("rejected",) else "❌"
            lines.append(
                f"{mark} BOUGHT {plan.qty} {plan.symbol} @ ~${plan.est_price:.2f} "
                f"(~${plan.budget:,.2f}, score {plan.score}/100) ({status})"
            )
            actions += 1
        if actions == 0:
            lines.append("No trades this cycle (HOLD).")
        lines.append("")

        lines.append("── PORTFOLIO ──")
        if ctx.positions_after:
            total_value = 0.0
            total_pl = 0.0
            for pos in ctx.positions_after:
                mv = float(pos.get("market_value", 0) or 0)
                pl = float(pos.get("unrealized_pl", 0) or 0)
                plpc = float(pos.get("unrealized_plpc", 0) or 0) * 100
                total_value += mv
                total_pl += pl
                lines.append(f"{pos.get('symbol'):<5} {float(pos.get('qty', 0)):g} sh  "
                             f"value ${mv:,.2f}  P/L ${pl:+,.2f} ({plpc:+.2f}%)")
            lines.append(f"Total position value: ${total_value:,.2f} | unrealized P/L: ${total_pl:+,.2f}")
        else:
            lines.append("Flat — no open positions.")
        lines.append("")
        lines.append("Automated Trading Bot · daily_stock_analysis fork · agents: market/research/risk/execution/report")
        return "\n".join(lines)

    def send_cycle_report(self, ctx: CycleContext) -> bool:
        regime_score = (ctx.regime or {}).get("score")
        actions = len(ctx.exit_results) + len(ctx.entry_results)
        if actions == 0:
            mode = "HOLD"
        elif ctx.entry_results and not ctx.exit_results:
            mode = "BUY"
        elif ctx.exit_results and not ctx.entry_results:
            mode = "SELL"
        else:
            mode = "REBALANCE"

        equity = float((ctx.account or {}).get("equity", 0) or 0)
        title = (
            f"🤖 Trading cycle: {mode} | {actions} action(s) | "
            f"signal {regime_score if regime_score is not None else 'n/a'}/100 | equity ${equity:,.0f}"
        )

        has_stop_loss = any("stop-loss" in plan.reason for plan in ctx.exit_plans)
        regime_exit = any("regime exit" in plan.reason for plan in ctx.exit_plans)
        priority = 4 if (has_stop_loss or regime_exit) else 3
        tags = ["robot_face", "chart_with_upwards_trend"] if actions else ["robot_face"]
        return self.notifier.send(title, self.build_report(ctx), priority=priority, tags=tags)

    def send_market_closed_note(self, ctx: CycleContext) -> bool:
        account_line = ""
        if ctx.account:
            account_line = f" Equity: ${float(ctx.account.get('equity', 0) or 0):,.2f}."
        message = (
            f"US market is CLOSED ({ctx.market.get('source', 'unknown')}) — no trades this cycle.{account_line}\n"
            f"Positions held: {len(ctx.positions_before)}. Next scheduled cycle will re-check the Alpaca clock."
        )
        return self.notifier.send("🤖 Trading cycle: market closed", message, priority=2, tags=["robot_face"])


# ============================================
# 🤖 CYCLE ORCHESTRATION
# ============================================

def run_cycle(
    config: Optional[BotConfig] = None,
    notifier: Optional[NtfyNotifier] = None,
    client: Optional[AlpacaClient] = None,
) -> int:
    """Run one full trading cycle. Returns process exit code."""
    config = config or BotConfig.from_env()
    notifier = notifier or NtfyNotifier(config)
    started_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 60)
    print(f"TRADING BOT CYCLE @ {started_at} UTC")
    print("=" * 60)

    if not config.api_key or not config.secret_key:
        notifier.send(
            "⚠️ Trading bot misconfigured",
            "ALPACA_API_KEY / ALPACA_SECRET_KEY are not set — the bot cannot trade or read the account. "
            "Add them as GitHub Actions secrets (or .env locally) and re-run.",
            priority=5,
            tags=["warning"],
        )
        print("Missing Alpaca credentials.")
        return 2

    client = client or AlpacaClient(config)
    market_agent = MarketAgent(client)
    research_agent = ResearchAgent(client, config)
    risk_agent = RiskAgent(config)
    execution_agent = ExecutionAgent(client, config)
    report_agent = ReportAgent(notifier, config)

    ctx = CycleContext(started_at=started_at, mode="DRY-RUN" if config.dry_run else "LIVE")

    # 1. Market clock
    ctx.market = market_agent.clock_status()
    print(f"Market open: {ctx.market['is_open']} (source: {ctx.market['source']})")
    if not ctx.market["is_open"] and not config.force_run:
        ctx.account = client.get_account()
        ctx.positions_before = client.get_positions()
        if config.notify_when_closed:
            report_agent.send_market_closed_note(ctx)
        print("Market closed — skipping cycle (set BOT_FORCE_RUN=1 to override).")
        return 0

    # 2. Account snapshot
    ctx.account = client.get_account()
    if not ctx.account:
        notifier.send(
            "❌ Trading bot error",
            "Could not fetch the Alpaca account (bad credentials, wrong APCA_API_BASE_URL, or API outage). "
            "No trades were attempted this cycle.",
            priority=5,
            tags=["warning"],
        )
        return 1
    equity = float(ctx.account.get("equity", 0) or 0)
    buying_power = float(ctx.account.get("buying_power", 0) or 0)
    print(f"Equity: ${equity:,.2f} | Buying power: ${buying_power:,.2f}")

    ctx.positions_before = client.get_positions()
    open_orders = client.get_open_orders()
    print(f"Positions: {len(ctx.positions_before)} | Open orders: {len(open_orders)}")

    # 3. Regime signal (used for exits and the report)
    ctx.regime = market_agent.regime_signal()
    print(f"Market regime signal: {ctx.regime.get('score')}/100 ({ctx.regime.get('label')})")

    # 4. Research every watchlist symbol with the repo's analysis engine
    ctx.research = research_agent.research(config.stocks_to_trade)
    for item in ctx.research:
        print(f"  {item['symbol']}: score {item['score']}/100 ({item['signal']}) via {item['source']} @ ${item.get('price', 0):.2f}")
    prices = {item["symbol"]: float(item.get("price", 0) or 0) for item in ctx.research}

    # 5. Exits first (frees cash + de-risks), with double-sell guard
    ctx.exit_plans = risk_agent.plan_exits(ctx.positions_before, prices, open_orders, ctx.regime.get("score"))
    ctx.exit_results = execution_agent.execute_exits(ctx.exit_plans)
    for plan in ctx.exit_plans:
        print(f"  EXIT {plan.symbol} qty {plan.qty:g} — {plan.reason}")

    # 6. Entries sized off equity with reserve + per-position cap.
    # Blocked entirely in a bear regime (score <= sell threshold) — otherwise
    # the bot would liquidate on the regime exit and immediately buy back.
    positions_now = client.get_positions() if ctx.exit_results and not config.dry_run else ctx.positions_before
    open_orders_now = client.get_open_orders() if ctx.exit_results and not config.dry_run else open_orders
    regime_score = ctx.regime.get("score", 50)
    if regime_score <= config.sell_signal_threshold:
        print(f"Regime {regime_score}/100 <= sell threshold {config.sell_signal_threshold} — no new entries this cycle")
        ctx.entry_plans = []
    else:
        ctx.entry_plans = risk_agent.plan_entries(ctx.research, ctx.account, positions_now, open_orders_now)
    ctx.entry_results = execution_agent.execute_entries(ctx.entry_plans)
    for plan in ctx.entry_plans:
        print(f"  ENTRY {plan.symbol} qty {plan.qty} @ ~${plan.est_price:.2f} (score {plan.score})")

    # 7. Final positions + structured report (always sent)
    ctx.positions_after = client.get_positions() if not config.dry_run else positions_now
    report_agent.send_cycle_report(ctx)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    config = BotConfig.from_env()
    if "--force" in argv:
        config.force_run = True
    if "--dry-run" in argv:
        config.dry_run = True
    try:
        return run_cycle(config=config)
    except Exception as exc:  # never die silently — tell the boss
        print(f"Unhandled bot error: {type(exc).__name__}: {exc}")
        try:
            NtfyNotifier(config).send(
                "❌ Trading bot crashed",
                f"{type(exc).__name__}: {exc}\nCycle aborted — inspect the GitHub Actions run log.",
                priority=5,
                tags=["warning"],
            )
        except Exception:
            pass
        return 1


# Backwards-compatible aliases (older docs/flows referenced these helpers).
def get_account_info() -> Optional[Dict[str, Any]]:
    config = BotConfig.from_env()
    return AlpacaClient(config).get_account() if config.api_key else None


def get_positions() -> List[Dict[str, Any]]:
    config = BotConfig.from_env()
    return AlpacaClient(config).get_positions() if config.api_key else []


def get_stock_price(symbol: str) -> float:
    config = BotConfig.from_env()
    return ResearchAgent(AlpacaClient(config), config).latest_price(symbol)


def is_market_open() -> bool:
    config = BotConfig.from_env()
    return MarketAgent(AlpacaClient(config)).clock_status()["is_open"]


def get_market_signal() -> int:
    config = BotConfig.from_env()
    return MarketAgent(AlpacaClient(config)).regime_signal()["score"]


if __name__ == "__main__":
    sys.exit(main())
