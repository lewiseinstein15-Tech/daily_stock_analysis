# -*- coding: utf-8 -*-
"""Telegram remote control for the 24/7 runner (v0.3).

Trade control from your phone with zero extra dependencies (pure
``requests`` long-polling).  Restrict to one chat via
``JEXI_TELEGRAM_CHAT_ID`` — commands from any other chat are ignored.

Supported commands:
    /status   — runner health, gate state, memory stats
    /account  — broker account snapshot
    /positions— open positions
    /pnl      — performance summary
    /pause    — stop NEW trades (resumable)
    /resume   — clear the pause
    /kill     — hard risk halt (survives restarts)
    /clear    — clear a halt (explicit human action)
    /help     — command list
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramController:
    """Long-polling Telegram bot bound to a :class:`MarketRunner247`."""

    def __init__(self, config, runner):
        self.config = config
        self.runner = runner
        self.token = config.telegram_bot_token
        self.allowed_chat = str(config.telegram_chat_id or "")
        self._offset = 0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # low-level
    # ------------------------------------------------------------------
    def _call(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 35.0) -> Any:
        url = API.format(token=self.token, method=method)
        resp = self._session.post(url, json=payload or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {data}")
        return data.get("result")

    def send(self, text: str, chat_id: Optional[str] = None) -> bool:
        cid = chat_id or self.allowed_chat
        if not cid:
            logger.warning("telegram: no chat id configured — dropping message")
            return False
        try:
            self._call("sendMessage", {"chat_id": cid, "text": text[:4000],
                                       "parse_mode": "Markdown"}, timeout=15.0)
            return True
        except Exception as exc:
            logger.error("telegram send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # command handlers
    # ------------------------------------------------------------------
    def handle(self, cmd: str, chat_id: str) -> str:
        cmd = cmd.strip().split("@")[0].lower()
        r = self.runner
        if cmd == "/help":
            return (
                "JEXI Market control:\n"
                "/status — health + gate state\n"
                "/account — broker account\n"
                "/positions — open positions\n"
                "/pnl — performance summary\n"
                "/pause — pause NEW trades\n"
                "/resume — resume trading\n"
                "/kill — risk halt (persists)\n"
                "/clear — clear halt after review"
            )
        if cmd == "/status":
            h = r.health_payload()
            allowed, reason = r.trading_allowed()
            broker = h.get("broker", {})
            mem = h.get("memory", {})
            return (
                f"⚙️ JEXI 24/7 status\n"
                f"broker: {broker.get('broker')} ({'paper' if broker.get('paper') else 'LIVE'})\n"
                f"cycles: {h.get('runner', {}).get('cycles', 0)}\n"
                f"heartbeat: {h.get('runner', {}).get('heartbeat_age_seconds', '-')}s ago\n"
                f"trading allowed: {allowed} ({reason})\n"
                f"halt: {h.get('risk', {}).get('halted', False)} | paused: {h.get('risk', {}).get('paused', False)}\n"
                f"closed trades: {mem.get('n_trades', 0)} | win rate: {mem.get('win_rate', 0):.0%}"
            )
        if cmd == "/account":
            acct = r.broker.get_account()
            return (
                f"💼 Account ({r.broker.name}{' / paper' if r.broker.paper else ' / LIVE'})\n"
                f"equity: {acct.equity:,.2f}\n"
                f"cash: {acct.cash:,.2f}\n"
                f"positions value: {acct.positions_value:,.2f}"
            )
        if cmd == "/positions":
            positions = r.broker.get_positions()
            if not positions:
                return "📭 No open positions."
            lines = [f"• {p.symbol} {p.qty:g} {p.side} @ {p.current_price:g} "
                     f"(PnL {p.unrealized_pl:+,.2f})" for p in positions]
            return "📊 Open positions:\n" + "\n".join(lines)
        if cmd == "/pnl":
            s = r.memory.stats_summary()
            return (
                f"📈 Performance\n"
                f"closed trades: {s.get('n_trades', 0)}\n"
                f"win rate: {s.get('win_rate', 0):.1%}\n"
                f"avg PnL: {s.get('avg_pnl_pct', 0):+.2%}\n"
                f"total PnL: {s.get('total_pnl_pct', 0):+.2%}"
            )
        if cmd == "/pause":
            r.state.set_pause(f"telegram pause by chat {chat_id}")
            return "⏸ Trading paused (new orders blocked). /resume to continue."
        if cmd == "/resume":
            r.state.clear_pause()
            return "▶️ Trading resumed."
        if cmd == "/kill":
            r.state.set_halt(f"telegram kill by chat {chat_id}")
            return "🛑 RISK HALT set. The bot will not trade. /clear to release after review."
        if cmd == "/clear":
            r.state.clear_halt()
            r.state.reset_failures()
            return "✅ Halt cleared. Watchdog counters reset."
        return f"Unknown command {cmd}. Try /help"

    # ------------------------------------------------------------------
    # poll loop (runs in a daemon thread)
    # ------------------------------------------------------------------
    def poll_forever(self) -> None:
        logger.info("telegram controller polling started")
        consecutive_errors = 0
        while True:
            try:
                updates = self._call("getUpdates", {
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                })
                consecutive_errors = 0
                for upd in updates or []:
                    self._offset = max(self._offset, upd.get("update_id", 0) + 1)
                    msg = upd.get("message") or {}
                    chat_id = str((msg.get("chat") or {}).get("id", ""))
                    text = (msg.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    if self.allowed_chat and chat_id != self.allowed_chat:
                        logger.warning("telegram: ignoring chat %s (not allowed)", chat_id)
                        self.send("⛔ Not authorised.", chat_id=chat_id)
                        continue
                    try:
                        reply = self.handle(text, chat_id)
                    except Exception as exc:
                        reply = f"command failed: {exc}"
                    self.send(reply, chat_id=chat_id)
            except Exception as exc:
                consecutive_errors += 1
                logger.error("telegram poll error (%d): %s", consecutive_errors, exc)
                time.sleep(min(60.0, 5.0 * consecutive_errors))
