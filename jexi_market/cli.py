# -*- coding: utf-8 -*-
"""JEXI Market CLI.

Usage examples (from the repo root):

    python -m jexi_market.cli status
    python -m jexi_market.cli once --symbols AAPL,MSFT
    python -m jexi_market.cli scan
    python -m jexi_market.cli run --max-candidates 3
    python -m jexi_market.cli backtest --strategy trend_following --symbol AAPL
    python -m jexi_market.cli memory --stats
    python -m jexi_market.cli test-push

All trading analysis is paper/research only unless
``JEXI_LIVE_TRADING_ENABLED=1`` is set AND 30 paper-validation days
have been recorded.  See README for the full safety contract.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from jexi_market.config import MarketConfig, get_config
from jexi_market.contracts import SignalDirection


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_status(args: argparse.Namespace) -> int:
    from jexi_market.agents import list_agent_ids
    from jexi_market.strategies import list_strategies

    config = get_config()
    summary = config.summary()
    print("=== JEXI Market Status ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print()
    print(f"Agents ({len(list_agent_ids())}): {', '.join(list_agent_ids())}")
    print(f"Strategies ({len(list_strategies())}): {', '.join(list_strategies())}")
    return 0


def cmd_once(args: argparse.Namespace) -> int:
    from jexi_market.orchestrator import MarketBoss

    config = get_config()
    boss = MarketBoss(config)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or config.default_symbol_list
    if not symbols:
        print("no symbols provided", file=sys.stderr)
        return 2
    for symbol in symbols:
        result = boss.analyze_symbol(symbol, days=args.days)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, default=str))
        else:
            print(result.report_text or f"(no report for {symbol})")
            print()
            if result.error:
                print(f"ERROR: {result.error}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from jexi_market.scanner import MarketScanner

    config = get_config()
    scanner = MarketScanner()
    universe = [s.strip() for s in args.universe.split(",") if s.strip()] or config.scanner_symbols
    candidates = scanner.scan(universe, days=args.days)
    if args.json:
        print(json.dumps([c.to_dict() for c in candidates], indent=2, default=str))
    else:
        print(f"Scan: {len(candidates)} candidates from {len(universe)} symbols")
        for c in candidates:
            print(f"  {c.symbol:<8} score={c.score:.2f} triggers={','.join(c.triggered)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from jexi_market.pipeline import DecisionPipeline

    config = get_config()
    pipeline = DecisionPipeline(config)
    run = pipeline.run_full(max_candidates=args.max_candidates, days=args.days, execute_paper=args.execute)
    if args.json:
        print(json.dumps(run.to_dict(), indent=2, default=str))
    else:
        print(f"Pipeline run: {run.summary}")
        for r in run.symbol_results:
            dec = r.decision
            if dec:
                print(f"  {r.symbol:<8} {dec.direction.value.upper():<6} conf={dec.confidence.score:.0%} gate={'OK' if r.gate_approved else 'BLOCKED'}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from jexi_market.backtest import run_backtest
    from jexi_market.data import MarketDataClient
    from jexi_market.strategies import get_strategy, list_strategies

    config = get_config()
    strategy_name = args.strategy
    strategy = get_strategy(strategy_name)
    if not strategy:
        print(f"unknown strategy. available: {', '.join(list_strategies())}", file=sys.stderr)
        return 2
    client = MarketDataClient()
    snap = client.get_daily(args.symbol, days=args.days)
    if not snap.ok:
        print(f"data fetch failed: {snap.error}", file=sys.stderr)
        return 1
    result = run_backtest(snap.df, strategy, symbol=args.symbol)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"Backtest: {result.strategy_name} on {result.symbol}")
        print(f"  trades: {result.n_trades} (win rate {result.win_rate:.1%})")
        print(f"  total return: {result.total_return:.2%}")
        print(f"  sharpe: {result.sharpe:.2f}  sortino: {result.sortino:.2f}")
        print(f"  max drawdown: {result.max_drawdown:.2%}")
        print(f"  profit factor: {result.profit_factor:.2f}")
        print(f"  benchmark return: {result.benchmark_return:.2%} (alpha {result.alpha:+.2%})")
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    from jexi_market.memory import PerformanceMemory

    config = get_config()
    memory = PerformanceMemory(config.memory_db_path)
    if args.stats:
        print(json.dumps(memory.stats_summary(), indent=2))
    elif args.agents:
        print(json.dumps(memory.agent_stats(), indent=2))
    elif args.recent:
        print(json.dumps(memory.recent_trades(limit=args.recent), indent=2, default=str))
    else:
        print(f"paper_trading_days: {memory.paper_trading_days()}")
        print(f"stats: {memory.stats_summary()}")
    return 0


def cmd_test_push(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from jexi_market.notifications import NtfyReporter

    config = get_config()
    reporter = NtfyReporter(config)
    title = "JEXI Market — Connectivity Test"
    body = f"Connectivity check at {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z.\nIf you see this, ntfy is correctly configured."
    ok = reporter.publish(title, body, priority="default", tags=["tada", "rocket"])
    print(f"endpoint: {reporter.endpoint or '(offline — STDOUT)'}")
    print(f"sent: {ok}")
    return 0 if ok else 1


def cmd_alpaca(args: argparse.Namespace) -> int:
    from jexi_market.execution import AlpacaClient

    config = get_config()
    client = AlpacaClient(config)
    if not client.configured:
        print("Alpaca not configured (set ALPACA_API_KEY / ALPACA_API_SECRET)")
        return 1
    print(f"paper_trading: {client.paper_trading}")
    account = client.get_account()
    print(f"account: {account.to_dict()}")
    positions = client.get_positions()
    print(f"positions ({len(positions)}):")
    for p in positions:
        print(f"  {p.symbol:<6} qty={p.qty} side={p.side} mv=${p.market_value:.2f} pl=${p.unrealized_pl:.2f}")
    clock = client.get_clock()
    print(f"market: {'OPEN' if clock.is_open else 'CLOSED'} (next open: {clock.next_open})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jexi-market",
        description="JEXI Market — autonomous multi-agent market intelligence & paper-trading system",
    )
    parser.add_argument("--log-level", default=None, help="Override JEXI_LOG_LEVEL")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show config, agents, strategies")
    p_status.set_defaults(func=cmd_status)

    p_once = sub.add_parser("once", help="Run the full agent pipeline on one or more symbols")
    p_once.add_argument("--symbols", default="", help="Comma-separated symbols (default: from config)")
    p_once.add_argument("--days", type=int, default=120)
    p_once.add_argument("--json", action="store_true")
    p_once.set_defaults(func=cmd_once)

    p_scan = sub.add_parser("scan", help="Scan a universe for trade candidates")
    p_scan.add_argument("--universe", default="", help="Comma-separated symbols")
    p_scan.add_argument("--days", type=int, default=120)
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_run = sub.add_parser("run", help="Run the full pipeline: scan -> analyze -> paper-trade")
    p_run.add_argument("--max-candidates", type=int, default=5)
    p_run.add_argument("--days", type=int, default=120)
    p_run.add_argument("--execute", action="store_true", help="Submit real paper orders via Alpaca")
    p_run.add_argument("--json", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_bt = sub.add_parser("backtest", help="Backtest a single strategy on one symbol")
    p_bt.add_argument("--strategy", required=True)
    p_bt.add_argument("--symbol", required=True)
    p_bt.add_argument("--days", type=int, default=250)
    p_bt.add_argument("--json", action="store_true")
    p_bt.set_defaults(func=cmd_backtest)

    p_mem = sub.add_parser("memory", help="Inspect performance memory")
    p_mem.add_argument("--stats", action="store_true")
    p_mem.add_argument("--agents", action="store_true")
    p_mem.add_argument("--recent", type=int, default=0)
    p_mem.set_defaults(func=cmd_memory)

    p_push = sub.add_parser("test-push", help="Send a connectivity test to ntfy")
    p_push.set_defaults(func=cmd_test_push)

    p_alp = sub.add_parser("alpaca", help="Show Alpaca account / positions / market clock")
    p_alp.set_defaults(func=cmd_alpaca)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = get_config()
    _setup_logging(args.log_level or config.log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
