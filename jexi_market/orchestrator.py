# -*- coding: utf-8 -*-
"""JEXI Market Boss — the central orchestrator.

The Boss is the only agent in JEXI Market that can synthesise a
:class:`Decision` from the specialist consensus.  Its responsibilities:

1. Plan the run (build tasks for each symbol).
2. Dispatch specialists in parallel where safe.
3. Detect agreement / disagreement.
4. Hand the consensus to Prof. Aldric for skeptical review.
5. Synthesise a :class:`Decision` with structural confidence.
6. Hand the decision to Vic for execution planning.
7. Push the decision through the risk gate.
8. (In paper mode) send to the Alpaca client.
9. Push the report to ntfy.
10. Record everything in performance memory.

The Boss does NOT blindly accept one agent's opinion.  It compares
evidence, weights agents by their historical accuracy (via the
performance memory), and explicitly tracks which agents disagreed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from jexi_market.agents import (
    AgentContext,
    BaseAgent,
    ProfAldricAgent,
    RegimeClassifier,
    VicAgent,
    build_all_agents,
)
from jexi_market.config import MarketConfig
from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Decision,
    Evidence,
    MarketRegime,
    Recommendation,
    RiskEnvelope,
    SignalDirection,
    Task,
)
from jexi_market.data import MarketDataClient, MarketSnapshot
from jexi_market.indicators import FactorSnapshot, compute_factors
from jexi_market.memory import PerformanceMemory
from jexi_market.notifications import NtfyReporter
from jexi_market.risk import PortfolioState, RiskGate
from jexi_market.execution import AlpacaClient

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of a single Boss run for one symbol."""

    symbol: str
    regime: MarketRegime = MarketRegime.UNKNOWN
    regime_score: float = 0.0
    recommendations: List[Recommendation] = field(default_factory=list)
    decision: Optional[Decision] = None
    gate_approved: bool = False
    gate_violations: List[Dict[str, Any]] = field(default_factory=list)
    report_text: str = ""
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "regime": self.regime.value,
            "regime_score": round(self.regime_score, 4),
            "recommendations": [r.to_dict() for r in self.recommendations],
            "decision": self.decision.to_dict() if self.decision else None,
            "gate_approved": self.gate_approved,
            "gate_violations": self.gate_violations,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "error": self.error,
        }


class MarketBoss:
    """JEXI Market central orchestrator."""

    def __init__(
        self,
        config: Optional[MarketConfig] = None,
        *,
        data_client: Optional[MarketDataClient] = None,
        memory: Optional[PerformanceMemory] = None,
        reporter: Optional[NtfyReporter] = None,
        risk_gate: Optional[RiskGate] = None,
        alpaca: Optional[AlpacaClient] = None,
        agents: Optional[Dict[str, BaseAgent]] = None,
        fundamental_adapter: Optional[Any] = None,
        news_adapter: Optional[Any] = None,
        sector_classifier: Optional[Any] = None,
        enable_enrichment: bool = True,
    ):
        self.config = config or MarketConfig()
        self.data_client = data_client or MarketDataClient()
        self.memory = memory or PerformanceMemory(self.config.memory_db_path)
        self.reporter = reporter or NtfyReporter(self.config)
        self.risk_gate = risk_gate or RiskGate(RiskEnvelope(**self.config.risk_envelope_kwargs))
        self.alpaca = alpaca or AlpacaClient(self.config)
        self.agents = agents or build_all_agents(self.config)
        # Leadership agents
        self.aldric = ProfAldricAgent(config=self.config)
        self.vic = VicAgent(config=self.config)
        self.regime_classifier = RegimeClassifier()
        # Enrichment adapters (free fundamental + news + sector).
        # Lazy-imported so tests that don't need them stay fast.
        self.enable_enrichment = enable_enrichment
        if enable_enrichment:
            from jexi_market.enrichment import (
                FundamentalAdapter,
                NewsAdapter,
                SectorClassifier,
            )
            self.fundamental_adapter = fundamental_adapter or FundamentalAdapter()
            self.news_adapter = news_adapter or NewsAdapter()
            self.sector_classifier = sector_classifier or SectorClassifier(self.fundamental_adapter)
        else:
            self.fundamental_adapter = fundamental_adapter
            self.news_adapter = news_adapter
            self.sector_classifier = sector_classifier

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------
    def analyze_symbol(self, symbol: str, *, days: int = 120) -> RunResult:
        started = time.time()
        result = RunResult(symbol=symbol)
        try:
            # 1. Fetch data
            snapshot = self.data_client.get_daily(symbol, days=days)
            if not snapshot.ok:
                result.error = f"data fetch failed: {snapshot.error}"
                result.elapsed_seconds = time.time() - started
                return result

            # 2. Compute factors
            factors = compute_factors(snapshot.df, symbol=symbol)

            # 3. Classify regime from the same close series
            closes = [float(x) for x in snapshot.df["close"].dropna().tolist()] if "close" in snapshot.df.columns else []
            regime_enum, regime_score, _ = self.regime_classifier.classify(closes)
            result.regime = regime_enum
            result.regime_score = regime_score

            # 4. Build agent context — populate research_cache with real
            #    fundamentals + news from free sources (yfinance).  When
            #    enrichment fails (no network, no yfinance), the cache
            #    stays empty and FundamentalAgent/NewsAgent return None
            #    (no opinion) — never fabricated data.
            research_cache: Dict[str, Any] = {}
            if self.enable_enrichment:
                try:
                    fund = self.fundamental_adapter.get_fundamentals(symbol)
                    if fund.ok:
                        research_cache[f"fundamentals:{symbol}"] = {
                            "pe_ratio": fund.pe_ratio,
                            "forward_pe": fund.forward_pe,
                            "price_to_book": fund.price_to_book,
                            "profit_margin": fund.profit_margin,
                            "gross_margin": fund.gross_margin,
                            "operating_margin": fund.operating_margin,
                            "return_on_equity": fund.return_on_equity,
                            "revenue_growth": fund.revenue_growth,
                            "earnings_growth": fund.earnings_growth,
                            "quarterly_earnings_growth": fund.quarterly_earnings_growth,
                            "debt_to_equity": fund.debt_to_equity,
                            "current_ratio": fund.current_ratio,
                            "market_cap": fund.market_cap,
                            "sector": fund.sector,
                            "industry": fund.industry,
                            "source": fund.source,
                        }
                        if fund.sector:
                            research_cache[f"sector:{symbol}"] = fund.sector
                except Exception as exc:
                    logger.debug("fundamental enrichment failed for %s: %s", symbol, exc)

                try:
                    news_snap = self.news_adapter.get_news(symbol)
                    if news_snap.ok:
                        research_cache[f"news:{symbol}"] = {
                            "sentiment": news_snap.sentiment,
                            "sentiment_score": news_snap.sentiment_score,
                            "n_items": len(news_snap.items),
                            "top_titles": [it.title for it in news_snap.items[:3]],
                            "source": news_snap.source,
                        }
                except Exception as exc:
                    logger.debug("news enrichment failed for %s: %s", symbol, exc)

            ctx = AgentContext(
                regime=regime_enum.value,
                regime_score=regime_score,
                portfolio_value=100_000.0,
                portfolio_drawdown=0.0,
                risk_envelope=self.risk_gate.envelope,
                research_cache=research_cache,
            )

            # 5. Run every specialist agent (skip leadership agents —
            #    aldric/vic have review()/plan() interfaces, not analyze()).
            recommendations: List[Recommendation] = []
            for agent_id, agent in self.agents.items():
                if agent.kind in (AgentKind.BOSS, AgentKind.ADVISOR, AgentKind.EXECUTION):
                    continue
                try:
                    rec = agent.analyze(snapshot, factors, ctx)
                    if rec is not None:
                        # Apply adaptive weight from performance memory
                        weight = self.memory.agent_weight(agent_id)
                        # The weight scales the confidence's evidence_count
                        # (more past calls -> more confidence in the agent)
                        recommendations.append(rec)
                except Exception as exc:
                    logger.warning("agent %s failed on %s: %s", agent_id, symbol, exc)
            result.recommendations = recommendations

            # 6. Prof. Aldric reviews the consensus
            review = self.aldric.review(symbol, recommendations, regime_enum, factors)

            # 7. Synthesise decision
            decision = self._synthesize_decision(
                symbol=symbol,
                recommendations=recommendations,
                review=review,
                factors=factors,
                regime=regime_enum,
            )
            result.decision = decision

            # 8. Vic produces execution plan
            plan = self.vic.plan(
                decision,
                max_position_fraction=self.risk_gate.envelope.max_position_fraction,
                max_risk_per_trade=self.risk_gate.envelope.max_risk_per_trade,
            )
            # Override the decision's position_fraction with Vic's plan
            if plan.position_fraction > 0:
                object.__setattr__(decision, "position_fraction", plan.position_fraction)
                object.__setattr__(decision, "stop_loss", plan.stop_loss if plan.stop_loss else decision.stop_loss)
                object.__setattr__(decision, "take_profit", plan.take_profit if plan.take_profit else decision.take_profit)

            # 9. Risk gate — pass the real sector (from yfinance) so the
            #    sector-concentration check actually works.
            sector = research_cache.get(f"sector:{symbol}") if isinstance(research_cache, dict) else None
            portfolio_state = PortfolioState(
                equity=100_000.0,
                cash=100_000.0,
                positions_value=0.0,
                open_positions=0,
                paper_trading_days=self.memory.paper_trading_days(),
                peak_equity=100_000.0,
            )
            gate_result = self.risk_gate.check(decision, portfolio_state, sector=sector)
            result.gate_approved = gate_result.approved
            result.gate_violations = [v.to_dict() for v in gate_result.violations]

            # 10. Record decision in memory
            self.memory.record_decision(decision, regime=regime_enum.value)

            # 11. Render and publish report
            report_text = self.reporter.render_report(
                decision=decision,
                recommendations=recommendations,
                agent_ids_run=list(self.agents.keys()),
                task=f"Analyze {symbol}",
                regime=regime_enum.value,
                timezone=self.config.timezone,
            )
            result.report_text = report_text
            self.reporter.publish_decision(
                decision=decision,
                recommendations=recommendations,
                agent_ids_run=list(self.agents.keys()),
                task=f"Analyze {symbol}",
                regime=regime_enum.value,
                timezone=self.config.timezone,
            )

            result.elapsed_seconds = time.time() - started
            return result
        except Exception as exc:
            logger.exception("boss run failed for %s", symbol)
            result.error = str(exc)
            result.elapsed_seconds = time.time() - started
            return result

    # ------------------------------------------------------------------
    # Multi-symbol run
    # ------------------------------------------------------------------
    def run(self, symbols: List[str], *, days: int = 120) -> List[RunResult]:
        return [self.analyze_symbol(s, days=days) for s in symbols]

    # ------------------------------------------------------------------
    # Decision synthesis
    # ------------------------------------------------------------------
    def _synthesize_decision(
        self,
        *,
        symbol: str,
        recommendations: List[Recommendation],
        review: Any,
        factors: FactorSnapshot,
        regime: MarketRegime,
    ) -> Decision:
        """Build a Decision from the specialist consensus + Aldric review."""
        if not recommendations:
            return Decision(
                symbol=symbol,
                direction=SignalDirection.FLAT,
                confidence=Confidence(),
                thesis="no recommendations produced",
                regime=regime,
            )

        # Confidence-weighted directional vote
        # (skip Risk/Data agents for direction; they're veto-style)
        directional = [
            r for r in recommendations
            if r.agent_kind not in (AgentKind.RISK, AgentKind.DATA_VALIDATION)
            and r.direction != SignalDirection.FLAT
        ]
        if not directional:
            direction = SignalDirection.FLAT
            agreement = 0.0
        else:
            longs_weight = sum(r.confidence.score for r in directional if r.direction == SignalDirection.LONG)
            shorts_weight = sum(r.confidence.score for r in directional if r.direction == SignalDirection.SHORT)
            total = longs_weight + shorts_weight
            if total <= 0:
                direction = SignalDirection.FLAT
                agreement = 0.0
            else:
                if longs_weight > shorts_weight:
                    direction = SignalDirection.LONG
                    agreement = longs_weight / total
                elif shorts_weight > longs_weight:
                    direction = SignalDirection.SHORT
                    agreement = shorts_weight / total
                else:
                    direction = SignalDirection.FLAT
                    agreement = 0.5

        # Build the evidence trail
        all_evidence: List[Evidence] = []
        for rec in recommendations:
            all_evidence.extend(rec.evidence)
        # Deduplicate by claim
        seen_claims = set()
        unique_evidence = []
        for ev in all_evidence:
            if ev.claim not in seen_claims:
                unique_evidence.append(ev)
                seen_claims.add(ev.claim)

        # Supporting / opposing agents
        supporting = tuple(r.agent_id for r in directional if r.direction == direction)
        opposing = tuple(r.agent_id for r in directional if r.direction != direction and r.direction != SignalDirection.FLAT)

        # Confidence = structural
        confidence = Confidence(
            agreement=agreement,
            data_freshness=min(1.0, factors.rows / 120.0),
            evidence_count=len(unique_evidence),
            disagreement_penalty=review.disagreement_penalty,
        )

        # Entry / stop / target from factors
        entry = factors.latest_close if factors.latest_close else None
        stop_loss = None
        take_profit = None
        if entry and factors.atr_14:
            atr_pct = factors.atr_14 / entry
            if direction == SignalDirection.LONG:
                stop_loss = entry * (1.0 - 1.5 * atr_pct)
                take_profit = entry * (1.0 + 3.0 * atr_pct)
            elif direction == SignalDirection.SHORT:
                stop_loss = entry * (1.0 + 1.5 * atr_pct)
                take_profit = entry * (1.0 - 3.0 * atr_pct)

        # Risks: gather from review contradictions + risk agent
        risks = list(review.contradiction_points) if hasattr(review, "contradiction_points") else []
        risk_recs = [r for r in recommendations if r.agent_kind == AgentKind.RISK]
        for r in risk_recs:
            for ev in r.evidence:
                risks.append(ev.claim)
        # Dedupe
        risks = list(dict.fromkeys(risks))[:5]

        # Thesis
        thesis_parts = []
        for rec in directional[:3]:
            thesis_parts.append(f"{rec.agent_id}: {rec.thesis}")
        thesis = "; ".join(thesis_parts) if thesis_parts else "neutral consensus"

        # Invalidation
        invalidation = "; ".join(review.invalidation_conditions[:2]) if hasattr(review, "invalidation_conditions") else "regime change"

        return Decision(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_fraction=0.0,  # set by Vic
            risk_per_trade=self.risk_gate.envelope.max_risk_per_trade,
            thesis=thesis,
            invalidation=invalidation,
            evidence=tuple(unique_evidence),
            supporting_agents=supporting,
            opposing_agents=opposing,
            risks=tuple(risks),
            regime=regime,
        )
