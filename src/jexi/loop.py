# -*- coding: utf-8 -*-
"""Jexi's self-improvement loop: test -> evaluate -> adapt -> re-test.

The loop runs a fixed set of historical *scenario* windows (bull / bear /
sideways / volatile) against the consensus engine, computes the four target
metrics (win rate, Sharpe, max drawdown, total return) and compares them to
``JEXI_TARGET_*``.  On each iteration the adaptive specialist weights are
nudged toward the specialists whose signals performed best, then re-run —
mirroring the repository's existing ``skill_opinion_*`` auto-weighting but
scoped to the Jexi specialist set.  The loop is capped by
``JEXI_MAX_ITERATIONS`` and is journaled to ``data/jexi/`` (git-ignored).

All evaluation is on historical, paper-only data.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.jexi.metrics import scenario_metrics_snapshot
from src.jexi.orchestrator import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_SIDEWAYS,
    JexiBossAgent,
)
from src.jexi.papersim import SignalPlan, simulate_plans
from src.jexi.specialist import analyze_stock_with_persona

logger = logging.getLogger(__name__)

JOURNAL_ROOT = Path(os.getenv("JEXI_JOURNAL_DIR", "data/jexi"))

# Historical scenario windows.  The pilot evaluates 2020-2025: the 2020 COVID
# crash/recovery (volatile), the 2020-21 melt-up (bull), the 2022 bear, and a
# 2023 sideways-ish tape.  Synthetic sequestered data can be supplied instead
# via the CLI/tests for fully offline CI runs.
SCENARIOS = {
    "bull": {"start": "2020-11-01", "end": "2021-12-31", "tickers": []},
    "bear": {"start": "2022-01-01", "end": "2022-12-31", "tickers": []},
    "sideways": {"start": "2023-01-01", "end": "2023-12-31", "tickers": []},
    "volatile": {"start": "2020-02-01", "end": "2020-05-31", "tickers": []},
}

FIVE_YEAR_WINDOW = {"start": "2020-01-01", "end": "2025-12-31", "tickers": []}

LOOKBACK_WINDOW_DAYS = 120     # trading bars of lookback for opinion slices
MIN_OPINION_BARS = 40          # too little history -> no opinion that window
DEFAULT_REBALANCE_DAYS = 20    # cadence of the rolling backtest
TREND_LOOKBACK_BARS = 100      # SMA window for the per-asset trend floor


@dataclass
class IterationOutcome:
    iteration: int
    scenario: str
    metrics: Dict[str, float]
    pass_scenario: bool
    adapt_log: List[str] = field(default_factory=list)


@dataclass
class LoopResult:
    iterations: List[IterationOutcome] = field(default_factory=list)
    converged: bool = False
    journal_path: Optional[Path] = None

    def summary(self) -> str:
        lines = []
        worst = None
        for it in self.iterations:
            lines.append(
                f"  iter {it.iteration} {it.scenario}: "
                f"win {it.metrics['win_rate']:.0%} sharpe {it.metrics['sharpe']:+.2f} "
                f"maxdd {it.metrics['max_drawdown']:.0%} ret {it.metrics['total_return']:+.0%} "
                f"-> {'PASS' if it.pass_scenario else 'FAIL'}"
            )
            if worst is None or it.metrics["total_return"] < worst:
                worst = it.metrics["total_return"]
        status = "CONVERGED" if self.converged else "NOT CONVERGED"
        return f"Jexi loop {status}\n" + "\n".join(lines)


def targets_from_config(config) -> Dict[str, float]:
    return {
        "win_rate": getattr(config, "jexi_target_win_rate", 0.55),
        "sharpe": getattr(config, "jexi_target_sharpe", 1.2),
        "max_drawdown": getattr(config, "jexi_target_max_drawdown", 0.15),
        "min_total_return": getattr(config, "jexi_target_min_total_return", 0.05),
    }


class JexiLearningLoop:
    """Owns the test/evaluate/adapt cycle over scenario windows."""

    def __init__(
        self,
        jexi: JexiBossAgent,
        *,
        ticker_lists: Optional[Dict[str, List[str]]] = None,
        max_iterations: int = 10,
        targets: Optional[Dict[str, float]] = None,
        journal_dir: Optional[Path] = None,
        rebalance_days: Optional[int] = None,
        lookback_days: int = LOOKBACK_WINDOW_DAYS,
        specialist_ids: Optional[List[str]] = None,
        research_backend: Optional[str] = None,
        regime_gate: bool = False,
        trend_gate: bool = False,
    ):
        self.jexi = jexi
        self.ticker_lists = ticker_lists or {}
        self.max_iterations = max_iterations
        self.targets = targets or targets_from_config(jexi.config)
        self.journal_dir = Path(journal_dir or JOURNAL_ROOT)
        self.result = LoopResult()
        self.rebalance_days = rebalance_days
        self.lookback_days = lookback_days
        self.specialist_ids = specialist_ids
        self.research_backend = research_backend
        self.regime_gate = regime_gate
        self.trend_gate = trend_gate

    def _active_personas(self) -> List:
        personas = self.jexi.registry.specialists()
        if self.specialist_ids is None:
            return [p for p in personas if p.id in self.jexi.adaptive_weights]
        selected = set(self.specialist_ids)
        return [p for p in personas if p.id in selected and p.id in self.jexi.adaptive_weights]

    # -- scenario data ----------------------------------------------------
    def _load_window(self, start: str, end: str, tickers: List[str]) -> Dict[str, object]:
        """Fetch per-window daily data for each ticker slice (no look-ahead).

        Returns {code: {"df": DataFrame, "opinions": [SpecialistOpinion,...]}}.
        Opinions are computed on the window-sliced frame so signals never use
        bars after the scenario end.
        """
        frames = {}
        opinions_by_code: Dict[str, list] = {}
        specialists = self._active_personas()
        for code in tickers:
            try:
                df, _ = self.jexi._fetch_daily(code, days=250)
                # trim to window
                if df is not None and not df.empty and "date" in df.columns:
                    df["__date"] = df["date"].astype(str).str[:10]
                    df = df[(df["__date"] >= start) & (df["__date"] <= end)]
                    df = df.drop(columns=["__date"])
            except Exception as exc:  # a single failing ticker must not kill the scenario
                logger.warning("scenario window fetch failed for %s: %s", code, exc)
                continue
            if df is None or df.empty or "close" not in df.columns:
                continue
            frames[code] = df
            opinions_by_code[code] = [
                self.jexi.adjust_opinion(
                    analyze_stock_with_persona(
                        p,
                        df,
                        code=code,
                        research=self.research_backend,
                        research_cache=self.jexi.research_cache,
                        research_bucket=f"{start}:{end}:{code}",
                    ),
                    p,
                )
                for p in specialists
            ]
        return {"frames": frames, "opinions": opinions_by_code}

    def _load_scenario_frames(
        self,
        start: str,
        end: str,
        tickers: List[str],
        lookback_calendar_days: int = 270,
    ) -> Dict[str, object]:
        """Fetch the full window (plus lookback buffer) for each ticker.

        The buffer before ``start`` gives the rolling backtest enough history to
        build opinion slices for the first chunks (no look-ahead: signal slices
        always end strictly before the chunk they are evaluated on).
        """
        import datetime as _dt

        buffer_start = (
            _dt.datetime.strptime(start, "%Y-%m-%d") - _dt.timedelta(days=lookback_calendar_days)
        ).strftime("%Y-%m-%d")
        frames: Dict[str, object] = {}
        for code in tickers:
            try:
                df, _ = self.jexi._fetch_daily(code, start_date=buffer_start, end_date=end)
            except Exception as exc:
                logger.warning("scenario fetch failed for %s: %s", code, exc)
                continue
            if df is None or df.empty or "close" not in df.columns:
                continue
            df = df.copy()
            df["date"] = df["date"].astype(str).str[:10]
            df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
            frames[code] = df
        return frames

    def backtest_scenario(self, start: str, end: str, tickers: List[str]) -> Dict[str, float]:
        """Rolling paper-trading backtest over the window.

        Every ``rebalance_days`` calendar bars the pipeline re-evaluates each
        ticker on the trailing ``lookback_days`` bars, builds the consensus,
        and papersim-trades the chunk.  Equity compounds across chunks; all
        closed trades feed the win-rate / Sharpe / drawdown metrics.
        """
        frames = self._load_scenario_frames(start, end, tickers)
        if not frames:
            return {"win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "total_return": 0.0,
                    "n_trades": 0, "pass_scenario": False, "_trades": [], "_n_chunks": 0}

        calendar = sorted(
            {
                str(d)[:10]
                for frame in frames.values()
                for d in frame["date"]
                if start <= str(d)[:10] <= end
            }
        )
        if len(calendar) < MIN_OPINION_BARS + 2:
            return {"win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "total_return": 0.0,
                    "n_trades": 0, "pass_scenario": False, "_trades": [], "_n_chunks": 0}

        step = self.rebalance_days or DEFAULT_REBALANCE_DAYS
        specialists = self._active_personas()
        risk_per_trade = getattr(self.jexi.config, "jexi_risk_per_trade", 0.02)
        max_position_fraction = getattr(self.jexi.config, "jexi_max_position_fraction", 0.25)

        book = 100_000.0
        equity_abs: List[float] = []
        dates_abs: List[str] = []
        all_trades = []
        n_chunks = 0
        persona_credit: Dict[str, float] = defaultdict(float)

        for i in range(0, len(calendar), step):
            chunk_dates = calendar[i : i + step]
            if len(chunk_dates) < 2:
                continue
            chunk_start = chunk_dates[0]
            chunk_end = chunk_dates[-1]

            opinions_by_code: Dict[str, list] = {}
            for code, frame in frames.items():
                look = frame[frame["date"] < chunk_start].tail(self.lookback_days)
                if len(look) < MIN_OPINION_BARS:
                    continue
                opinions_by_code[code] = [
                    self.jexi.adjust_opinion(
                        analyze_stock_with_persona(
                            p,
                            look,
                            code=code,
                            research=self.research_backend,
                            research_cache=self.jexi.research_cache,
                            research_bucket=f"{start}:{end}:{code}",
                        ),
                        p,
                    )
                    for p in specialists
                ]

            plans = self.jexi.build_consensus(opinions_by_code)
            if not plans:
                continue

            if self.regime_gate:
                gate_frame = frames.get("SPY")
                if gate_frame is None:
                    gate_frame = frames.get("^GSPC")
                if gate_frame is not None and not gate_frame.empty:
                    regime = gate_frame[gate_frame["date"] < chunk_start].tail(self.lookback_days)
                    if len(regime) >= MIN_OPINION_BARS:
                        assessment = self.jexi.regime_classifier.classify(regime)
                        plans = self._gate_plans(plans, assessment.regime)

            if self.trend_gate:
                plans = self._trend_gate_plans(plans, frames, chunk_start)

            chunk_frames = {}
            for code, frame in frames.items():
                rows = frame[frame["date"] <= chunk_end]
                rows = rows[rows["date"] >= chunk_start]
                if not rows.empty:
                    chunk_frames[code] = rows.reset_index(drop=True)

            # Per-persona credit: agree with the trade direction on a green
            # chunk (or disagree on a red one) -> positive, swap -> negative.
            plan_by_code = {p.code: p for p in plans}
            for code, plan in plan_by_code.items():
                if plan.signal not in ("long", "short"):
                    continue
                rows = chunk_frames.get(code)
                if rows is None or rows.empty or len(rows) < 2:
                    continue
                first_c = float(rows.iloc[0]["close"])
                last_c = float(rows.iloc[-1]["close"])
                if first_c <= 0:
                    continue
                ret = last_c / first_c - 1.0
                if plan.signal == "short":
                    ret = -ret
                opinions = opinions_by_code.get(code) or []
                for op in opinions:
                    agreement = 0.0
                    if op.signal == plan.signal:
                        agreement = 1.0
                    elif op.signal in ("long", "short"):
                        agreement = -1.0
                    if agreement:
                        persona_credit[op.persona.id] += agreement * ret

            sim = simulate_plans(
                plans,
                chunk_frames,
                start_cash=book,
                risk_per_trade=risk_per_trade,
                max_position_fraction=max_position_fraction,
            )
            if sim.equity_series:
                init = sim.equity_series[0] or book
                equity_abs.extend(book * (v / init) for v in sim.equity_series)
                dates_abs.extend(sim.dates)
                book = sim.equity_series[-1]
            all_trades.extend(t.to_dict() for t in sim.trades)
            n_chunks += 1

        metrics = scenario_metrics_snapshot(equity_abs or [book], all_trades)
        metrics["pass_scenario"] = (
            metrics["win_rate"] >= self.targets["win_rate"]
            and metrics["sharpe"] >= self.targets["sharpe"]
            and metrics["max_drawdown"] <= self.targets["max_drawdown"]
            and metrics["total_return"] >= self.targets["min_total_return"]
        )
        metrics["_trades"] = all_trades
        metrics["_n_chunks"] = n_chunks
        metrics["_persona_credit"] = dict(persona_credit)
        return metrics

    def _evaluate_window(self, start: str, end: str, tickers: List[str]) -> Dict[str, float]:
        if self.rebalance_days:
            return self.backtest_scenario(start, end, tickers)
        window = self._load_window(start, end, tickers)
        frames = window["frames"]
        opinions = window["opinions"]

        # Reuse the orchestrator's consensus — one source of truth for math.
        plans = self.jexi.build_consensus(opinions)

        sim = simulate_plans(
            plans,
            frames,
            risk_per_trade=getattr(self.jexi.config, "jexi_risk_per_trade", 0.02),
            max_position_fraction=getattr(self.jexi.config, "jexi_max_position_fraction", 0.25),
        )
        trades = [t.to_dict() for t in sim.trades]
        metrics = scenario_metrics_snapshot(sim.equity_series, trades)
        metrics["pass_scenario"] = (
            metrics["win_rate"] >= self.targets["win_rate"]
            and metrics["sharpe"] >= self.targets["sharpe"]
            and metrics["max_drawdown"] <= self.targets["max_drawdown"]
            and metrics["total_return"] >= self.targets["min_total_return"]
        )
        metrics["_trades"] = trades
        return metrics

    def _gate_plans(self, plans: List[SignalPlan], regime: str) -> List[SignalPlan]:
        """Regime-aware direction filter (Prof Thorne weighs in on consensus).

        - bear tape: longs are flat unless the consensus is strong
        - bull tape: shorts are flat unless the consensus is strong
        - sideways tape: only strong conviction trades at all
        """
        gated = []
        for plan in plans:
            signal = plan.signal
            if regime == REGIME_BEAR and signal == "long" and plan.confidence < 0.6:
                signal = "flat"
            elif regime == REGIME_BULL and signal == "short" and plan.confidence < 0.6:
                signal = "flat"
            elif regime == REGIME_SIDEWAYS and signal in ("long", "short") and plan.confidence < 0.5:
                signal = "flat"
            gated.append(replace(plan, signal=signal, target_direction=(
                "up" if signal == "long" else ("down" if signal == "short" else None)
            )))
        return gated

    def _trend_gate_plans(self, plans: List[SignalPlan], frames, chunk_start: str) -> List[SignalPlan]:
        """Per-asset trend floor (industry-standard john cut): only risk fresh
        longs when the ticker sits above its longer SMA, fresh shorts below it.

        Vetoes the bear-market buy-the-dip long bias that dragged win rates to
        ~30% in 2022 without flattening every position like the regime gate.
        """
        gated = []
        for plan in plans:
            signal = plan.signal
            if signal in ("long", "short"):
                frame = frames.get(plan.code)
                if frame is not None and not frame.empty and "close" in frame.columns:
                    look = frame[frame["date"] < chunk_start]
                    closes = look["close"].dropna().tolist()
                    recent = closes[-min(TREND_LOOKBACK_BARS, len(closes)):] if closes else []
                    if len(recent) >= TREND_LOOKBACK_BARS:
                        sma = sum(recent) / len(recent)
                        last = recent[-1]
                        if signal == "long" and last < sma:
                            signal = "flat"
                        elif signal == "short" and last > sma:
                            signal = "flat"
            gated.append(replace(plan, signal=signal, target_direction=(
                "up" if signal == "long" else ("down" if signal == "short" else None)
            )))
        return gated

    # -- adaptation ---------------------------------------------------------
    def _adapt(self, scenario: str, outcome: Dict[str, float], iteration: int) -> List[str]:
        """Nudge adaptive weights by per-persona credit (profit attribution).

        Each specialist that agreed with a winning chunk direction earns
        positive credit and gets up-weighted; disagreeing specialists get
        down-weighted.  Credit is normalized per scenario so the nudge is
        comparably sized across iterations.
        """
        log: List[str] = []
        credit = outcome.get("_persona_credit") or {}
        if not credit:
            log.append("no directional credit recorded; weights unchanged")
            return log
        max_abs = max((abs(v) for v in credit.values()), default=0.0)
        if max_abs <= 0:
            log.append("flat credit; weights unchanged")
            return log
        nudged = 0
        for pid, value in credit.items():
            if pid not in self.jexi.adaptive_weights:
                continue
            delta = 0.06 * (value / max_abs)
            self.jexi.adaptive_weights[pid] = max(
                0.2, min(3.0, self.jexi.adaptive_weights[pid] + delta)
            )
            nudged += 1
        best = sorted(credit.items(), key=lambda kv: kv[1], reverse=True)[:3]
        worst = sorted(credit.items(), key=lambda kv: kv[1])[:3]
        log.append(
            f"iter {iteration}: nudged {nudged} specialists "
            f"(top {[p for p, _ in best]} up, {[p for p, _ in worst]} down)"
        )
        return log

    # -- loop ---------------------------------------------------------------
    def run(
        self,
        scenarios: Optional[List[str]] = None,
        *,
        stop_on_first_pass: bool = False,
    ) -> LoopResult:
        scenario_names = scenarios or list(self.ticker_lists)
        if not scenario_names:
            raise ValueError("no scenario ticker lists configured")

        best_metrics: Dict[str, float] = {"win_rate": 0.0, "sharpe": -10.0, "max_drawdown": 1.0, "total_return": -1.0}
        converged_windows = 0

        for iteration in range(1, self.max_iterations + 1):
            window_passes = 0
            for scenario in scenario_names:
                spec = SCENARIOS.get(scenario, {})
                tickers = self.ticker_lists.get(scenario, [])
                outcome = self._evaluate_window(spec.get("start", ""), spec.get("end", ""), tickers)
                for key in best_metrics:
                    if key == "max_drawdown":
                        best_metrics[key] = min(best_metrics[key], outcome[key])
                    else:
                        best_metrics[key] = max(best_metrics[key], outcome[key])
                passes = bool(outcome.get("pass_scenario"))
                window_passes += int(passes)
                adapt_log = self._adapt(scenario, outcome, iteration) if not passes else ["window passed"]
                self.result.iterations.append(
                    IterationOutcome(
                        iteration=iteration,
                        scenario=scenario,
                        metrics={k: v for k, v in outcome.items() if not k.startswith("_")},
                        pass_scenario=passes,
                        adapt_log=adapt_log,
                    )
                )
                self._journal(iteration, scenario, outcome)
                logger.info(
                    "iter=%d scenario=%s passes=%s metrics=%s",
                    iteration,
                    scenario,
                    passes,
                    {k: v for k, v in outcome.items() if not k.startswith("_")},
                )

            self.jexi.notifier.milestone(
                f"JEXI 迭代 {iteration}/{self.max_iterations}",
                f"通过 {window_passes}/{len(scenario_names)} 场景；最佳 win={best_metrics['win_rate']:.0%} "
                f"sharpe={best_metrics['sharpe']:+.2f} maxdd={best_metrics['max_drawdown']:.0%}",
                tags=["chart", "rocket"],
            )

            converged_windows = window_passes
            if window_passes == len(scenario_names) and stop_on_first_pass:
                break

        self.result.converged = converged_windows == len(scenario_names)
        self.result.journal_path = self.journal_dir / "last_loop.json"
        return self.result

    def _journal(self, iteration: int, scenario: str, outcome: Dict[str, float]) -> None:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "iteration": iteration,
            "scenario": scenario,
            "metrics": {k: v for k, v in outcome.items() if not k.startswith("_")},
            "n_trades": len(outcome.get("_trades") or []),
            "adaptive_weights": {k: round(v, 3) for k, v in sorted(self.jexi.adaptive_weights.items())},
        }
        path = self.journal_dir / f"{scenario}_iter_{iteration}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
        with open(self.journal_dir / "last_loop.json", "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
