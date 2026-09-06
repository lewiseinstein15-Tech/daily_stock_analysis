# -*- coding: utf-8 -*-
"""Unit tests for automated_trading_bot.py (multi-agent trading pipeline).

All HTTP traffic is mocked — the suite never touches Alpaca or ntfy. Scenarios
covered: correct API hosts, data-API payload parsing, market clock (API +
fallback), regime scoring, take-profit/stop-loss/regime exits, the double-sell
guard, equity-based position sizing, entry filters, ntfy JSON publish with
Bearer auth and timeouts, the long-report attachment fallback (HTTP 413 fix),
structured per-cycle reports, dry-run mode, misconfiguration alerts, forced
runs on a closed market, and both research paths (repo analyzer + built-in).
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import automated_trading_bot as bot  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="ok"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class RequestRecorder:
    """Routes requests.get/post by URL substring and records every call."""

    def __init__(self, get_routes=None, post_routes=None):
        self.get_routes = dict(get_routes or {})
        self.post_routes = dict(post_routes or {})
        self.get_calls = []
        self.post_calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        for matcher, handler in self.get_routes.items():
            if matcher in url:
                return handler(url, params) if callable(handler) else handler
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers=None, json=None, data=None, timeout=None, **kwargs):
        self.post_calls.append(
            {"url": url, "headers": headers, "json": json, "data": data, "timeout": timeout, **kwargs}
        )
        for matcher, handler in self.post_routes.items():
            if matcher in url:
                return handler(url, json, data, headers) if callable(handler) else handler
        raise AssertionError(f"unexpected POST {url}")

    # -- assertions helpers ---------------------------------------------------
    def posts_to(self, substring):
        return [call for call in self.post_calls if substring in call["url"]]

    def gets_to(self, substring):
        return [call for call in self.get_calls if substring in call["url"]]


def make_config(**overrides):
    defaults = dict(
        api_key="KEY",
        secret_key="SECRET",
        trading_base_url="https://paper-api.alpaca.markets",
        data_base_url="https://data.alpaca.markets",
        ntfy_server="https://ntfy.test",
        ntfy_topic="test-topic",
        ntfy_token="tok_123",
        ntfy_timeout=7,
        use_repo_analyzer=False,
        stocks_to_trade=["AAPL", "MSFT", "NVDA"],
    )
    defaults.update(overrides)
    return bot.BotConfig(**defaults)


def make_bars(closes, start_vol=1_000_000):
    return [
        {"t": f"2026-01-{i + 1:02d}T00:00:00Z", "o": c * 0.99, "h": c * 1.01,
         "l": c * 0.98, "c": c, "v": start_vol + i * 1000}
        for i, c in enumerate(closes)
    ]


def full_cycle_routes(recorder_state=None):
    """Standard happy-path Alpaca routes for run_cycle tests."""
    state = recorder_state if recorder_state is not None else {}
    state.setdefault("order_posts", 0)

    def order_post(url, json_body, data, headers):
        state["order_posts"] += 1
        return FakeResponse(200, {"id": f"order-{state['order_posts']}", "status": "accepted"})

    get_routes = {
        "/v2/clock": FakeResponse(200, {"is_open": True}),
        "/v2/account": FakeResponse(200, {"equity": "100000", "buying_power": "100000", "cash": "100000"}),
        "/v2/positions": FakeResponse(200, []),
        "/v2/orders": FakeResponse(200, []),
        "/stocks/SPY/bars": FakeResponse(200, {"bars": {"SPY": make_bars([100, 101, 102, 103, 105])}}),
    }
    post_routes = {
        "/v2/orders": order_post,
        "https://ntfy.test": FakeResponse(200, {"id": "msg"}),
    }
    return get_routes, post_routes, state


def patch_requests(recorder):
    return mock.patch.multiple("automated_trading_bot.requests", get=recorder.get, post=recorder.post)


# ===========================================================================
# Configuration
# ===========================================================================

class TestBotConfig(unittest.TestCase):
    def test_from_env_reads_overrides_and_defaults(self):
        env = {
            "ALPACA_API_KEY": "ak",
            "ALPACA_SECRET_KEY": "sk",
            "STOCKS_TO_TRADE": "aapl, tsla;nvda",
            "BOT_DRY_RUN": "true",
            "MAX_STOCKS": "5",
            "STOP_LOSS_PERCENT": "7.5",
            "NTFY_TOPIC": "custom-topic",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = bot.BotConfig.from_env()
        self.assertEqual(config.api_key, "ak")
        self.assertEqual(config.stocks_to_trade, ["AAPL", "TSLA", "NVDA"])
        self.assertTrue(config.dry_run)
        self.assertFalse(config.force_run)
        self.assertEqual(config.max_stocks, 5)
        self.assertEqual(config.stop_loss_percent, 7.5)
        self.assertEqual(config.ntfy_topic, "custom-topic")
        self.assertEqual(config.ntfy_server, bot.DEFAULT_NTFY_SERVER)
        self.assertEqual(config.data_base_url, "https://data.alpaca.markets")
        self.assertEqual(config.trading_base_url, "https://paper-api.alpaca.markets")


# ===========================================================================
# Alpaca client — hosts, auth headers, payload schemas
# ===========================================================================

class TestAlpacaClient(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.client = bot.AlpacaClient(self.config)

    def test_trading_and_data_hosts_are_separate_and_authenticated(self):
        recorder = RequestRecorder(
            get_routes={
                "/v2/account": FakeResponse(200, {"equity": "1"}),
                "/v2/clock": FakeResponse(200, {"is_open": True}),
                "/quotes/latest": FakeResponse(200, {"quote": {"ap": 1, "bp": 1}}),
                "/bars": FakeResponse(200, {"bars": {"AAPL": []}}),
            }
        )
        with patch_requests(recorder):
            self.client.get_account()
            self.client.get_clock()
            self.client.get_latest_quote("AAPL")
            self.client.get_bars("AAPL")

        account_url = recorder.gets_to("/v2/account")[0]["url"]
        clock_url = recorder.gets_to("/v2/clock")[0]["url"]
        quote_url = recorder.gets_to("/quotes/latest")[0]["url"]
        bars_url = recorder.gets_to("/bars")[0]["url"]

        self.assertTrue(account_url.startswith("https://paper-api.alpaca.markets/v2/"))
        self.assertTrue(clock_url.startswith("https://paper-api.alpaca.markets/v2/"))
        # The regression this fixes: market data MUST NOT go to paper-api (404).
        self.assertTrue(quote_url.startswith("https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest"))
        self.assertTrue(bars_url.startswith("https://data.alpaca.markets/v2/stocks/AAPL/bars"))
        for call in recorder.get_calls:
            self.assertEqual(call["headers"]["APCA-API-KEY-ID"], "KEY")
            self.assertEqual(call["headers"]["APCA-API-SECRET-KEY"], "SECRET")
            self.assertIsNotNone(call["timeout"])
        self.assertEqual(recorder.gets_to("/bars")[0]["params"]["timeframe"], "1Day")

    def test_latest_quote_prefers_ask_then_bid_then_last_close(self):
        recorder = RequestRecorder(
            get_routes={"/quotes/latest": FakeResponse(200, {"quote": {"ap": 101.5, "bp": 101.2}})}
        )
        with patch_requests(recorder):
            self.assertEqual(bot.ResearchAgent(self.client, self.config).latest_price("AAPL"), 101.5)

        recorder = RequestRecorder(
            get_routes={"/quotes/latest": FakeResponse(200, {"quote": {"ap": 0, "bp": 99.25}})}
        )
        with patch_requests(recorder):
            self.assertEqual(bot.ResearchAgent(self.client, self.config).latest_price("AAPL"), 99.25)

        recorder = RequestRecorder(
            get_routes={
                "/quotes/latest": FakeResponse(404, None),
                "/bars": FakeResponse(200, {"bars": {"AAPL": make_bars([98.75])}}),
            }
        )
        with patch_requests(recorder):
            self.assertEqual(bot.ResearchAgent(self.client, self.config).latest_price("AAPL"), 98.75)

    def test_bars_parsing_handles_nested_symbol_payload_and_bad_shapes(self):
        recorder = RequestRecorder(
            get_routes={"/bars": FakeResponse(200, {"bars": {"AAPL": [{"c": 1}, {"c": 2}]}, "symbol": "AAPL"})}
        )
        with patch_requests(recorder):
            self.assertEqual(len(self.client.get_bars("AAPL")), 2)

        recorder = RequestRecorder(get_routes={"/bars": FakeResponse(200, {"bars": [{"c": 1}]})})
        with patch_requests(recorder):
            self.assertEqual(len(self.client.get_bars("AAPL")), 1)  # defensive flat-list support

        recorder = RequestRecorder(get_routes={"/bars": FakeResponse(500, None)})
        with patch_requests(recorder):
            self.assertEqual(self.client.get_bars("AAPL"), [])

    def test_network_errors_never_raise(self):
        recorder = RequestRecorder()
        recorder.get = mock.Mock(side_effect=__import__("requests").exceptions.ConnectionError("boom"))
        with mock.patch.multiple("automated_trading_bot.requests", get=recorder.get):
            self.assertIsNone(self.client.get_account())
            self.assertEqual(self.client.get_positions(), [])
            self.assertIsNone(self.client.get_clock())
            self.assertEqual(self.client.get_bars("AAPL"), [])


# ===========================================================================
# Market agent — clock + regime
# ===========================================================================

class TestMarketAgent(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.client = bot.AlpacaClient(self.config)
        self.agent = bot.MarketAgent(self.client)

    def test_clock_prefers_alpaca_api(self):
        recorder = RequestRecorder(get_routes={"/v2/clock": FakeResponse(200, {"is_open": False})})
        with patch_requests(recorder):
            status = self.agent.clock_status()
        self.assertFalse(status["is_open"])
        self.assertEqual(status["source"], "alpaca-clock")

    def test_clock_falls_back_to_et_hours_when_api_unavailable(self):
        recorder = RequestRecorder(get_routes={"/v2/clock": FakeResponse(500, None)})
        saturday = datetime(2026, 9, 5, 12, 0)   # Saturday
        wednesday = datetime(2026, 9, 2, 10, 0)  # Wednesday 10:00 ET
        with patch_requests(recorder), mock.patch.object(bot, "_et_now", return_value=saturday):
            self.assertFalse(self.agent.clock_status()["is_open"])
        with patch_requests(recorder), mock.patch.object(bot, "_et_now", return_value=wednesday):
            status = self.agent.clock_status()
        self.assertTrue(status["is_open"])
        self.assertEqual(status["source"], "et-hours-fallback")

    def test_regime_signal_scoring_buckets(self):
        self.assertEqual(self.agent.score_regime(3.5), 85)
        self.assertEqual(self.agent.score_regime(1.5), 70)
        self.assertEqual(self.agent.score_regime(0.2), 50)
        self.assertEqual(self.agent.score_regime(-2.0), 35)
        self.assertEqual(self.agent.score_regime(-4.0), 15)

    def test_regime_signal_parses_data_api_payload(self):
        recorder = RequestRecorder(
            get_routes={"/stocks/SPY/bars": FakeResponse(200, {"bars": {"SPY": make_bars([100, 104.5])}})}
        )
        with patch_requests(recorder):
            regime = self.agent.regime_signal()
        self.assertEqual(regime["score"], 85)
        self.assertEqual(regime["label"], "BULLISH")
        self.assertAlmostEqual(regime["change_percent"], 4.5)

        recorder = RequestRecorder(get_routes={"/stocks/SPY/bars": FakeResponse(404, None)})
        with patch_requests(recorder):
            regime = self.agent.regime_signal()
        self.assertEqual(regime["score"], 50)  # neutral default on data failure
        self.assertIn("note", regime)


# ===========================================================================
# Research agent — repo analyzer path + built-in fallback
# ===========================================================================

class TestResearchAgent(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.client = bot.AlpacaClient(self.config)
        self.agent = bot.ResearchAgent(self.client, self.config)

    def test_builtin_scorer_uptrend_beats_downtrend(self):
        up = make_bars([100 + i * 0.4 for i in range(120)])
        down = make_bars([160 - i * 0.4 for i in range(120)])
        up_score = self.agent._score_builtin("AAA", up)
        down_score = self.agent._score_builtin("BBB", down)
        self.assertGreater(up_score["score"], down_score["score"])
        self.assertTrue(0 <= up_score["score"] <= 100)
        self.assertEqual(up_score["source"], "builtin-technical")
        self.assertGreaterEqual(len(up_score["reasons"]), 2)

    def test_builtin_scorer_insufficient_history_is_neutral(self):
        result = self.agent._score_builtin("CCC", make_bars([100, 101, 102]))
        self.assertEqual(result["score"], 50)
        self.assertEqual(result["signal"], "HOLD")
        self.assertIn("insufficient bar history", result["reasons"])

    def test_repo_analyzer_path_used_when_importable(self):
        captured = {}

        def fake_analyze(df, code):
            captured["df"] = df
            captured["code"] = code
            return SimpleNamespace(
                signal_score=77,
                buy_signal=SimpleNamespace(name="BUY"),
                signal_reasons=["MA bullish alignment", "RSI healthy"],
                risk_factors=["extended bias"],
            )

        bars = make_bars([100 + i * 0.3 for i in range(80)])
        # Inject the fake analyzer directly (bypasses the lazy loader sentinel).
        self.agent._repo_analyzer = fake_analyze
        scored = self.agent._score_with_repo_analyzer("AAPL", bars)

        self.assertIsNotNone(scored)
        self.assertEqual(scored["source"], "repo-analyzer")
        self.assertEqual(scored["score"], 77)
        self.assertEqual(scored["signal"], "BUY")
        self.assertEqual(captured["code"], "AAPL")
        self.assertIn("date", captured["df"].columns)
        self.assertEqual(len(captured["df"]), len(bars))

    def test_research_symbol_falls_back_when_repo_analyzer_missing(self):
        recorder = RequestRecorder(
            get_routes={
                "/quotes/latest": FakeResponse(200, {"quote": {"ap": 150.0, "bp": 149.9}}),
                "/bars": FakeResponse(200, {"bars": {"AAPL": make_bars([100 + i * 0.4 for i in range(120)])}}),
            }
        )
        with patch_requests(recorder), mock.patch.object(bot, "_load_repo_analyzer", return_value=None):
            agent = bot.ResearchAgent(self.client, make_config(use_repo_analyzer=True))
            result = agent.research_symbol("AAPL")
        self.assertEqual(result["source"], "builtin-technical")
        self.assertEqual(result["price"], 150.0)
        self.assertTrue(0 <= result["score"] <= 100)

    @unittest.skipUnless(
        os.environ.get("RUN_REPO_ANALYZER_INTEGRATION", "1") == "1", "set RUN_REPO_ANALYZER_INTEGRATION=0 to skip"
    )
    def test_real_repo_analyzer_integration_when_dependencies_present(self):
        """End-to-end through the fork's own src.stock_analyzer engine if importable."""
        try:
            analyze_stock = bot._load_repo_analyzer()
        except Exception:
            analyze_stock = None
        if analyze_stock is None:
            self.skipTest("src.stock_analyzer dependencies unavailable in this environment")
        bars = make_bars([100 * (1.004 ** i) for i in range(120)])
        recorder = RequestRecorder(
            get_routes={
                "/quotes/latest": FakeResponse(200, {"quote": {"ap": 161.0, "bp": 160.9}}),
                "/bars": FakeResponse(200, {"bars": {"AAPL": bars}}),
            }
        )
        with patch_requests(recorder):
            agent = bot.ResearchAgent(self.client, make_config(use_repo_analyzer=True))
            result = agent.research_symbol("AAPL")
        self.assertEqual(result["source"], "repo-analyzer")
        self.assertTrue(0 <= result["score"] <= 100)
        self.assertIn(result["signal"], {"STRONG_BUY", "BUY", "HOLD", "WAIT", "SELL", "STRONG_SELL"})
        self.assertEqual(result["price"], 161.0)


# ===========================================================================
# Risk agent — exits, double-sell guard, sizing
# ===========================================================================

class TestRiskAgent(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.risk = bot.RiskAgent(self.config)

    @staticmethod
    def position(symbol, qty, entry, current):
        return {
            "symbol": symbol,
            "qty": str(qty),
            "avg_entry_price": str(entry),
            "current_price": str(current),
            "market_value": str(qty * current),
            "unrealized_pl": str((current - entry) * qty),
            "unrealized_plpc": str((current - entry) / entry),
        }

    def test_take_profit_stop_loss_and_regime_exits(self):
        positions = [
            self.position("AAA", 10, 100, 112),   # +12% → take profit
            self.position("BBB", 5, 100, 94),     # -6%  → stop loss
            self.position("CCC", 7, 100, 100),    # flat → only regime exit
        ]
        prices = {"AAA": 112.0, "BBB": 94.0, "CCC": 100.0}

        exits = self.risk.plan_exits(positions, prices, [], regime_score=50)
        by_symbol = {exit_.symbol: exit_ for exit_ in exits}
        self.assertEqual(set(by_symbol), {"AAA", "BBB"})
        self.assertIn("take-profit", by_symbol["AAA"].reason)
        self.assertEqual(by_symbol["AAA"].qty, 10)
        self.assertIn("stop-loss", by_symbol["BBB"].reason)

        exits = self.risk.plan_exits(positions, prices, [], regime_score=20)
        by_symbol = {exit_.symbol: exit_ for exit_ in exits}
        self.assertEqual(set(by_symbol), {"AAA", "BBB", "CCC"})
        self.assertIn("regime exit", by_symbol["CCC"].reason)

    def test_no_double_sell_when_exit_order_already_pending(self):
        positions = [self.position("AAA", 10, 100, 112)]
        prices = {"AAA": 112.0}
        open_orders = [{"symbol": "AAA", "side": "sell", "qty": "10", "status": "new"}]

        exits = self.risk.plan_exits(positions, prices, open_orders, regime_score=50)
        self.assertEqual(exits, [])  # fully in flight → never sell twice

        open_orders_partial = [{"symbol": "AAA", "side": "sell", "qty": "4", "status": "partially_filled"}]
        exits = self.risk.plan_exits(positions, prices, open_orders_partial, regime_score=50)
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].qty, 6)  # only the remainder

        # A pending BUY must not suppress a sell.
        open_orders_buy = [{"symbol": "AAA", "side": "buy", "qty": "10"}]
        exits = self.risk.plan_exits(positions, prices, open_orders_buy, regime_score=50)
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].qty, 10)

    def test_position_sizing_uses_equity_reserve_and_per_position_cap(self):
        account = {"equity": "100000", "buying_power": "100000"}
        candidates = [
            {"symbol": "AAA", "price": 200.0, "score": 90},
            {"symbol": "BBB", "price": 100.0, "score": 80},
            {"symbol": "CCC", "price": 300.0, "score": 70},
        ]
        entries = self.risk.plan_entries(candidates, account, positions=[], open_orders=[])
        by_symbol = {entry.symbol: entry for entry in entries}

        # investable = 100000 - 20% reserve = 80000; per-position cap = 40% equity = 40000
        self.assertEqual(len(entries), 2)  # max_buys_per_cycle
        self.assertEqual(by_symbol["AAA"].qty, 200)   # 40000 / 200
        self.assertAlmostEqual(by_symbol["AAA"].budget, 40000.0)
        self.assertEqual(by_symbol["BBB"].qty, 400)   # 40000 / 100
        self.assertNotIn("CCC", by_symbol)
        total = sum(entry.budget for entry in entries)
        self.assertLessEqual(total, 80000.0 + 1e-9)

    def test_sizing_never_exceeds_remaining_cash_across_buys(self):
        account = {"equity": "10000", "buying_power": "10000"}
        # cap = 4000, investable = 8000; 3 candidates but only 2 buys/cycle
        candidates = [
            {"symbol": "AAA", "price": 10.0, "score": 95},
            {"symbol": "BBB", "price": 10.0, "score": 90},
            {"symbol": "CCC", "price": 10.0, "score": 85},
        ]
        entries = self.risk.plan_entries(candidates, account, positions=[], open_orders=[])
        self.assertEqual(len(entries), 2)
        for entry in entries:
            self.assertEqual(entry.qty, 400)  # min(4000 cap, remaining) / 10
        self.assertLessEqual(sum(e.budget for e in entries), 8000.0)

    def test_entry_filters_owned_pending_low_score_dust_and_max_stocks(self):
        account = {"equity": "100000", "buying_power": "100000"}
        candidates = [
            {"symbol": "OWN", "price": 100.0, "score": 95},   # already held
            {"symbol": "PEND", "price": 100.0, "score": 95},  # buy order pending
            {"symbol": "LOW", "price": 100.0, "score": 55},   # below threshold 60
            {"symbol": "DUST", "price": 100000.0, "score": 99},  # qty would be 0
            {"symbol": "FREE", "price": 0.0, "score": 99},    # bad price
            {"symbol": "OK", "price": 100.0, "score": 88},    # only viable one
        ]
        positions = [self.position("OWN", 5, 100, 100)]
        open_orders = [{"symbol": "PEND", "side": "buy", "qty": "10"}]
        entries = self.risk.plan_entries(candidates, account, positions, open_orders)
        self.assertEqual([entry.symbol for entry in entries], ["OK"])

        # MAX_STOCKS respected: already holding 3 → no new entries
        full_positions = [self.position(s, 1, 100, 100) for s in ("P1", "P2", "P3")]
        entries = self.risk.plan_entries(candidates, account, full_positions, [])
        self.assertEqual(entries, [])

    def test_entries_ranked_by_score(self):
        account = {"equity": "100000", "buying_power": "100000"}
        candidates = [
            {"symbol": "WEAK", "price": 100.0, "score": 65},
            {"symbol": "STRONG", "price": 100.0, "score": 92},
        ]
        entries = self.risk.plan_entries(candidates, account, [], [])
        self.assertEqual([entry.symbol for entry in entries], ["STRONG", "WEAK"])


# ===========================================================================
# ntfy notifier — JSON publish API, auth, timeouts, 413 attachment fallback
# ===========================================================================

class TestNtfyNotifier(unittest.TestCase):
    def test_publish_uses_json_api_with_bearer_token_and_timeout(self):
        config = make_config()
        notifier = bot.NtfyNotifier(config)
        recorder = RequestRecorder(post_routes={"https://ntfy.test": FakeResponse(200, {"id": "m"})})
        with patch_requests(recorder):
            ok = notifier.send("Title 🤖", "line1\nline2 — ünïcödé ✅", priority=4, tags=["robot_face"])
        self.assertTrue(ok)
        call = recorder.post_calls[0]
        self.assertEqual(call["url"], "https://ntfy.test")  # JSON publish → server root
        self.assertEqual(call["json"]["topic"], "test-topic")
        self.assertEqual(call["json"]["title"], "Title 🤖")
        self.assertIn("ünïcödé ✅", call["json"]["message"])  # no lossy ASCII stripping
        self.assertEqual(call["json"]["priority"], 4)
        self.assertEqual(call["json"]["tags"], ["robot_face"])
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok_123")
        self.assertEqual(call["timeout"], 7)

    def test_no_auth_header_without_token(self):
        notifier = bot.NtfyNotifier(make_config(ntfy_token=None))
        recorder = RequestRecorder(post_routes={"https://ntfy.test": FakeResponse(200, {})})
        with patch_requests(recorder):
            self.assertTrue(notifier.send("t", "m"))
        self.assertNotIn("Authorization", recorder.post_calls[0]["headers"])

    def test_publish_failure_and_network_error_return_false(self):
        notifier = bot.NtfyNotifier(make_config())
        recorder = RequestRecorder(post_routes={"https://ntfy.test": FakeResponse(500, None)})
        with patch_requests(recorder):
            self.assertFalse(notifier.send("t", "m"))

        recorder = RequestRecorder()
        recorder.post = mock.Mock(side_effect=__import__("requests").exceptions.Timeout("slow"))
        with mock.patch.multiple("automated_trading_bot.requests", post=recorder.post):
            self.assertFalse(notifier.send("t", "m"))

    def test_long_report_uses_summary_plus_attachment(self):
        config = make_config(ntfy_message_byte_limit=200)
        notifier = bot.NtfyNotifier(config)
        long_message = "R" * 50 + "\n" + ("📈 report line with unicode ✅\n" * 40)
        recorder = RequestRecorder(post_routes={"https://ntfy.test": FakeResponse(200, {})})
        with patch_requests(recorder):
            ok = notifier.send("🤖 Long report 报告", long_message)
        self.assertTrue(ok)
        self.assertEqual(len(recorder.post_calls), 2)

        summary_call, attach_call = recorder.post_calls
        self.assertIsNotNone(summary_call["json"])  # first: JSON summary
        self.assertLessEqual(len(summary_call["json"]["message"].encode("utf-8")), 200 + 100)
        self.assertIn("attached", summary_call["json"]["message"])
        # Title with emoji/CJK travels safely inside the JSON body:
        self.assertEqual(summary_call["json"]["title"], "🤖 Long report 报告")
        self.assertIsNone(attach_call["json"])      # second: raw attachment body
        self.assertEqual(attach_call["url"], "https://ntfy.test/test-topic")
        self.assertEqual(attach_call["data"], long_message.encode("utf-8"))
        self.assertIn("Filename", attach_call["headers"])
        self.assertTrue(attach_call["headers"]["Filename"].startswith("trading-report-"))
        self.assertEqual(attach_call["headers"]["Authorization"], "Bearer tok_123")
        # Regression: header values MUST be latin-1 encodable (emoji title used
        # to crash the attachment request with UnicodeEncodeError).
        for name, value in attach_call["headers"].items():
            try:
                value.encode("latin-1")
            except UnicodeEncodeError:
                self.fail(f"attachment header {name!r} is not latin-1 safe: {value!r}")

    def test_http_413_triggers_attachment_retry(self):
        config = make_config(ntfy_message_byte_limit=100_000)  # pre-check off; server still says 413
        notifier = bot.NtfyNotifier(config)
        responses = iter([FakeResponse(413, None), FakeResponse(200, {}), FakeResponse(200, {})])
        recorder = RequestRecorder(post_routes={"https://ntfy.test": lambda *args: next(responses)})
        with patch_requests(recorder):
            ok = notifier.send("Big", "x" * 5000)
        self.assertTrue(ok)
        self.assertEqual(len(recorder.post_calls), 3)  # normal → 413 → summary + attachment

    def test_attachment_failure_returns_false(self):
        config = make_config(ntfy_message_byte_limit=100)
        notifier = bot.NtfyNotifier(config)
        responses = iter([FakeResponse(200, {}), FakeResponse(500, None)])  # summary ok, attach fails
        recorder = RequestRecorder(post_routes={"https://ntfy.test": lambda *args: next(responses)})
        with patch_requests(recorder):
            self.assertFalse(notifier.send("Big", "y" * 500))


# ===========================================================================
# Full cycle orchestration (end-to-end with mocked HTTP)
# ===========================================================================

class TestRunCycle(unittest.TestCase):
    RESEARCH_STUB = [
        {"symbol": "AAPL", "price": 150.0, "score": 90, "signal": "BUY", "source": "test",
         "reasons": ["strong trend"], "risks": [], "summary": [], "bars": 120},
        {"symbol": "MSFT", "price": 400.0, "score": 45, "signal": "HOLD", "source": "test",
         "reasons": [], "risks": [], "summary": [], "bars": 120},
    ]

    def test_full_cycle_trades_and_sends_structured_report(self):
        get_routes, post_routes, state = full_cycle_routes()
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        config = make_config()
        with patch_requests(recorder), \
                mock.patch.object(bot.ResearchAgent, "research", return_value=self.RESEARCH_STUB):
            code = bot.run_cycle(config=config)
        self.assertEqual(code, 0)

        # One buy order submitted for AAPL only (MSFT score 45 < 60):
        # cap = 40% equity = 40000 → qty = 40000 // 150 = 266
        order_posts = recorder.posts_to("/v2/orders")
        self.assertEqual(len(order_posts), 1)
        self.assertEqual(order_posts[0]["json"]["symbol"], "AAPL")
        self.assertEqual(order_posts[0]["json"]["side"], "buy")
        self.assertEqual(order_posts[0]["json"]["qty"], "266")
        self.assertEqual(order_posts[0]["json"]["type"], "market")
        self.assertEqual(order_posts[0]["json"]["time_in_force"], "day")

        # Structured ntfy report delivered via JSON publish API
        ntfy_calls = recorder.posts_to("ntfy.test")
        self.assertEqual(len(ntfy_calls), 1)
        report = ntfy_calls[0]["json"]["message"]
        title = ntfy_calls[0]["json"]["title"]
        for fragment in ("TRADING CYCLE REPORT", "Market: OPEN", "── ACCOUNT ──", "Equity: $100,000.00",
                         "── MARKET REGIME (SPY) ──", "Signal: 85/100", "── RESEARCH ──", "AAPL",
                         "── ACTIONS ──", "BOUGHT 266 AAPL", "── PORTFOLIO ──", "Flat"):
            self.assertIn(fragment, report)
        self.assertIn("BUY", title)
        self.assertEqual(ntfy_calls[0]["headers"]["Authorization"], "Bearer tok_123")
        self.assertEqual(state["order_posts"], 1)

    def test_market_closed_skips_trading_but_notifies(self):
        get_routes, post_routes, state = full_cycle_routes()
        get_routes["/v2/clock"] = FakeResponse(200, {"is_open": False})
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        with patch_requests(recorder):
            code = bot.run_cycle(config=make_config())
        self.assertEqual(code, 0)
        self.assertEqual(state["order_posts"], 0)
        self.assertEqual(recorder.gets_to("/stocks/SPY/bars"), [])  # no research when closed
        ntfy_calls = recorder.posts_to("ntfy.test")
        self.assertEqual(len(ntfy_calls), 1)
        self.assertIn("market closed", ntfy_calls[0]["json"]["title"].lower())
        self.assertEqual(ntfy_calls[0]["json"]["priority"], 2)

    def test_market_closed_silent_when_notifications_disabled(self):
        get_routes, post_routes, _ = full_cycle_routes()
        get_routes["/v2/clock"] = FakeResponse(200, {"is_open": False})
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        with patch_requests(recorder):
            code = bot.run_cycle(config=make_config(notify_when_closed=False))
        self.assertEqual(code, 0)
        self.assertEqual(recorder.post_calls, [])

    def test_force_run_trades_on_closed_market(self):
        get_routes, post_routes, state = full_cycle_routes()
        get_routes["/v2/clock"] = FakeResponse(200, {"is_open": False})
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        with patch_requests(recorder), \
                mock.patch.object(bot.ResearchAgent, "research", return_value=self.RESEARCH_STUB):
            code = bot.run_cycle(config=make_config(force_run=True))
        self.assertEqual(code, 0)
        self.assertEqual(state["order_posts"], 1)  # forced → order still placed
        report = recorder.posts_to("ntfy.test")[0]["json"]["message"]
        self.assertIn("FORCED", report)

    def test_dry_run_plans_and_reports_without_submitting_orders(self):
        get_routes, post_routes, state = full_cycle_routes()
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        with patch_requests(recorder), \
                mock.patch.object(bot.ResearchAgent, "research", return_value=self.RESEARCH_STUB):
            code = bot.run_cycle(config=make_config(dry_run=True))
        self.assertEqual(code, 0)
        self.assertEqual(state["order_posts"], 0)          # never touches /v2/orders
        self.assertEqual(recorder.posts_to("/v2/orders"), [])
        ntfy_calls = recorder.posts_to("ntfy.test")
        self.assertEqual(len(ntfy_calls), 1)
        report = ntfy_calls[0]["json"]["message"]
        self.assertIn("DRY-RUN", report)
        self.assertIn("BOUGHT 266 AAPL", report)           # plan still reported
        self.assertIn("dry-run", report)

    def test_missing_credentials_alerts_with_priority_5(self):
        recorder = RequestRecorder(post_routes={"https://ntfy.test": FakeResponse(200, {})})
        with patch_requests(recorder):
            code = bot.run_cycle(config=make_config(api_key=None, secret_key=None))
        self.assertEqual(code, 2)
        ntfy_calls = recorder.posts_to("ntfy.test")
        self.assertEqual(len(ntfy_calls), 1)
        self.assertEqual(ntfy_calls[0]["json"]["priority"], 5)
        self.assertIn("misconfigured", ntfy_calls[0]["json"]["title"].lower())
        self.assertEqual(recorder.get_calls, [])  # no Alpaca traffic at all

    def test_account_fetch_failure_notifies_and_returns_error(self):
        get_routes, post_routes, _ = full_cycle_routes()
        get_routes["/v2/account"] = FakeResponse(401, {"message": "unauthorized"})
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        with patch_requests(recorder):
            code = bot.run_cycle(config=make_config())
        self.assertEqual(code, 1)
        ntfy_calls = recorder.posts_to("ntfy.test")
        self.assertEqual(ntfy_calls[0]["json"]["priority"], 5)
        self.assertIn("error", ntfy_calls[0]["json"]["title"].lower())

    def test_stop_loss_cycle_escalates_priority_and_sells(self):
        positions = [{
            "symbol": "NVDA", "qty": "8", "avg_entry_price": "200", "current_price": "180",
            "market_value": "1440", "unrealized_pl": "-160", "unrealized_plpc": "-0.10",
        }]
        get_routes, post_routes, state = full_cycle_routes()
        get_routes["/v2/positions"] = FakeResponse(200, positions)
        recorder = RequestRecorder(get_routes=get_routes, post_routes=post_routes)
        research = [{"symbol": "NVDA", "price": 180.0, "score": 35, "signal": "WAIT", "source": "test",
                     "reasons": [], "risks": [], "summary": [], "bars": 120}]
        with patch_requests(recorder), mock.patch.object(bot.ResearchAgent, "research", return_value=research):
            code = bot.run_cycle(config=make_config())
        self.assertEqual(code, 0)
        order_posts = recorder.posts_to("/v2/orders")
        self.assertEqual(len(order_posts), 1)
        self.assertEqual(order_posts[0]["json"]["side"], "sell")
        self.assertEqual(order_posts[0]["json"]["symbol"], "NVDA")
        ntfy_call = recorder.posts_to("ntfy.test")[0]
        self.assertEqual(ntfy_call["json"]["priority"], 4)  # stop-loss escalation
        self.assertIn("SOLD 8 NVDA", ntfy_call["json"]["message"])
        self.assertIn("stop-loss", ntfy_call["json"]["message"])
        self.assertIn("SELL", ntfy_call["json"]["title"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
