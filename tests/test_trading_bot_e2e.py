# -*- coding: utf-8 -*-
"""End-to-end tests: real HTTP, real pipeline, zero cloud credentials.

These spin up scripts/trading_bot_simulator.py (a local Alpaca + ntfy simulator)
and run automated_trading_bot.run_cycle() against it as a black box, asserting
on what the simulator actually received. Scenarios: bullish buy cycle,
stop-loss exit with the double-sell guard, bear-regime liquidation (with the
no-buy-back gate), closed market, forced run, dry run, the ntfy HTTP 413
attachment fallback against a simulator that enforces the size cap like
ntfy.sh, and the repo's real analysis engine driving a trade decision.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import automated_trading_bot as bot  # noqa: E402

_SIM_PATH = os.path.join(ROOT, "scripts", "trading_bot_simulator.py")
_spec = importlib.util.spec_from_file_location("trading_bot_simulator", _SIM_PATH)
_sim_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sim_module)
TradingBotSimulator = _sim_module.TradingBotSimulator

SIM: TradingBotSimulator = None  # type: ignore[assignment]


def setUpModule():
    global SIM
    SIM = TradingBotSimulator("bull")


def tearDownModule():
    if SIM is not None:
        SIM.shutdown()


def make_cfg(**overrides) -> bot.BotConfig:
    defaults = dict(
        api_key="sim",
        secret_key="sim",
        trading_base_url=SIM.base_url,
        data_base_url=SIM.base_url,
        ntfy_server=SIM.base_url,
        ntfy_topic="sim",
        ntfy_token=None,
        use_repo_analyzer=False,  # deterministic built-in scorer unless a test opts in
        stocks_to_trade=["AAPL", "MSFT", "NVDA"],
    )
    defaults.update(overrides)
    return bot.BotConfig(**defaults)


class TradingBotE2ETestCase(unittest.TestCase):
    def setUp(self):
        SIM.reset("bull")

    # -- scenario 1: bullish cycle buys with correct sizing and reports -------
    def test_e2e_bull_cycle_places_capped_buy_and_sends_structured_report(self):
        code = bot.run_cycle(config=make_cfg())
        self.assertEqual(code, 0)

        orders = SIM.captured_of("ORDER")
        self.assertEqual(len(orders), 1)
        order = orders[0]["order"]
        self.assertEqual(order["symbol"], "AAPL")       # only AAPL scores >= 60
        self.assertEqual(order["side"], "buy")
        # equity 100k → reserve 20% → investable 80k; per-position cap 40% = 40k
        # AAPL ask 150 → qty = 40000 // 150 = 266
        self.assertEqual(order["qty"], "266")
        self.assertEqual(order["type"], "market")
        self.assertEqual(order["time_in_force"], "day")

        pushes = SIM.captured_of("NTFY_JSON")
        self.assertEqual(len(pushes), 1)
        payload = pushes[0]["payload"]
        self.assertEqual(payload["topic"], "sim")
        self.assertIn("BUY", payload["title"])
        report = payload["message"]
        for fragment in ("TRADING CYCLE REPORT", "Market: OPEN", "── ACCOUNT ──",
                         "Equity: $100,000.00", "── MARKET REGIME (SPY) ──", "Signal: 85/100",
                         "── RESEARCH ──", "AAPL", "MSFT", "NVDA", "── ACTIONS ──",
                         "BOUGHT 266 AAPL", "── PORTFOLIO ──"):
            self.assertIn(fragment, report)

        # The simulated fill must have created the position.
        positions_after = [c for c in SIM.captured_of("GET") if c["path"] == "/v2/positions"]
        self.assertTrue(positions_after)

    # -- scenario 2: stop-loss exit + double-sell guard ------------------------
    def test_e2e_stoploss_exit_and_pending_sell_is_not_doubled(self):
        SIM.reset("stoploss")
        code = bot.run_cycle(config=make_cfg())
        self.assertEqual(code, 0)

        orders = SIM.captured_of("ORDER")
        self.assertEqual(len(orders), 1, "only NVDA should be sold; AAPL sell is already pending")
        order = orders[0]["order"]
        self.assertEqual(order["symbol"], "NVDA")
        self.assertEqual(order["side"], "sell")
        self.assertEqual(order["qty"], "8")

        pushes = SIM.captured_of("NTFY_JSON")
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]["payload"]["priority"], 4)  # stop-loss escalation
        report = pushes[0]["payload"]["message"]
        self.assertIn("SOLD 8 NVDA", report)
        self.assertIn("stop-loss", report)
        self.assertNotIn("SOLD 5 AAPL", report)  # never double-sold

    # -- scenario 3: bear regime liquidates and does NOT buy back --------------
    def test_e2e_crash_regime_liquidates_without_buying_back(self):
        SIM.reset("crash")
        code = bot.run_cycle(config=make_cfg())
        self.assertEqual(code, 0)

        orders = SIM.captured_of("ORDER")
        self.assertEqual(len(orders), 1, "regime exit sells AAPL and must not re-buy it")
        self.assertEqual(orders[0]["order"]["side"], "sell")
        self.assertEqual(orders[0]["order"]["symbol"], "AAPL")

        report = SIM.captured_of("NTFY_JSON")[0]["payload"]["message"]
        self.assertIn("regime exit", report)
        self.assertIn("Signal: 15/100", report)
        self.assertNotIn("BOUGHT", report)

    # -- scenario 4/5: closed market, and forced run overrides it ---------------
    def test_e2e_market_closed_only_notifies(self):
        SIM.reset("closed")
        code = bot.run_cycle(config=make_cfg())
        self.assertEqual(code, 0)
        self.assertEqual(SIM.captured_of("ORDER"), [])
        pushes = SIM.captured_of("NTFY_JSON")
        self.assertEqual(len(pushes), 1)
        self.assertIn("market closed", pushes[0]["payload"]["title"].lower())
        self.assertEqual(pushes[0]["payload"]["priority"], 2)

    def test_e2e_closed_market_silent_when_disabled(self):
        SIM.reset("closed")
        code = bot.run_cycle(config=make_cfg(notify_when_closed=False))
        self.assertEqual(code, 0)
        self.assertEqual(SIM.captured_of("NTFY_JSON"), [])
        self.assertEqual(SIM.captured_of("ORDER"), [])

    def test_e2e_force_run_trades_on_closed_market(self):
        SIM.reset("closed")
        code = bot.run_cycle(config=make_cfg(force_run=True))
        self.assertEqual(code, 0)
        orders = SIM.captured_of("ORDER")
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["order"]["side"], "buy")
        report = SIM.captured_of("NTFY_JSON")[0]["payload"]["message"]
        self.assertIn("FORCED", report)

    # -- scenario 6: dry run never submits orders -------------------------------
    def test_e2e_dry_run_plans_without_ordering(self):
        code = bot.run_cycle(config=make_cfg(dry_run=True))
        self.assertEqual(code, 0)
        self.assertEqual(SIM.captured_of("ORDER"), [])
        pushes = SIM.captured_of("NTFY_JSON")
        self.assertEqual(len(pushes), 1)
        report = pushes[0]["payload"]["message"]
        self.assertIn("DRY-RUN", report)
        self.assertIn("BOUGHT 266 AAPL", report)  # the PLAN is still reported

    # -- scenario 7: real ntfy-style 413 → summary + attachment -----------------
    def test_e2e_ntfy_413_falls_back_to_summary_plus_attachment(self):
        # Cap the simulated server BELOW the report size so the first publish
        # really gets rejected with HTTP 413 (as ntfy.sh does for >4096 bytes).
        SIM.update_state(ntfy_max_bytes=1000)
        code = bot.run_cycle(config=make_cfg(ntfy_message_byte_limit=100_000))
        self.assertEqual(code, 0)

        pushes = SIM.captured_of("NTFY_JSON")
        self.assertGreaterEqual(len(pushes), 2)
        # First attempt is oversized → simulator answered 413 → adaptive shrink succeeded
        self.assertGreater(len(pushes[0]["payload"]["message"].encode("utf-8")), 1000)
        accepted = pushes[-1]["payload"]
        self.assertLessEqual(len(accepted["message"].encode("utf-8")), 1000)
        self.assertIn("attached", accepted["message"])

        attachments = SIM.captured_of("NTFY_ATTACHMENT")
        self.assertEqual(len(attachments), 1)
        self.assertTrue(attachments[0]["filename"].startswith("trading-report-"))
        body = attachments[0]["body"]
        self.assertIn("TRADING CYCLE REPORT", body)      # FULL report arrived
        self.assertIn("BOUGHT 266 AAPL", body)
        self.assertGreater(len(body.encode("utf-8")), 1000)

    # -- scenario 8: the fork's real analysis engine drives the decision ---------
    def test_e2e_repo_analyzer_engine_drives_trade(self):
        if bot._load_repo_analyzer() is None:
            self.skipTest("src.stock_analyzer dependencies unavailable here")
        code = bot.run_cycle(config=make_cfg(use_repo_analyzer=True))
        self.assertEqual(code, 0)

        orders = SIM.captured_of("ORDER")
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["order"]["symbol"], "AAPL")
        self.assertEqual(orders[0]["order"]["side"], "buy")

        report = SIM.captured_of("NTFY_JSON")[0]["payload"]["message"]
        self.assertIn("[repo-analyzer]", report)  # scored by src.stock_analyzer, not the fallback
        self.assertIn("BOUGHT", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
