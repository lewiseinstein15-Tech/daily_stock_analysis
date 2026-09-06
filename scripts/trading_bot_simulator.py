#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Alpaca + ntfy simulator for automated_trading_bot.py.

Lets you run the trading bot END-TO-END without any cloud credentials — useful
for validating the pipeline (clock → research → risk → execution → ntfy report)
before pointing it at a real Alpaca paper account.

Usage:
    python scripts/trading_bot_simulator.py --port 8787 --scenario bull &

    APCA_API_BASE_URL=http://127.0.0.1:8787 \
    ALPACA_DATA_BASE_URL=http://127.0.0.1:8787 \
    NTFY_SERVER=http://127.0.0.1:8787 \
    NTFY_TOPIC=sim \
    ALPACA_API_KEY=sim ALPACA_SECRET_KEY=sim \
    python automated_trading_bot.py

Admin endpoints (JSON):
    GET  /__admin/state      current simulated world
    POST /__admin/state      merge keys into the world (clock_open, account,
                             positions, open_orders, quotes, bars_closes,
                             ntfy_max_bytes)
    POST /__admin/reset      {"scenario": "bull"} → restore a preset
    GET  /__admin/captured   every request the bot made (orders, ntfy pushes)

Presets: bull (buyable uptrend), stoploss (a losing position + a pending sell
that must not be double-sold), crash (bear regime liquidates everything),
closed (market closed → bot only notifies).

Simulated behaviour mirrors the real APIs closely enough for the bot:
  * market orders fill instantly at the latest ask and update positions
  * ntfy JSON publish rejects oversized messages with HTTP 413, exactly like
    ntfy.sh, and accepts raw-body file attachments on /<topic>
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
_STATE: dict = {}
_CAPTURED: list = []


def _expand_bars(closes):
    return [
        {
            "t": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}T05:00:00Z",
            "o": round(c * 0.995, 2),
            "h": round(c * 1.01, 2),
            "l": round(c * 0.99, 2),
            "c": round(c, 2),
            "v": 1_000_000 + i * 1_000,
        }
        for i, c in enumerate(closes)
    ]


def _uptrend_with_pullbacks(n=120, drift=0.0035, dip_every=6, dip=-0.012, start=100.0):
    """Trending up with periodic small pullbacks (keeps RSI out of the
    overbought zone — a monotonic series scores as 'extended', by design)."""
    closes, c = [], start
    for i in range(n):
        c *= 1 + drift
        if i % dip_every == 2:  # dips mid-cycle so the series ENDS with a recovery leg
            c *= 1 + dip
        closes.append(round(c, 2))
    return closes


def scenario_state(name: str) -> dict:
    uptrend = _uptrend_with_pullbacks()
    sideways = [round(100 * (0.9992 ** i), 2) for i in range(120)]  # soft drift down → not buyable
    downtrend = [round(160 * (0.9965 ** i), 2) for i in range(120)]

    base = {
        "clock_open": True,
        "account": {"equity": "100000", "buying_power": "100000", "cash": "100000", "status": "ACTIVE"},
        "positions": [],
        "open_orders": [],
        "quotes": {
            "AAPL": {"ap": 150.0, "bp": 149.9},
            "MSFT": {"ap": 400.0, "bp": 399.8},
            "NVDA": {"ap": 180.0, "bp": 179.9},
            "SPY": {"ap": 104.6, "bp": 104.5},
        },
        "bars_closes": {"AAPL": uptrend, "MSFT": sideways, "NVDA": downtrend, "SPY": [100, 101, 102, 103, 104.5]},
        "ntfy_max_bytes": 4096,
    }
    if name == "stoploss":
        base["positions"] = [
            {"symbol": "NVDA", "qty": "8", "avg_entry_price": "200", "current_price": "180",
             "market_value": "1440", "unrealized_pl": "-160", "unrealized_plpc": "-0.1"},
            {"symbol": "AAPL", "qty": "5", "avg_entry_price": "100", "current_price": "112",
             "market_value": "560", "unrealized_pl": "60", "unrealized_plpc": "0.12"},
        ]
        base["quotes"]["AAPL"] = {"ap": 112.0, "bp": 111.9}
        # An exit order for AAPL is already in flight → bot must NOT sell it again.
        base["open_orders"] = [{"id": "pending-1", "symbol": "AAPL", "side": "sell", "qty": "5", "status": "new"}]
        base["bars_closes"]["SPY"] = [100, 100.5, 100.2, 99.8, 100.1]  # neutral regime
    elif name == "crash":
        base["positions"] = [
            {"symbol": "AAPL", "qty": "5", "avg_entry_price": "100", "current_price": "101",
             "market_value": "505", "unrealized_pl": "5", "unrealized_plpc": "0.01"},
        ]
        base["quotes"]["AAPL"] = {"ap": 101.0, "bp": 100.9}  # quote must match the position's world
        base["bars_closes"]["SPY"] = [100, 99, 98, 96.5, 95]  # regime 15 → liquidate
    elif name == "closed":
        base["clock_open"] = False
    elif name != "bull":
        raise SystemExit(f"unknown scenario: {name} (choose bull|stoploss|crash|closed)")
    return base


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    # -- helpers -------------------------------------------------------------
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, kind, **extra):
        with _LOCK:
            _CAPTURED.append({"kind": kind, "path": self.path, **extra})

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # -- routes ----------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        with _LOCK:
            state = json.loads(json.dumps(_STATE))
        self._record("GET", path=path)

        if path == "/__admin/state":
            return self._send(200, state)
        if path == "/__admin/captured":
            with _LOCK:
                return self._send(200, list(_CAPTURED))
        if path == "/v2/clock":
            return self._send(200, {"is_open": state["clock_open"], "timestamp": "2026-09-05T20:00:00Z"})
        if path == "/v2/account":
            return self._send(200, state["account"])
        if path == "/v2/positions":
            return self._send(200, state["positions"])
        if path == "/v2/orders":
            return self._send(200, state["open_orders"])
        if path.startswith("/v2/stocks/") and path.endswith("/quotes/latest"):
            symbol = path.split("/")[3]
            quote = state["quotes"].get(symbol)
            if not quote:
                return self._send(404, {"message": f"no quote for {symbol}"})
            return self._send(200, {"symbol": symbol, "quote": quote})
        if path.startswith("/v2/stocks/") and path.endswith("/bars"):
            symbol = path.split("/")[3]
            closes = state["bars_closes"].get(symbol, [])
            return self._send(200, {"bars": {symbol: _expand_bars(closes)}, "symbol": symbol})
        return self._send(404, {"message": f"simulator has no route {path}"})

    def do_POST(self):
        path = self.path.split("?")[0]
        raw = self._body()

        if path == "/__admin/reset":
            scenario = (json.loads(raw or b"{}") or {}).get("scenario", "bull")
            with _LOCK:
                _STATE.clear()
                _STATE.update(scenario_state(scenario))
                _CAPTURED.clear()
            return self._send(200, {"reset": scenario})
        if path == "/__admin/state":
            with _LOCK:
                _STATE.update(json.loads(raw or b"{}"))
            return self._send(200, {"ok": True})

        if path == "/v2/orders":
            order = json.loads(raw or b"{}")
            self._record("ORDER", order=order)
            with _LOCK:
                order_id = f"sim-order-{len(_CAPTURED)}"
                order.update({"id": order_id, "status": "filled", "filled_qty": order.get("qty"), "filled_avg_price": None})
                # Instant market fill at the latest ask; keep positions coherent.
                symbol = order.get("symbol")
                price = _STATE["quotes"].get(symbol, {}).get("ap", 0)
                qty = float(order.get("qty", 0))
                positions = _STATE["positions"]
                if order.get("side") == "buy":
                    positions.append({
                        "symbol": symbol, "qty": order.get("qty"), "avg_entry_price": str(price),
                        "current_price": str(price), "market_value": str(round(price * qty, 2)),
                        "unrealized_pl": "0", "unrealized_plpc": "0",
                    })
                    cash = float(_STATE["account"]["buying_power"]) - price * qty
                    _STATE["account"]["buying_power"] = str(round(max(cash, 0), 2))
                else:
                    for pos in positions:
                        if pos["symbol"] == symbol:
                            remaining = float(pos["qty"]) - qty
                            pos["qty"] = str(remaining)
                            if remaining <= 0:
                                positions.remove(pos)
                            break
                    _STATE["open_orders"] = [o for o in _STATE["open_orders"] if o.get("symbol") != symbol or o.get("side") != "sell"]
                order["filled_avg_price"] = str(price)
            return self._send(200, order)

        # --- ntfy simulation ---
        if path == "/":  # JSON publish API
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            self._record("NTFY_JSON", payload=payload)
            message = str(payload.get("message", ""))
            with _LOCK:
                limit = _STATE.get("ntfy_max_bytes", 4096)
            if len(message.encode("utf-8")) > limit:
                return self._send(413, {"code": 40011, "error": "message too large"})
            return self._send(200, {"id": "sim-msg", "time": 1_780_000_000})

        # raw-body attachment publish to /<topic>
        filename = self.headers.get("Filename")
        self._record("NTFY_ATTACHMENT", filename=filename, title=self.headers.get("Title"), body=raw.decode("utf-8", "replace"))
        return self._send(200, {"id": "sim-attach", "attachment": {"name": filename}})


class TradingBotSimulator:
    """In-process simulator used by tests/test_trading_bot_e2e.py."""

    def __init__(self, scenario="bull"):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.reset(scenario)
        self._thread.start()

    def reset(self, scenario="bull"):
        with _LOCK:
            _STATE.clear()
            _STATE.update(scenario_state(scenario))
            _CAPTURED.clear()

    def update_state(self, **kwargs):
        with _LOCK:
            _STATE.update(kwargs)

    @property
    def captured(self):
        with _LOCK:
            return list(_CAPTURED)

    def captured_of(self, kind):
        return [c for c in self.captured if c["kind"] == kind]

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--scenario", default="bull", choices=["bull", "stoploss", "crash", "closed"])
    args = parser.parse_args()

    with _LOCK:
        _STATE.update(scenario_state(args.scenario))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"Trading bot simulator listening on http://127.0.0.1:{args.port} (scenario: {args.scenario})")
    print("Point the bot at it:")
    print(f"  APCA_API_BASE_URL=http://127.0.0.1:{args.port} ALPACA_DATA_BASE_URL=http://127.0.0.1:{args.port} \\")
    print(f"  NTFY_SERVER=http://127.0.0.1:{args.port} NTFY_TOPIC=sim ALPACA_API_KEY=sim ALPACA_SECRET_KEY=sim \\")
    print("  python automated_trading_bot.py")
    server.serve_forever()


if __name__ == "__main__":
    main()
