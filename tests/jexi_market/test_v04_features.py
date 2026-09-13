# -*- coding: utf-8 -*-
"""v0.4 feature tests — TriggerEngine (opportunity timing), plain-English
translation layer, AccountPlanner, broker auto-detection, MCP client,
and the OpportunityRunner watch loop."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jexi_market.config import MarketConfig
from jexi_market.contracts import Confidence, Decision, Evidence, SignalDirection
from jexi_market.data import load_synthetic_frame


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _frame(prices, volume=1_000_000, gap=None, last_volume=None):
    """Build an OHLCV frame from a list of closes.

    ``last_volume`` overrides the volume of the final 5 bars so the
    5d/20d volume-ratio triggers can be exercised (uniform volume gives
    a ratio of exactly 1.0, which fires nothing).
    """
    rows = []
    prev_close = None
    n = len(prices)
    for i, close in enumerate(prices):
        open_ = close if prev_close is None else prev_close
        if gap is not None and i == n - 1:
            open_ = prev_close * (1 + gap)
        vol = volume
        if last_volume is not None and i >= n - 5:
            vol = last_volume
        rows.append({
            "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(open_, 4),
            "high": round(max(open_, close) * 1.001, 4),
            "low": round(min(open_, close) * 0.999, 4),
            "close": round(close, 4),
            "volume": vol,
        })
        prev_close = close
    return pd.DataFrame(rows)


class _StubSnapshot:
    """Minimal MarketSnapshot stand-in (duck-typed for triggers)."""

    def __init__(self, df):
        self.ok = True
        self.df = df


class _StubDataClient:
    def __init__(self, frames):
        self._frames = frames

    def get_daily(self, symbol, days=120, **kwargs):
        df = self._frames.get(symbol)
        if df is None:
            from jexi_market.data import MarketSnapshot
            return MarketSnapshot(symbol=symbol, ok=False, error="no data")
        return _StubSnapshot(df)


def _decision(symbol="AAPL", direction=SignalDirection.LONG, conf=0.8,
              entry=100.0, stop=95.0, target=110.0, fraction=0.10):
    return Decision(
        symbol=symbol, direction=direction,
        confidence=Confidence(agreement=0.8, data_freshness=0.9,
                              evidence_count=3),
        entry=entry, stop_loss=stop, take_profit=target,
        position_fraction=fraction,
        thesis="trend up; volume strong",
        evidence=(Evidence(source="technical", claim="Price has been climbing steadily for two weeks"),),
        supporting_agents=("technical",),
    )


class _StubReporter:
    def __init__(self):
        self.calls = []

    def publish(self, title, message, *, priority="default", tags=None, **kw):
        self.calls.append({"title": title, "message": message, "priority": priority})
        return True


class _StubBroker:
    name = "stub"
    paper = True
    configured = True

    def __init__(self, equity=100_000.0, cash=100_000.0, positions=(), prices=None):
        self._equity = equity
        self._cash = cash
        self._positions = list(positions)
        self._prices = prices or {}

    def get_account(self):
        from jexi_market.brokers.base import BrokerAccount
        return BrokerAccount(equity=self._equity, cash=self._cash)

    def get_positions(self):
        return list(self._positions)

    def get_latest_price(self, symbol):
        return self._prices.get(symbol)

    def status(self):
        return {"broker": "stub", "paper": True, "configured": True}


# ---------------------------------------------------------------------------
# TriggerEngine — trades at the RIGHT time
# ---------------------------------------------------------------------------

def _engine(frames, cooldown=None, clock=time.time):
    from jexi_market.triggers import TriggerConfig, TriggerEngine
    store = {} if cooldown is None else cooldown
    tcfg = TriggerConfig(cooldown_seconds=3600, min_rows=10)
    return TriggerEngine(
        MarketConfig(), data_client=_StubDataClient(frames), trigger_config=tcfg,
        cooldown_store=store, clock=clock,
    )


def test_breakout_proximity_fires_near_20d_high():
    # Steadily rising closes: last close sits right at the 20d high zone.
    prices = [100 + i * 0.5 for i in range(40)]
    eng = _engine({"AAPL": _frame(prices)})
    events = eng.evaluate_symbol("AAPL")
    kinds = {e.kind for e in events}
    assert "breakout_proximity" in kinds
    ev = next(e for e in events if e.kind == "breakout_proximity")
    assert ev.direction_hint == "up"
    assert "$" in ev.plain_reason and "AAPL" in ev.plain_reason
    assert ev.priority >= 3


def test_momentum_burst_with_volume():
    prices = [100.0] * 30 + [101, 103, 106, 110]
    eng = _engine({"AAPL": _frame(prices, volume=1_000_000, last_volume=5_000_000)})
    events = eng.evaluate_symbol("AAPL")
    kinds = {e.kind for e in events}
    assert "momentum_burst" in kinds


def test_oversold_bounce_fires_when_rsi_turns_up():
    # Steep decline then two stabilising/up closes -> RSI low but rising.
    prices = [100 - i * 1.2 for i in range(30)] + [64.2, 64.6]
    eng = _engine({"AAPL": _frame(prices)})
    events = eng.evaluate_symbol("AAPL")
    kinds = {e.kind for e in events}
    assert "oversold_bounce" in kinds
    ev = next(e for e in events if e.kind == "oversold_bounce")
    assert "sold off" in ev.plain_reason or "turn" in ev.plain_reason


def test_volume_spike_fires():
    prices = [100.0] * 25
    eng = _engine({"AAPL": _frame(prices, volume=1_000_000, last_volume=9_000_000)})
    events = eng.evaluate_symbol("AAPL")
    kinds = {e.kind for e in events}
    assert "volume_spike" in kinds


def test_gap_event_fires():
    prices = [100.0] * 25 + [100.0]
    eng = _engine({"AAPL": _frame(prices, gap=0.05)})
    events = eng.evaluate_symbol("AAPL")
    kinds = {e.kind for e in events}
    assert "gap_event" in kinds


def test_exit_triggers_near_stop_and_target():
    eng = _engine({})
    trade = {"symbol": "AAPL", "entry": 100.0, "stop_loss": 95.0,
             "take_profit": 110.0, "direction": "long"}
    # price has fallen 76% of the way from entry to stop -> warn
    near_stop = eng._exit_triggers("AAPL", trade, price=96.2)
    assert any(e.kind == "near_stop" for e in near_stop)
    # price covered 96% of the way to target -> almost there
    near_target = eng._exit_triggers("AAPL", trade, price=109.6)
    assert any(e.kind == "near_target" for e in near_target)
    # mid-range: neither edge
    mid = eng._exit_triggers("AAPL", trade, price=105.0)
    assert not any(e.kind in ("near_stop", "near_target") for e in mid)
    # short direction: price rising 80% of the way to the stop
    short_trade = {"symbol": "TSLA", "entry": 100.0, "stop_loss": 105.0,
                   "take_profit": 90.0, "direction": "short"}
    short_near_stop = eng._exit_triggers("TSLA", short_trade, price=104.0)
    assert any(e.kind == "near_stop" for e in short_near_stop)


def test_cooldown_suppresses_repeats_until_window_passes():
    prices = [100 + i * 0.5 for i in range(40)]
    frames = {"AAPL": _frame(prices)}
    now = [1_000_000.0]
    eng = _engine(frames, cooldown={}, clock=lambda: now[0])
    first = eng.evaluate_symbol("AAPL")
    assert first, "first scan must fire"
    kinds = {e.kind for e in first}
    # Second scan immediately: all suppressed by cooldown.
    assert eng.evaluate_symbol("AAPL") == []
    # Advance past the cooldown window: fires again.
    now[0] += 3601
    again = eng.evaluate_symbol("AAPL")
    assert {e.kind for e in again} == kinds


def test_bad_symbol_yields_no_events():
    eng = _engine({})
    assert eng.evaluate_symbol("NOPE") == []


def test_evaluate_universe_sorts_by_priority():
    hot = _frame([100 + i * 0.5 for i in range(40)])
    quiet = _frame([100.0] * 25, volume=1_000_000, last_volume=9_000_000)  # volume spike (p2)
    eng = _engine({"HOT": hot, "QUIET": quiet})
    events = eng.evaluate_universe(["QUIET", "HOT"])
    assert events, "at least one trigger must fire"
    priorities = [e.priority for e in events]
    assert priorities == sorted(priorities, reverse=True)


# ---------------------------------------------------------------------------
# Plain-English layer
# ---------------------------------------------------------------------------

JARGON = ("rsi", "macd", "sma", "position", "long", "short", "flat",
          "bollinger", "fraction", "kelly", "regime")


def _assert_plain(text):
    low = text.lower()
    for word in JARGON:
        assert word not in low, f"jargon {word!r} leaked: {text!r}"


def test_translate_decision_long_executed_has_dollars_and_no_jargon():
    from jexi_market.plain_english import translate_decision
    d = _decision(entry=332.27, stop=320.21, target=356.40)
    title, body = translate_decision(d, account_equity=100_000.0,
                                     position_value=10_000.0, executed=True)
    assert "AAPL" in title
    assert "$10,000.00" in body
    assert "$332.27" in body
    assert "$320.21" in body   # safety net
    assert "$356.40" in body   # goal
    _assert_plain(title + body)
    assert len(title + body) < 900


def test_translate_decision_flat_is_honest_nothing_to_do():
    from jexi_market.plain_english import translate_decision
    d = _decision(direction=SignalDirection.FLAT)
    title, body = translate_decision(d)
    assert "nothing to do" in title.lower()
    _assert_plain(body)


def test_translate_trade_closed_profit_and_loss():
    from jexi_market.plain_english import translate_trade_closed
    win = translate_trade_closed("AAPL", entry=100, exit_price=112, profit=12.0)
    assert "$12.00" in win and "profit" in win.lower()
    loss = translate_trade_closed("AAPL", entry=100, exit_price=96, profit=-4.0)
    assert "$4.00" in loss and "loss" in loss.lower()
    _assert_plain(win + loss)


def test_translate_account_summary_paper_mode():
    from jexi_market.plain_english import translate_account_summary
    text = translate_account_summary(broker_name="paper", equity=101_250.0,
                                     cash=64_000.0, n_positions=2,
                                     open_profit=1250.0, paper=True)
    assert "$101,250.00" in text
    assert "practice mode" in text
    _assert_plain(text)


def test_translate_plan_mentions_limits():
    from jexi_market.plain_english import translate_plan
    text = translate_plan(equity=100_000.0, cash=50_000.0, max_new_positions=3,
                          risk_per_trade_amount=2_000.0, daily_budget_left=4_000.0,
                          watch_out=["AAPL would be sold automatically if it falls to $95.00."],
                          notes=[])
    assert "$2,000.00" in text
    assert "3" in text
    _assert_plain(text)


def test_translate_watchdog_halt_is_calm():
    from jexi_market.plain_english import translate_watchdog_halt
    text = translate_watchdog_halt(5, "data error boom")
    assert "protect your money" in text
    _assert_plain(text)


def test_jargon_filter_strips_leaked_terms():
    from jexi_market.plain_english import _ensure_no_jargon
    assert "rsi" not in _ensure_no_jargon("the RSI says buy").lower()
    assert "Position" not in _ensure_no_jargon("Position opened")


# ---------------------------------------------------------------------------
# AccountPlanner
# ---------------------------------------------------------------------------

def test_planner_builds_plan_from_stub_account(tmp_path):
    from jexi_market.planner import AccountPlanner
    from jexi_market.memory import PerformanceMemory
    from jexi_market.risk.state import RiskStateStore

    broker = _StubBroker(equity=100_000.0, cash=60_000.0)
    plan = AccountPlanner(MarketConfig(), broker=broker,
                          memory=PerformanceMemory(":memory:"),
                          state_store=RiskStateStore(str(tmp_path / "s.sqlite"))).build()
    assert plan.equity == 100_000.0
    assert plan.cash == 60_000.0
    assert plan.max_new_positions > 0
    # risk budget = equity * max_risk_per_trade (2% default)
    assert plan.risk_per_trade_amount == pytest.approx(2_000.0)
    assert plan.daily_budget_left == pytest.approx(4_000.0)
    assert not plan.halted and not plan.paused


def test_planner_respects_halt(tmp_path):
    from jexi_market.planner import AccountPlanner
    from jexi_market.risk.state import RiskStateStore
    store = RiskStateStore(str(tmp_path / "s.sqlite"))
    store.set_halt("test halt")
    plan = AccountPlanner(MarketConfig(), broker=_StubBroker(),
                          memory=None, state_store=store).build()
    assert plan.halted
    assert plan.max_new_positions == 0
    assert any("HALTED" in n for n in plan.notes)


def test_planner_watch_outs_from_open_trades(tmp_path):
    from jexi_market.planner import AccountPlanner
    from jexi_market.memory import PerformanceMemory
    mem = PerformanceMemory(":memory:")
    mem.record_decision(_decision(entry=100.0, stop=95.0, target=110.0))
    plan = AccountPlanner(MarketConfig(), broker=_StubBroker(), memory=mem,
                          state_store=None).build()
    assert any("AAPL" in w and "$95.00" in w for w in plan.watch_out)


# ---------------------------------------------------------------------------
# Broker auto-detection (any market via env / git secrets)
# ---------------------------------------------------------------------------

def test_detect_alpaca_from_env():
    from jexi_market.brokers.factory import detect_configured_broker
    name, reason = detect_configured_broker({
        "ALPACA_API_KEY": "K", "ALPACA_SECRET_KEY": "S"})
    assert name == "alpaca"


def test_detect_alpaca_secret_alias():
    from jexi_market.brokers.factory import detect_configured_broker
    name, _ = detect_configured_broker({
        "ALPACA_API_KEY": "K", "ALPACA_API_SECRET": "S"})
    assert name == "alpaca"


def test_detect_binance_pocketoption_and_paper_fallback():
    from jexi_market.brokers.factory import detect_configured_broker
    assert detect_configured_broker({
        "BINANCE_API_KEY": "K", "BINANCE_API_SECRET": "S"})[0] == "binance"
    assert detect_configured_broker({"POCKET_OPTION_SSID": "x"})[0] == "pocketoption"
    assert detect_configured_broker({
        "MT5_LOGIN": "1", "MT5_PASSWORD": "p", "MT5_SERVER": "s"})[0] == "mt5"
    name, reason = detect_configured_broker({})
    assert name == "paper" and "paper" in reason.lower()


def test_detect_prefers_alpaca_when_multiple_present():
    from jexi_market.brokers.factory import detect_configured_broker
    name, _ = detect_configured_broker({
        "ALPACA_API_KEY": "K", "ALPACA_API_SECRET": "S",
        "BINANCE_API_KEY": "K2", "BINANCE_API_SECRET": "S2"})
    assert name == "alpaca"


def test_partial_credentials_fall_through_to_paper():
    from jexi_market.brokers.factory import detect_configured_broker
    # key without secret must NOT select alpaca
    name, _ = detect_configured_broker({"ALPACA_API_KEY": "K"})
    assert name == "paper"


def test_build_broker_auto_selects_paper_without_creds(monkeypatch):
    from jexi_market.brokers.factory import build_broker
    for var in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_SECRET_KEY",
                "BINANCE_API_KEY", "BINANCE_API_SECRET", "POCKET_OPTION_SSID",
                "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JEXI_BROKER", "auto")
    broker = build_broker(MarketConfig())
    assert broker.name == "paper" and broker.paper


# ---------------------------------------------------------------------------
# MCP client (Model Context Protocol over stdio)
# ---------------------------------------------------------------------------

_FAKE_MCP_SERVER = r'''
import sys, json

def send(msg):
    body = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    sys.stdout.buffer.flush()

def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        try:
            k, v = line.decode("utf-8", "replace").split(":", 1)
        except ValueError:
            continue
        headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", "0"))
    if not n:
        return None
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))

while True:
    req = read_msg()
    if req is None:
        break
    method = req.get("method", "")
    if "id" not in req:
        continue  # notification (e.g. initialized)
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": req["id"], "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "fake-news", "version": "1.2"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [
            {"name": "get_news", "description": "headlines",
             "inputSchema": {"type": "object"}}]}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": req["id"], "result": {
            "content": [{"type": "text", "text": "MARKETS CALM"}], "isError": False}})
'''


def test_mcp_stdio_client_full_handshake(tmp_path):
    from jexi_market.mcp import McpStdioClient
    server = tmp_path / "fake_mcp_server.py"
    server.write_text(_FAKE_MCP_SERVER)
    client = McpStdioClient("fake", sys.executable, [str(server)], timeout=20)
    try:
        assert client.initialize()
        assert client.server_info.get("name") == "fake-news"
        tools = client.list_tools()
        assert [t["name"] for t in tools] == ["get_news"]
        result = client.call_tool("get_news", {"symbol": "AAPL"})
        assert result["content"][0]["text"] == "MARKETS CALM"
        assert client.connected
    finally:
        client.close()


def test_mcp_connector_and_tool_registry(tmp_path):
    from jexi_market.mcp import McpConnector
    from jexi_market.tools.registry import ToolRegistry
    server = tmp_path / "fake_mcp_server.py"
    server.write_text(_FAKE_MCP_SERVER)
    conn = McpConnector(specs=[{"name": "news", "command": sys.executable,
                                "args": [str(server)]}])
    try:
        ready = conn.connect_all()
        assert ready == {"news": ["get_news"]}
        registry = ToolRegistry()
        registry.register_mcp(conn.clients["news"])
        assert "mcp.get_news" in registry.list_names()
        res = registry.call("mcp.get_news", {})
        assert res.ok and res.data["content"][0]["text"] == "MARKETS CALM"
    finally:
        conn.close()


def test_mcp_connector_skips_dead_server():
    from jexi_market.mcp import McpConnector
    conn = McpConnector(specs=[{"name": "ghost", "command": "definitely-not-a-real-binary-xyz"}])
    ready = conn.connect_all()
    assert ready == {}  # broken MCP server must never take the loop down


def test_mcp_disabled_without_config(monkeypatch):
    from jexi_market.mcp import McpConnector
    monkeypatch.setattr(MarketConfig, "mcp_servers_json", "", raising=False)
    conn = McpConnector(MarketConfig())
    assert conn.connect_all() == {}


# ---------------------------------------------------------------------------
# OpportunityRunner — the watch loop
# ---------------------------------------------------------------------------

class _StubBoss:
    """Stand-in for MarketBoss inside the pipeline."""

    def __init__(self, frames, decisions):
        self.data_client = _StubDataClient(frames)
        self._decisions = decisions

    def analyze_symbol(self, symbol, days=120):
        class _R:
            pass
        r = _R()
        r.decision = self._decisions.get(symbol)
        r.gate_approved = True
        r.gate_violations = []
        return r


class _StubPipeline:
    def __init__(self, boss):
        self.boss = boss


class _StubLifecycle:
    def __init__(self, broker, memory):
        self._broker = broker
        self._memory = memory
        self.opened = []

    def open_position(self, decision, equity, price, paper_mode=True):
        from jexi_market.execution.lifecycle import ExecutionOutcome
        self.opened.append((decision.symbol, price))
        return ExecutionOutcome(ok=True, order_id="o1", filled_qty=10,
                                filled_price=price, bracket=True)

    def check_exits(self, prices):
        closed = []
        for sym, px in prices.items():
            t = self._open.get(sym)
            if not t:
                continue
            if px <= t["stop_loss"]:
                closed.append({"symbol": sym, "reason": "stop_loss",
                               "venue": False, "exit_price": px})
        return closed

    _open = {}


class _StubState:
    def __init__(self):
        self.halted = False
        self.paused = False
        self.failures = 0

    def is_halted(self):
        return self.halted

    def is_paused(self):
        return self.paused

    def load(self):
        return {"halt_reason": "x" if self.halted else ""}

    def bump_failures(self):
        self.failures += 1
        return self.failures

    def reset_failures(self):
        self.failures = 0

    def set_halt(self, reason):
        self.halted = True

    def heartbeat(self):
        pass


class _StubMemory:
    """recent_trades() stub for the watch loop's exit management."""

    def __init__(self, trades):
        self._trades = trades

    def recent_trades(self, limit=100):
        return list(self._trades)


def _make_runner(frames, decisions, broker=None, tmp=None):
    from jexi_market.watch import OpportunityRunner
    cfg = MarketConfig()
    cfg.notify_triggers = False  # silence trigger pings in most tests
    cfg.notify_daily_plan = False  # planner is stubbed in most tests
    cfg.trade_247 = True         # bypass the equity-session gate in tests
    broker = broker or _StubBroker()
    lifecycle = _StubLifecycle(broker, None)
    runner = OpportunityRunner.__new__(OpportunityRunner)
    runner.config = cfg
    runner.broker = broker
    runner.memory = None
    runner.state = _StubState()
    runner.audit = _StubAudit()
    runner.lifecycle = lifecycle
    runner.pipeline = _StubPipeline(_StubBoss(frames, decisions))
    runner.triggers = _make_engine_for_runner(frames)
    runner.reporter = _StubReporter()
    runner.planner = None
    from jexi_market.watch import WatchStats
    runner.stats = WatchStats()
    runner._telegram = None
    runner._stop = __import__("threading").Event()
    return runner, lifecycle


class _StubAudit:
    def __init__(self):
        self.events = []

    def event(self, kind, **fields):
        self.events.append((kind, fields))


def _make_engine_for_runner(frames):
    from jexi_market.triggers import TriggerConfig, TriggerEngine
    return TriggerEngine(MarketConfig(), data_client=_StubDataClient(frames),
                         trigger_config=TriggerConfig(cooldown_seconds=0, min_rows=10))


def test_watch_once_no_triggers_no_deep_dive():
    flat = _frame([100.0] * 25, volume=100_000)  # nothing special
    runner, lifecycle = _make_runner({"AAPL": flat}, {})
    result = runner.watch_once()
    assert result["watched"] is True
    assert result["deep_dives"] == []
    assert lifecycle.opened == []


def test_watch_once_trigger_runs_deep_dive_and_orders():
    hot = _frame([100 + i * 0.5 for i in range(40)])
    runner, lifecycle = _make_runner(
        {"AAPL": hot},
        {"AAPL": _decision(entry=hot["close"].iloc[-1])},
    )
    runner.config.notify_triggers = True
    result = runner.watch_once()
    assert result["triggers"], "breakout trigger must fire"
    assert result["deep_dives"], "high-priority trigger must deep dive"
    assert result["deep_dives"][0]["outcome"] == "ordered"
    assert lifecycle.opened and lifecycle.opened[0][0] == "AAPL"
    # plain-English notifications were sent
    titles = [c["title"] for c in runner.reporter.calls]
    assert any("AAPL" in t for t in titles)


def test_watch_once_halted_never_deep_dives_but_still_exits():
    hot = _frame([100 + i * 0.5 for i in range(40)])
    runner, lifecycle = _make_runner({"AAPL": hot}, {"AAPL": _decision()})
    runner.memory = _StubMemory([
        {"symbol": "AAPL", "outcome": "open", "entry": 100.0,
         "stop_loss": 999.0, "take_profit": 200.0, "direction": "long"}])
    runner.lifecycle._open = {"AAPL": {"stop_loss": 999.0}}  # stub exit logic
    runner.state.halted = True
    broker = runner.broker
    broker._prices["AAPL"] = 95.0
    result = runner.watch_once()
    assert result["trading_allowed"] is False
    assert result["deep_dives"] == []
    assert result["exits_closed"], "exit management must run even when halted"
    closed = result["exits_closed"][0]
    assert closed["symbol"] == "AAPL"
    assert closed["profit"] == pytest.approx(95.0 - 100.0, abs=0.01)


def test_watch_once_low_confidence_does_not_order():
    hot = _frame([100 + i * 0.5 for i in range(40)])
    d = _decision()
    object.__setattr__(d, "confidence", Confidence(agreement=0.2, data_freshness=0.2, evidence_count=0))
    runner, lifecycle = _make_runner({"AAPL": hot}, {"AAPL": d})
    runner.config.min_confidence = 0.99
    result = runner.watch_once()
    assert result["deep_dives"][0]["outcome"] == "not_sure_yet"
    assert lifecycle.opened == []


def test_watchdog_halt_after_consecutive_failures():
    flat = _frame([100.0] * 25)
    runner, _ = _make_runner({"AAPL": flat}, {})
    runner.config.max_consecutive_failures = 2

    def boom():
        raise RuntimeError("data exploded")

    runner.triggers.evaluate_universe = boom  # type: ignore
    runner.watch_once()
    runner.watch_once()
    assert runner.state.halted
    # emergency notification sent
    titles = [c["title"] for c in runner.reporter.calls]
    assert any("paused" in t.lower() for t in titles)


def test_watch_stats_accumulate():
    hot = _frame([100 + i * 0.5 for i in range(40)])
    runner, lifecycle = _make_runner({"AAPL": hot}, {"AAPL": _decision()})
    runner.watch_once()
    assert runner.stats.watches == 1
    assert runner.stats.triggers_fired >= 1
    assert runner.stats.pipeline_runs == 1
    assert runner.stats.orders_placed == 1
