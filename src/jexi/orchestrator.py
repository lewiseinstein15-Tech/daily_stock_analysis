# -*- coding: utf-8 -*-
"""Jexi — the boss agent and orchestrator.

Jexi plans each run, dispatches the persona set, lets the leadership layer
(Prof Thorne on regime, Vic Sterling on execution) weigh in, synthesises a
structured report and pushes it to ntfy.  It is deliberately thin: it reuses
the repository's ``DataFetcherManager`` for data, the persona registry for
identity, the deterministic specialist runtime for opinions (LLM-backed mode
reuses the persona briefs as prompts), and the Jexi notifier for pushes.

The self-improvement *loop* lives in :mod:`src.jexi.loop`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from data_provider import DataFetcherManager
from src.jexi.notify import JexiNotifier
from src.jexi.papersim import SignalPlan
from src.jexi.persona import Persona, PersonaRegistry, get_persona_registry
from src.jexi.research import RESEARCH_OFF, resolve_research_backend
from src.jexi.specialist import (
    SIGNAL_FLAT,
    SIGNAL_LONG,
    SIGNAL_SHORT,
    SpecialistOpinion,
    analyze_stock_with_persona,
)

logger = logging.getLogger(__name__)

REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_SIDEWAYS = "sideways"
REGIME_VOLATILE = "volatile"

_DEFAULT_INDEX_BY_REGION = {
    "cn": "sh000001",
    "us": "^GSPC",
    "hk": "^HSI",
}

# Weight registry used by the self-improvement loop; as base_weight grows,
# a specialist's opinion counts for more in the consensus.
PERFORMANCE_WEIGHT_ENV = "JEXI_ADAPTIVE_WEIGHTS"


@dataclass
class RegimeAssessment:
    regime: str
    score: float = 0.0
    rationale: str = ""
    volatility: float = 0.0

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "score": round(self.score, 4),
            "volatility": round(self.volatility, 4),
            "rationale": self.rationale,
        }


class RegimeClassifier:
    """Deterministic market-regime classifier for the Prof Thorne persona."""

    def classify(self, df) -> RegimeAssessment:
        if df is None or df.empty or "close" not in df.columns:
            return RegimeAssessment(REGIME_SIDEWAYS, 0.0, "no index data available")
        closes = df["close"].dropna().tolist()
        latest = closes[-1]
        window = min(120, len(closes))
        lookback = closes[-window:]
        start = lookback[0]
        ret = latest / start - 1.0 if start else 0.0

        returns = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        mean = sum(returns) / len(returns) if returns else 0.0
        variance = (
            sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            if len(returns) > 1
            else 0.0
        )
        ann_vol = (variance ** 0.5) * (252 ** 0.5) if variance > 0 else 0.0

        if len(closes) >= 60:
            ma60_mean = sum(closes[-60:]) / 60
            above_ma60 = latest >= ma60_mean
            below_ma60 = latest < ma60_mean
        else:
            above_ma60 = True
            below_ma60 = False

        if ann_vol >= 0.45:
            regime, score, why = REGIME_VOLATILE, 0.0, f"annualised volatility {ann_vol:.0%} >= 45%"
        elif ret >= 0.08 and above_ma60:
            regime, score, why = REGIME_BULL, min(1.0, ret / 0.3), f"{window}d return {ret:+.1%} above rising MA60"
        elif ret <= -0.08 and below_ma60:
            regime, score, why = REGIME_BEAR, -min(1.0, abs(ret) / 0.3), f"{window}d return {ret:+.1%} below falling MA60"
        else:
            regime, score, why = REGIME_SIDEWAYS, 0.0, f"{window}d return {ret:+.1%} with no dominant trend"
        return RegimeAssessment(regime, score, f"{why}; ann vol {ann_vol:.1%}", ann_vol)


def _infer_region(codes: List[str]) -> str:
    for code in codes:
        upper = code.upper()
        if upper.startswith(("SH", "SZ", "BJ")) or upper.isdigit():
            return "cn"
        if upper.startswith(("HK",)):
            return "hk"
        if upper.isascii() and not upper.startswith("HK"):
            return "us"
    return "cn"


class ExecutionPlan:
    def __init__(self, plan: SignalPlan):
        self.plan = plan
        self.position_fraction = 0.0
        self.notes: List[str] = []

    def to_dict(self) -> dict:
        return {
            "code": self.plan.code,
            "signal": self.plan.signal,
            "target_direction": self.plan.target_direction,
            "confidence": round(self.plan.confidence, 4),
            "position_fraction": round(self.position_fraction, 4),
            "stop_loss": self.plan.stop_loss_pct,
            "take_profit": self.plan.take_profit_pct,
            "max_holding_days": self.plan.max_holding_days,
            "notes": self.notes,
        }


class SterlingExecutionOptimiser:
    """Victor Sterling: turn analyst consensus into an execution plan."""

    def optimise(
        self,
        plan: SignalPlan,
        *,
        risk_per_trade: float = 0.02,
        max_position_fraction: float = 0.25,
        annualised_vol: float = 0.0,
    ) -> ExecutionPlan:
        execution = ExecutionPlan(plan)
        if plan.signal == SIGNAL_FLAT or annualised_vol <= 0:
            execution.notes.append("no signal; stand aside")
            return execution
        vol_stop = min(0.15, max(0.04, 0.6 * annualised_vol))
        stop = max(plan.stop_loss_pct, vol_stop)
        take = max(plan.take_profit_pct, 1.6 * stop)
        plan.stop_loss_pct = stop
        plan.take_profit_pct = take
        execution.position_fraction = min(risk_per_trade / stop, max_position_fraction)
        execution.notes.append(
            f"risk-based sizing {execution.position_fraction:.0%} of equity "
            f"(2% risk / {stop:.0%} stop)"
        )
        if annualised_vol >= 0.45:
            execution.position_fraction *= 0.5
            execution.notes.append("volatility override: position halved (regime elevated)")
        execution.notes.append("fractional-kill style: no single trade risks > 2%")
        return execution


class JexiBossAgent:
    """Central orchestrator: plan -> dispatch -> arbitrate -> synthesise -> notify."""

    def __init__(
        self,
        config=None,
        registry: Optional[PersonaRegistry] = None,
        fetcher=None,
        notifier: Optional[JexiNotifier] = None,
        research_backend: Optional[str] = None,
        research_cache: Optional[dict] = None,
    ):
        if config is None:
            from src.config import get_config

            config = get_config()
        self.config = config
        self.registry = registry or get_persona_registry()
        self.fetcher = fetcher or DataFetcherManager()
        self.notifier = notifier or JexiNotifier(config)
        self.regime_classifier = RegimeClassifier()
        self.execution_optimiser = SterlingExecutionOptimiser()
        self.research_cache: Dict = research_cache if research_cache is not None else {}
        self.research_backend = resolve_research_backend(config, explicit=research_backend)
        if self.research_backend != RESEARCH_OFF:
            logger.info("Jexi research backend active: %s", self.research_backend)
        self.adaptive_weights: Dict[str, float] = {
            p.id: float(p.base_weight)
            for p in self.registry.specialists()
        }

    # -- data helpers -----------------------------------------------------
    def _fetch_daily(self, code: str, days: int = 250, start_date: Optional[str] = None, end_date: Optional[str] = None):
        if start_date and end_date:
            df, provider = self.fetcher.get_daily_data(code, start_date=start_date, end_date=end_date)
        else:
            df, provider = self.fetcher.get_daily_data(code, days=days)
        return df, provider

    def _fetch_regime_index(self, codes: List[str], days: int = 180):
        region = _infer_region(codes)
        index_code = _DEFAULT_INDEX_BY_REGION.get(region)
        if not index_code:
            return None, region
        try:
            df, _ = self._fetch_daily(index_code, days=days)
            return df, region
        except Exception as exc:  # index failure must not crash the run
            logger.warning("regime index fetch failed (%s): %s", index_code, exc)
            return None, region

    # -- per-stock analysis ----------------------------------------------
    def adjust_opinion(self, op: SpecialistOpinion, persona: Persona) -> SpecialistOpinion:
        """Bake the adaptive (self-loop) weight into a specialist opinion."""
        op.score = op.score * (1.0 + 0.25 * self.adaptive_weights.get(persona.id, 1.0))
        op.score = max(-1.0, min(1.0, op.score))
        return op

    def analyze_stock(
        self,
        code: str,
        days: int,
        specialists: List[Persona],
    ) -> Dict[str, object]:
        try:
            df, provider = self._fetch_daily(code, days)
        except Exception as exc:
            logger.error("fetch failed for %s: %s", code, exc)
            return {"code": code, "opinions": [], "provider": None, "error": str(exc), "rows": 0}
        opinions: List[SpecialistOpinion] = []
        for persona in specialists:
            op = analyze_stock_with_persona(
                persona,
                df,
                provider,
                code=code,
                research=self.research_backend,
                research_cache=self.research_cache,
                research_bucket=f"once:{code}",
            )
            self.adjust_opinion(op, persona)
            opinions.append(op)
        return {
            "code": code,
            "provider": provider,
            "rows": 0 if df is None else len(df),
            "opinions": opinions,
            "df": df,
            "error": None,
        }

    def run(
        self,
        stocks: List[str],
        *,
        days: int = 120,
        specialist_ids: Optional[List[str]] = None,
        start_time: Optional[float] = None,
    ) -> Dict[str, object]:
        started = start_time or time.time()
        specialists = self.registry.select(specialist_ids)

        index_df, region = self._fetch_regime_index(stocks, days=days)
        regime: RegimeAssessment = self.regime_classifier.classify(index_df)

        analyses = [self.analyze_stock(code, days, specialists) for code in stocks]
        by_code: Dict[str, List[SpecialistOpinion]] = {}
        errors: List[str] = []
        for result in analyses:
            if result["error"]:
                errors.append(f"{result['code']}: {result['error']}")
                continue
            by_code[result["code"]] = result["opinions"]

        consensus = self.build_consensus(by_code)
        execution = {
            plan.code: self.execution_optimiser.optimise(
                plan,
                annualised_vol=regime.volatility,
            )
            for plan in consensus
        }

        report_md = self.render_report(
            stocks=stocks,
            region=region,
            regime=regime,
            by_code=by_code,
            consensus=consensus,
            execution=execution,
            errors=errors,
            elapsed=time.time() - started,
            days=days,
        )
        self.notify_report(report_md, regime)

        return {
            "region": region,
            "regime": regime.to_dict(),
            "analyses": [a for a in analyses if not a["error"]],
            "errors": errors,
            "consensus": [p.to_dict() for p in consensus],
            "execution": {c: e.to_dict() for c, e in execution.items()},
            "report_md": report_md,
            "elapsed_seconds": round(time.time() - started, 2),
            "active_specialists": len(specialists),
        }

    # -- consensus & reporting -------------------------------------------
    def build_consensus(self, by_code: Dict[str, List[SpecialistOpinion]]) -> List[SignalPlan]:
        plans: List[SignalPlan] = []
        for code, opinions in by_code.items():
            total_w = 0.0
            weighted = 0.0
            best_name = code
            for op in opinions:
                w = op.confidence * 10.0
                weighted += w * op.score
                total_w += w
                best_name = op.persona.name
            score = weighted / total_w if total_w > 0 else 0.0
            conf = min(1.0, 0.35 + 0.55 * abs(score))
            signal = (
                SIGNAL_LONG if score >= 0.08 else (SIGNAL_SHORT if score <= -0.08 else SIGNAL_FLAT)
            )
            plans.append(
                SignalPlan(
                    code=code,
                    name=best_name,
                    signal=signal,
                    target_direction="up" if signal == SIGNAL_LONG else ("down" if signal == SIGNAL_SHORT else None),
                    confidence=round(conf, 4),
                )
            )
        return plans

    def notify_report(self, report_md: str, regime: RegimeAssessment) -> None:
        title = f"J.E.X.I. 市场分析 · {regime.regime}"
        self.notifier.report(title, report_md, tags=["chart", "stock"])

    def render_report(
        self,
        *,
        stocks: List[str],
        region: str,
        regime: RegimeAssessment,
        by_code: Dict[str, List[SpecialistOpinion]],
        consensus: List[SignalPlan],
        execution: Dict[str, ExecutionPlan],
        errors: List[str],
        elapsed: float,
        days: int,
    ) -> str:
        lines: List[str] = []
        lines.append(f"# J.E.X.I. 综合分析报告 — {len(stocks)} 只标的 · {region}")
        lines.append(f"**市场状态**: {regime.regime}（{regime.rationale}）")
        lines.append(f"**运行耗时**: {elapsed:.1f}s · 窗口 {days} 交易日")
        lines.append("")

        for plan in consensus:
            code = plan.code
            lines.append(f"## {code} — {plan.signal.upper()} (confidence {plan.confidence:.0%})")
            for op in by_code.get(code, []):
                arrow = {"long": "▲", "flat": "・", "short": "▼"}[op.signal]
                lines.append(
                    f"- {arrow} **{op.persona.name}** ({op.persona.tilt}): {op.signal} "
                    f"score {op.score:+.2f} conf {op.confidence:.0%}"
                )
                lines.append(f"  - {op.rationale[0] if op.rationale else ''}")
            plan_exec = execution.get(code)
            if plan_exec:
                lines.append(
                    f"- **{plan_exec.plan.name}**: 计划仓位 {plan_exec.position_fraction:.0%} · "
                    f"止损 {plan_exec.plan.stop_loss_pct:.0%} · 止盈 {plan_exec.plan.take_profit_pct:.0%}"
                )
            lines.append("")

        if errors:
            lines.append("## 数据告警")
            for err in errors:
                lines.append(f"- ⚠ {err}")
            lines.append("")

        lines.append("## 风险与安全")
        lines.append("- 全部建议仅供纸面/研究用途，不构成实盘指令。")
        lines.append("- 单笔风险 ≤ 2%，止损止盈必须成对设置；回撤超 10% 自动暂停。")
        lines.append("- 高波动（>45% 年化）时对半削减仓位。")
        return "\n".join(lines)


def get_jexi(config=None, **kwargs) -> JexiBossAgent:
    """Factory to match the repository's ``get_*`` accessor convention."""
    return JexiBossAgent(config=config, **kwargs)
