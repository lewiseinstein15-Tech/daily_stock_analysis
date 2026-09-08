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


def cmd_walk_forward(args: argparse.Namespace) -> int:
    from jexi_market.backtest import run_walk_forward
    from jexi_market.data import MarketDataClient
    from jexi_market.strategies import get_strategy, list_strategies

    config = get_config()
    strategy = get_strategy(args.strategy)
    if not strategy:
        print(f"unknown strategy. available: {', '.join(list_strategies())}", file=sys.stderr)
        return 2
    client = MarketDataClient()
    snap = client.get_daily(args.symbol, days=args.days)
    if not snap.ok:
        print(f"data fetch failed: {snap.error}", file=sys.stderr)
        return 1
    wf = run_walk_forward(snap.df, strategy, symbol=args.symbol, n_windows=args.windows)
    if args.json:
        print(json.dumps(wf.to_dict(), indent=2, default=str))
    else:
        print(f"Walk-forward: {wf.strategy_name} on {wf.symbol}")
        print(f"  windows: {wf.n_windows}")
        print(f"  total trades: {wf.total_trades}")
        print(f"  avg sharpe:     {wf.avg_sharpe:.2f}")
        print(f"  avg return:    {wf.avg_total_return:.2%}")
        print(f"  avg max DD:     {wf.avg_max_drawdown:.2%}")
        print(f"  avg win rate:  {wf.avg_win_rate:.1%}")
    return 0


def cmd_compare_strategies(args: argparse.Namespace) -> int:
    from jexi_market.backtest import compare_strategies
    from jexi_market.data import MarketDataClient

    config = get_config()
    client = MarketDataClient()
    snap = client.get_daily(args.symbol, days=args.days)
    if not snap.ok:
        print(f"data fetch failed: {snap.error}", file=sys.stderr)
        return 1
    rows = compare_strategies(snap.df, symbol=args.symbol)
    print(f"{'strategy':<22}{'trades':>7}{'win%':>7}{'return':>9}{'sharpe':>8}{'sortino':>9}{'maxDD':>8}{'alpha':>9}")
    for r in rows:
        print(
            f"{r['strategy']:<22}{r['n_trades']:>7}"
            f"{r['win_rate']*100:>6.1f}%"
            f"{r['total_return']*100:>8.1f}%"
            f"{r['sharpe']:>8.2f}"
            f"{r['sortino']:>9.2f}"
            f"{r['max_drawdown']*100:>7.1f}%"
            f"{r['alpha']*100:>8.1f}%"
        )
    return 0


def cmd_self_eval(args: argparse.Namespace) -> int:
    from jexi_market.self_eval import SelfEvaluationLoop

    config = get_config()
    loop = SelfEvaluationLoop(config)
    if args.leaderboard:
        board = loop.agent_leaderboard()
        if not board:
            print("no agent history yet (need closed trades)")
            return 0
        print(f"{'agent':<22}{'accuracy':>10}{'calls':>7}{'correct':>9}{'wrong':>7}{'weight':>8}{'total_pnl':>11}")
        for r in board:
            print(
                f"{r['agent_id']:<22}{r['accuracy']*100:>9.1f}%"
                f"{r['n_calls']:>7}{r['n_correct']:>9}{r['n_wrong']:>7}"
                f"{r['adaptive_weight']:>8.2f}{r['total_pnl']:>11.4f}"
            )
        return 0
    closed = loop.evaluate_open_trades(max_to_close=args.max)
    print(f"closed {len(closed)} open trades")
    for c in closed[:10]:
        print(f"  {c.symbol:<8} {c.direction:<6} entry={c.entry_price:.2f} exit={c.exit_price:.2f} "
              f"pnl={c.pnl_pct:+.2%} reason={c.exit_reason}")
    if closed:
        stats = loop.memory.stats_summary()
        print(f"\nmemory stats: {stats}")
    return 0


def cmd_scheduler(args: argparse.Namespace) -> int:
    from jexi_market.scheduler import AutonomousScheduler

    config = get_config()
    sched = AutonomousScheduler(config)
    if args.once:
        result = sched.run_once(args.once)
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0 if result.success else 1
    # Otherwise run forever (Ctrl-C to stop)
    sched.run_forever(
        scan_interval_seconds=args.scan_interval,
        analyze_interval_seconds=args.analyze_interval,
        monitor_interval_seconds=args.monitor_interval,
    )
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn
    from jexi_market.dashboard import app

    print(f"JEXI Market Dashboard starting on http://{args.host}:{args.port}")
    print("  GET /                  — health")
    print("  GET /api/overview      — portfolio + system state")
    print("  GET /api/agents        — agent roster + performance")
    print("  GET /api/strategies    — strategy registry")
    print("  GET /api/recent-trades — last N paper trades")
    print("  POST /api/analyze/{symbol} — trigger analysis")
    print("  POST /api/scan         — trigger scan")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_correlation(args: argparse.Namespace) -> int:
    from jexi_market.backtest import compute_correlation_matrix, find_correlated_clusters
    from jexi_market.data import MarketDataClient

    config = get_config()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    client = MarketDataClient()
    frames = {}
    for s in symbols:
        snap = client.get_daily(s, days=args.days)
        if snap.ok:
            frames[s] = snap.df
    matrix = compute_correlation_matrix(frames)
    print("Correlation matrix:")
    header = "          " + "  ".join(f"{s[:8]:>8}" for s in matrix)
    print(header)
    for s1 in matrix:
        row = f"{s1[:8]:<10}" + "  ".join(f"{matrix[s1].get(s2, 0):>8.2f}" for s2 in matrix)
        print(row)
    print()
    clusters = find_correlated_clusters(frames, threshold=args.threshold)
    if clusters:
        print(f"Correlated clusters (>= {args.threshold}):")
        for i, cluster in enumerate(clusters, 1):
            print(f"  cluster {i}: {', '.join(cluster)}")
    else:
        print(f"No correlated clusters (>= {args.threshold})")
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

    p_wf = sub.add_parser("walk-forward", help="Walk-forward backtest (out-of-sample validation)")
    p_wf.add_argument("--strategy", required=True)
    p_wf.add_argument("--symbol", required=True)
    p_wf.add_argument("--days", type=int, default=500)
    p_wf.add_argument("--windows", type=int, default=5)
    p_wf.add_argument("--json", action="store_true")
    p_wf.set_defaults(func=cmd_walk_forward)

    p_cmp = sub.add_parser("compare-strategies", help="Compare all strategies on one symbol")
    p_cmp.add_argument("--symbol", required=True)
    p_cmp.add_argument("--days", type=int, default=250)
    p_cmp.set_defaults(func=cmd_compare_strategies)

    p_eval = sub.add_parser("self-eval", help="Close open paper trades + update agent weights")
    p_eval.add_argument("--max", type=int, default=50, help="Max trades to evaluate")
    p_eval.add_argument("--leaderboard", action="store_true", help="Show agent leaderboard")
    p_eval.set_defaults(func=cmd_self_eval)

    p_sched = sub.add_parser("scheduler", help="Run the autonomous scheduler (foreground)")
    p_sched.add_argument("--once", default="", help="Run a single job (scan/analyze/monitor/daily_summary) and exit")
    p_sched.add_argument("--scan-interval", type=int, default=300)
    p_sched.add_argument("--analyze-interval", type=int, default=600)
    p_sched.add_argument("--monitor-interval", type=int, default=180)
    p_sched.set_defaults(func=cmd_scheduler)

    p_dash = sub.add_parser("dashboard", help="Start the FastAPI dashboard (uvicorn)")
    p_dash.add_argument("--host", default="0.0.0.0")
    p_dash.add_argument("--port", type=int, default=8088)
    p_dash.set_defaults(func=cmd_dashboard)

    p_corr = sub.add_parser("correlation", help="Compute correlation matrix across symbols")
    p_corr.add_argument("--symbols", required=True, help="Comma-separated")
    p_corr.add_argument("--days", type=int, default=120)
    p_corr.add_argument("--threshold", type=float, default=0.7)
    p_corr.set_defaults(func=cmd_correlation)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = get_config()
    _setup_logging(args.log_level or config.log_level)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
