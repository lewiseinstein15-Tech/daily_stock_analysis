# -*- coding: utf-8 -*-
"""Jexi CLI — run the boss agent, a historical paper-sim, or the self-loop.

Usage examples (from repo root):

    .venv/bin/python scripts/jexi_cli.py --status
    .venv/bin/python scripts/jexi_cli.py --mode once --stocks 600519,hk00700,AAPL
    .venv/bin/python scripts/jexi_cli.py --mode sim --scenario bull --scenario-tickers "bull=SPY,QQQ"
    .venv/bin/python scripts/jexi_cli.py --mode loop --max-iterations 5
      --scenario-tickers "bull=SPY,QQQ;bear=SPY,TSLA;sideways=SPY;volatile=SPY"

All trading analysis is paper/research only.  Run ``--mode loop`` only after
the offline unit tests (``pytest -m "not network"``) pass.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.config import get_config  # noqa: E402

DEFAULT_SCENARIO_TICKERS = {
    "bull": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
    "bear": ["SPY", "TSLA", "AMZN", "AAPL", "META"],
    "sideways": ["SPY", "KO", "PEP", "JNJ", "PG"],
    "volatile": ["SPY", "TSLA", "UBER", "DIS", "AAL"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jexi_cli",
        description="J.E.X.I. boss-agent CLI (paper/research only).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="Show personas + integrations")
    mode.add_argument("--mode", choices=["once", "sim", "loop", "backtest"], default="once")
    parser.add_argument("--stocks", default="", help="Comma-separated stock codes")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--specialists", default="", help="Comma-separated specialist ids (subset)")
    parser.add_argument("--research", default=None, choices=["auto", "opencode_cli", "litellm", "off"],
                        help="LLM research backend for specialists (default: off unless configured)")
    parser.add_argument("--scenario", default="", choices=list(DEFAULT_SCENARIO_TICKERS))
    parser.add_argument(
        "--scenarios",
        default="",
        help="Comma-separated scenario names for loop/backtest (default: all)",
    )
    parser.add_argument(
        "--scenario-tickers",
        default="",
        help='e.g. "bull=SPY,QQQ;volatile=SPY,TSLA" (semicolon-separated per scenario)',
    )
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--rebalance-days", type=int, default=20,
                        help="Rolling-backtest rebalance cadence (set for --mode loop rolling)",
    )
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--target-win-rate", type=float, default=None)
    parser.add_argument("--target-sharpe", type=float, default=None)
    parser.add_argument("--target-max-drawdown", type=float, default=None)
    parser.add_argument("--target-min-return", type=float, default=None)
    parser.add_argument("--ntfy-topic", default=None)
    parser.add_argument("--no-push", action="store_true", help="Never push to ntfy (STDOUT only)")
    parser.add_argument("--regime-gate", action="store_true",
                        help="Gate consensus trades on Prof Thorne's regime (bear->no fresh longs, etc)")
    parser.add_argument("--trend-gate", action="store_true",
                        help="Per-asset trend floor: only long above / short below its longer SMA")
    parser.add_argument("--test-push", action="store_true", help="Send a connectivity test to ntfy")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON result")
    return parser


def parse_scenario_tickers(raw: str) -> Dict[str, List[str]]:
    result = dict(DEFAULT_SCENARIO_TICKERS)
    if not raw:
        return result
    for group in raw.split(";"):
        if not group or "=" not in group:
            continue
        scenario, csv = group.split("=", 1)
        scenario = scenario.strip()
        tickers = [t.strip() for t in csv.split(",") if t.strip()]
        if scenario:
            result[scenario] = tickers
    return result


def run_status() -> int:
    from src.jexi import get_persona_registry
    from src.jexi.mcp_client import default_mcp_specs, is_mcp_enabled
    from src.jexi.notify import JexiNotifier

    config = get_config()
    registry = get_persona_registry()
    notifier = JexiNotifier(config)
    print(f"personas: leadership={len(registry.leadership.all)} specialists={len(registry.specialists())}")
    print(f"specialist ids: {', '.join(registry.specialist_ids)}")
    print(f"ntfy endpoint: {notifier.endpoint or '(not configured — STDOUT mode)'}")
    print(f"MCP enabled: {is_mcp_enabled(config)}")
    if is_mcp_enabled(config):
        print(f"default MCP specs: {json.dumps(default_mcp_specs())}")
    return 0


def run_once(args) -> int:
    from src.jexi import get_jexi
    from src.jexi.notify import JexiNotifier

    config = get_config()
    stocks = [s.strip() for s in args.stocks.split(",") if s.strip()]
    if not stocks:
        print("--stocks required for --mode once", file=sys.stderr)
        return 2

    jexi = get_jexi(config, research_backend=args.research)
    if args.ntfy_topic:
        jexi.notifier = JexiNotifier(config, topic=args.ntfy_topic)
    if args.no_push:
        jexi.notifier = JexiNotifier(None)

    specialist_ids = [s.strip() for s in args.specialists.split(",") if s.strip()] or None
    result = jexi.run(stocks, days=args.days, specialist_ids=specialist_ids)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["report_md"])
    return 0


def _resolve_targets(args, config) -> Dict[str, float]:
    return {
        "win_rate": args.target_win_rate if args.target_win_rate is not None else getattr(config, "jexi_target_win_rate", 0.55),
        "sharpe": args.target_sharpe if args.target_sharpe is not None else getattr(config, "jexi_target_sharpe", 1.2),
        "max_drawdown": args.target_max_drawdown if args.target_max_drawdown is not None else getattr(config, "jexi_target_max_drawdown", 0.15),
        "min_total_return": args.target_min_return if args.target_min_return is not None else getattr(config, "jexi_target_min_total_return", 0.05),
    }


def _make_jexi_and_loop(args, config):
    from src.jexi import get_jexi
    from src.jexi.loop import JexiLearningLoop
    from src.jexi.notify import JexiNotifier

    jexi = get_jexi(config, research_backend=args.research)
    if args.ntfy_topic:
        jexi.notifier = JexiNotifier(config, topic=args.ntfy_topic)
    if args.no_push:
        jexi.notifier = JexiNotifier(None)
    specialist_ids = [s.strip() for s in args.specialists.split(",") if s.strip()] or None
    loop = JexiLearningLoop(
        jexi,
        ticker_lists=parse_scenario_tickers(args.scenario_tickers),
        max_iterations=args.max_iterations or int(getattr(config, "jexi_max_iterations", 10)),
        targets=_resolve_targets(args, config),
        rebalance_days=args.rebalance_days,
        lookback_days=args.lookback_days,
        specialist_ids=specialist_ids,
        research_backend=jexi.research_backend,
        regime_gate=bool(args.regime_gate),
        trend_gate=bool(args.trend_gate),
    )
    return jexi, loop


def _select_scenarios(args, loop) -> List[str]:
    pool = parse_scenario_tickers(args.scenario_tickers)
    if args.scenario and args.scenario in pool:
        loop.ticker_lists = {args.scenario: pool[args.scenario]}
        return [args.scenario]
    requested = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    names = requested or list(loop.ticker_lists)
    loop.ticker_lists = {name: pool[name] for name in names if name in pool}
    return list(loop.ticker_lists)


def run_window(args) -> int:
    from src.config import get_config

    config = get_config()
    jexi, loop = _make_jexi_and_loop(args, config)
    scenarios = _select_scenarios(args, loop)
    if not scenarios:
        print("no scenario ticker lists configured", file=sys.stderr)
        return 2
    result = loop.run(scenarios=scenarios, stop_on_first_pass=(args.mode == "sim"))
    print(result.summary())
    return 0 if result.converged else 1


def run_backtest(args) -> int:
    """Single rolling backtest pass over the 5-year scenario windows + full 2020-2025."""
    from src.config import get_config
    from src.jexi.loop import FIVE_YEAR_WINDOW, JexiLearningLoop, SCENARIOS

    config = get_config()
    jexi, loop = _make_jexi_and_loop(args, config)
    scenarios = _select_scenarios(args, loop)
    if not scenarios:
        print("no scenario ticker lists configured", file=sys.stderr)
        return 2

    all_ok = True
    rows = []
    summary = {"scenarios": {}, "full_5y": {}}
    for scenario in scenarios:
        spec = SCENARIOS.get(scenario, {})
        outcome = loop.backtest_scenario(spec.get("start", ""), spec.get("end", ""), loop.ticker_lists[scenario])
        ok = bool(outcome["pass_scenario"])
        all_ok = all_ok and ok
        rows.append((scenario, outcome, ok))
        summary["scenarios"][scenario] = {
            "win_rate": outcome["win_rate"],
            "sharpe": outcome["sharpe"],
            "max_drawdown": outcome["max_drawdown"],
            "total_return": outcome["total_return"],
            "n_trades": outcome["n_trades"],
            "n_chunks": outcome["_n_chunks"],
            "pass": ok,
        }

    print(f"{'scenario':<10}{'win%':>7}{'sharpe':>8}{'maxdd%':>8}{'ret%':>8}{'trades':>7}{'chunks':>7}  verdict")
    for scenario, outcome, ok in rows:
        print(
            f"{scenario:<10}{outcome['win_rate']*100:>6.1f}%{outcome['sharpe']:>8.2f}"
            f"{outcome['max_drawdown']*100:>7.1f}%{outcome['total_return']*100:>7.1f}%"
            f"{outcome['n_trades']:>7}{outcome['_n_chunks']:>7}  {'PASS' if ok else 'FAIL'}"
        )

    universe = sorted({t for name in scenarios for t in loop.ticker_lists.get(name, [])})
    five_year = loop.backtest_scenario(FIVE_YEAR_WINDOW["start"], FIVE_YEAR_WINDOW["end"], universe)
    ok5 = bool(five_year["pass_scenario"])
    all_ok = all_ok and ok5
    print(
        f"{'5y(2020-25)':<10}{five_year['win_rate']*100:>6.1f}%{five_year['sharpe']:>8.2f}"
        f"{five_year['max_drawdown']*100:>7.1f}%{five_year['total_return']*100:>7.1f}%"
        f"{five_year['n_trades']:>7}{five_year['_n_chunks']:>7}  {'PASS' if ok5 else 'FAIL'}"
    )
    summary["full_5y"] = {
        "win_rate": five_year["win_rate"],
        "sharpe": five_year["sharpe"],
        "max_drawdown": five_year["max_drawdown"],
        "total_return": five_year["total_return"],
        "n_trades": five_year["n_trades"],
        "n_chunks": five_year["_n_chunks"],
        "pass": ok5,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


def run_test_push(args) -> int:
    from datetime import datetime

    from src.config import get_config
    from src.jexi.notify import JexiNotifier

    config = get_config()
    topic = args.ntfy_topic or getattr(config, "jexi_ntfy_topic", None) or "jexi_reports"
    notifier = JexiNotifier(config, topic=topic)
    ok = notifier.milestone(
        "JEXI 通知连通性测试",
        f"ntfy connectivity check from the Jexi pilot at {datetime.now().isoformat(timespec='seconds')}.",
        tags=["tada", "rocket"],
    )
    print(f"endpoint: {notifier.endpoint or '(STDOUT only — not configured)'}")
    print(f"sent: {ok}")
    return 0 if ok else 1


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.test_push:
        return run_test_push(args)
    if args.status:
        return run_status()
    if args.mode == "once":
        return run_once(args)
    if args.mode == "backtest":
        return run_backtest(args)
    return run_window(args)


if __name__ == "__main__":
    sys.exit(main())
