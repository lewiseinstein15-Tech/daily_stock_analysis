# -*- coding: utf-8 -*-
"""Specialist agents for JEXI Market.

Each agent here is a real, deterministic specialist that consumes the
shared :class:`FactorSnapshot` and produces a typed
:class:`Recommendation` with concrete :class:`Evidence`.  These are NOT
"functions with fancy names": each one applies a different lens to the
same data and reaches a different conclusion, which is exactly what the
orchestrator needs to detect agreement vs. disagreement.

Specialists implemented here:
  * ``fundamental`` — value/quality lens (mocks real fundamentals
    because we don't have a paid fundamental feed; produces honest
    "fundamentals unavailable" evidence when no fundamental data is
    present, never fabricates P/E or earnings).
  * ``technical`` — trend/momentum/volume/RSI/MACD/Bollinger lens.
  * ``quant`` — statistical/factor lens (volatility regime, momentum
    factor, mean-reversion z-score).
  * ``macro`` — regime/macro lens (reads the AgentContext regime field
    that Prof. Aldric's classifier produces).
  * ``news`` — sentiment lens.  When no news feed is available, returns
    ``None`` (no opinion) rather than inventing sentiment.
  * ``risk`` — tail-risk / drawdown / volatility lens; can vote AGAINST
    a trade even when other agents agree.
  * ``data_validation`` — checks snapshot freshness/quality; if data is
    stale or sparse, returns a "no-trade" recommendation with evidence.
  * ``market_monitor`` — detects unusual volume / volatility expansion.
"""

from __future__ import annotations

import logging
from typing import Optional

from jexi_market.agents.base import (
    AgentContext,
    BaseAgent,
    register_agent,
)
from jexi_market.contracts import (
    AgentKind,
    Evidence,
    Recommendation,
    SignalDirection,
)
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import FactorSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Technical Analysis Agent
# ---------------------------------------------------------------------------


@register_agent
class TechnicalAgent(BaseAgent):
    """Trend/momentum/volume/RSI/MACD/Bollinger agent."""

    id = "technical"
    name = "Technical Analyst"
    kind = AgentKind.TECHNICAL

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok or factors.rows < 30:
            return None

        score = 0.0
        evidence_claims = []

        # Trend: price vs SMA20 vs SMA50
        if factors.sma_20 and factors.sma_50:
            if factors.latest_close > factors.sma_20:
                score += 0.25
                evidence_claims.append(
                    self.evidence(
                        f"{snapshot.symbol} price {factors.latest_close:.2f} above SMA20 {factors.sma_20:.2f}",
                        source="technical",
                        reference=f"{snapshot.symbol}:sma20",
                    )
                )
            else:
                score -= 0.25
            if factors.sma_20 > factors.sma_50:
                score += 0.2
                evidence_claims.append(
                    self.evidence(
                        f"SMA20 {factors.sma_20:.2f} above SMA50 {factors.sma_50:.2f} (uptrend)",
                        source="technical",
                        reference=f"{snapshot.symbol}:sma_cross",
                    )
                )
            else:
                score -= 0.2

        # Momentum: 3d / 10d / 20d returns
        mom = 0.5 * factors.momentum_3d + 0.3 * factors.momentum_10d + 0.2 * factors.momentum_20d
        if mom > 0.02:
            score += 0.25
            evidence_claims.append(
                self.evidence(
                    f"positive momentum blend {mom:+.2%} (3d/10d/20d)",
                    source="technical",
                    reference=f"{snapshot.symbol}:momentum",
                )
            )
        elif mom < -0.02:
            score -= 0.25

        # RSI: overbought / oversold
        if factors.rsi_14 is not None:
            if factors.rsi_14 < 30:
                score += 0.15
                evidence_claims.append(
                    self.evidence(
                        f"RSI(14) {factors.rsi_14:.1f} oversold",
                        source="technical",
                        reference=f"{snapshot.symbol}:rsi",
                    )
                )
            elif factors.rsi_14 > 70:
                score -= 0.15
                evidence_claims.append(
                    self.evidence(
                        f"RSI(14) {factors.rsi_14:.1f} overbought",
                        source="technical",
                        reference=f"{snapshot.symbol}:rsi",
                    )
                )

        # MACD histogram
        if factors.macd_hist is not None:
            if factors.macd_hist > 0:
                score += 0.15
                evidence_claims.append(
                    self.evidence(
                        f"MACD histogram positive ({factors.macd_hist:+.4f})",
                        source="technical",
                        reference=f"{snapshot.symbol}:macd",
                    )
                )
            else:
                score -= 0.15

        # Volume confirmation
        if factors.volume_ratio_5_20 > 1.3:
            score += 0.1
            evidence_claims.append(
                self.evidence(
                    f"volume expansion (5d/20d ratio {factors.volume_ratio_5_20:.2f})",
                    source="technical",
                    reference=f"{snapshot.symbol}:volume",
                )
            )

        score = max(-1.0, min(1.0, score))
        if score >= 0.15:
            direction = SignalDirection.LONG
        elif score <= -0.15:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        # Stop / target from ATR
        stop_pct = 0.05
        target_pct = 0.10
        if factors.atr_14 and factors.latest_close:
            stop_pct = max(0.03, min(0.12, (1.5 * factors.atr_14) / factors.latest_close))
            target_pct = stop_pct * 2.0

        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            target_price=(factors.latest_close * (1 + target_pct)) if direction != SignalDirection.FLAT else None,
            stop_loss=(factors.latest_close * (1 - stop_pct)) if direction == SignalDirection.LONG
                       else (factors.latest_close * (1 + stop_pct)) if direction == SignalDirection.SHORT
                       else None,
            take_profit=(factors.latest_close * (1 + target_pct)) if direction == SignalDirection.LONG
                         else (factors.latest_close * (1 - target_pct)) if direction == SignalDirection.SHORT
                         else None,
            risk_per_trade=0.02,
            max_holding_days=15,
            thesis=f"technical score {score:+.2f}; trend/momentum/volume/RSI composite",
            invalidation=f"close back below SMA20 ({factors.sma_20}) or RSI reversal",
            evidence=tuple(evidence_claims) or (self.evidence("technical factors neutral", source="technical"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors),
        )


# ---------------------------------------------------------------------------
# Fundamental Analysis Agent
# ---------------------------------------------------------------------------


@register_agent
class FundamentalAgent(BaseAgent):
    """Value / quality lens.

    IMPORTANT: this agent does NOT invent fundamentals.  If the snapshot
    has no fundamental payload (which is the default — the repo's free
    data sources don't ship P/E or earnings for every ticker), the
    agent returns ``None`` (no opinion).  This is the correct behaviour
    per spec section 16: "if data is unavailable, say that the data is
    unavailable. DO NOT INVENT DATA."

    When a fundamental payload IS attached to the snapshot (via
    ``ctx.research_cache`` or a future fundamental adapter), the agent
    will use it.  This makes the agent forward-compatible without
    fabricating data today.
    """

    id = "fundamental"
    name = "Fundamental Analyst"
    kind = AgentKind.FUNDAMENTAL

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok:
            return None

        # Look up fundamentals from the research cache (populated by the
        # research engine or a future fundamental adapter).  We never
        # invent this.
        fundamentals = ctx.research_cache.get(f"fundamentals:{snapshot.symbol}")
        if not fundamentals:
            # Honest "no opinion" — return None so the orchestrator
            # records this agent as "skipped (data unavailable)".
            return None

        # If we got real fundamentals, score them.
        pe = fundamentals.get("pe_ratio")
        eps_growth = fundamentals.get("eps_growth_yoy")
        margin = fundamentals.get("gross_margin")
        score = 0.0
        claims = []
        if pe is not None:
            if pe < 15:
                score += 0.3
                claims.append(self.evidence(f"P/E {pe:.1f} below 15 (cheap)", source="fundamental", reference=f"{snapshot.symbol}:pe"))
            elif pe > 40:
                score -= 0.2
                claims.append(self.evidence(f"P/E {pe:.1f} above 40 (rich)", source="fundamental", reference=f"{snapshot.symbol}:pe"))
        if eps_growth is not None and eps_growth > 0.15:
            score += 0.3
            claims.append(self.evidence(f"EPS YoY growth {eps_growth:.0%}", source="fundamental", reference=f"{snapshot.symbol}:eps"))
        if margin is not None and margin > 0.4:
            score += 0.15
            claims.append(self.evidence(f"gross margin {margin:.0%}", source="fundamental", reference=f"{snapshot.symbol}:margin"))

        score = max(-1.0, min(1.0, score))
        direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=f"fundamental score {score:+.2f}",
            invalidation="earnings miss or guidance cut",
            evidence=tuple(claims) or (self.evidence("fundamentals neutral", source="fundamental"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors),
        )


# ---------------------------------------------------------------------------
# Quantitative Agent
# ---------------------------------------------------------------------------


@register_agent
class QuantAgent(BaseAgent):
    """Statistical / factor lens.

    Combines a momentum factor, a mean-reversion z-score, and a
    volatility-regime filter.  Disagrees with Technical on purpose:
    Quant looks for mean-reversion in high-vol regimes, momentum in
    low-vol regimes.
    """

    id = "quant"
    name = "Quantitative Strategist"
    kind = AgentKind.QUANT

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok or factors.rows < 30:
            return None

        claims = []
        score = 0.0
        high_vol = factors.annualised_vol > 0.45

        # Momentum factor (cross-sectional analogue — sign only here).
        mom = factors.momentum_20d
        if not high_vol:
            if mom > 0.03:
                score += 0.3
                claims.append(self.evidence(f"low-vol momentum factor {mom:+.2%}", source="quant", reference=f"{snapshot.symbol}:mom"))
            elif mom < -0.03:
                score -= 0.3
        else:
            # High-vol regime: look for mean reversion (RSI extreme)
            if factors.rsi_14 is not None:
                if factors.rsi_14 < 30:
                    score += 0.25
                    claims.append(self.evidence(f"high-vol mean-reversion (RSI {factors.rsi_14:.0f})", source="quant", reference=f"{snapshot.symbol}:rsi"))
                elif factors.rsi_14 > 70:
                    score -= 0.25

        # Bollinger position: near lower band -> +score, near upper -> -score
        if factors.bb_upper and factors.bb_lower and factors.bb_middle:
            width = factors.bb_upper - factors.bb_lower
            if width > 0:
                pos = (factors.latest_close - factors.bb_lower) / width
                if pos < 0.2:
                    score += 0.2
                    claims.append(self.evidence("price near Bollinger lower band", source="quant", reference=f"{snapshot.symbol}:bb"))
                elif pos > 0.8:
                    score -= 0.2
                    claims.append(self.evidence("price near Bollinger upper band", source="quant", reference=f"{snapshot.symbol}:bb"))

        # Volatility regime filter: avoid trading in extreme vol
        if factors.annualised_vol > 0.8:
            score *= 0.5
            claims.append(self.evidence(f"volatility regime filter applied ({factors.annualised_vol:.0%} ann.)", source="quant", reference=f"{snapshot.symbol}:vol"))

        score = max(-1.0, min(1.0, score))
        direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=f"quant score {score:+.2f} ({'high-vol' if high_vol else 'low-vol'} regime)",
            invalidation="regime change or factor decay",
            evidence=tuple(claims) or (self.evidence("quant factors neutral", source="quant"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors, disagreement_penalty=0.1 if high_vol else 0.0),
        )


# ---------------------------------------------------------------------------
# Macro Agent
# ---------------------------------------------------------------------------


@register_agent
class MacroAgent(BaseAgent):
    """Macro / regime lens — reads Prof. Aldric's regime from context."""

    id = "macro"
    name = "Macro Strategist"
    kind = AgentKind.MACRO

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok:
            return None
        regime = ctx.regime
        score = 0.0
        claims = []
        if regime == "bull":
            score += 0.25
            claims.append(self.evidence("macro regime: bull (risk-on)", source="macro", reference="regime:bull"))
        elif regime == "bear":
            score -= 0.25
            claims.append(self.evidence("macro regime: bear (risk-off)", source="macro", reference="regime:bear"))
        elif regime == "volatile":
            score -= 0.1
            claims.append(self.evidence("macro regime: volatile (defensive)", source="macro", reference="regime:volatile"))
        else:
            claims.append(self.evidence("macro regime: sideways", source="macro", reference="regime:sideways"))

        # High volatility reduces macro conviction
        if factors.annualised_vol > 0.6:
            score *= 0.5

        direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=f"macro score {score:+.2f} (regime={regime})",
            invalidation="regime change",
            evidence=tuple(claims),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors),
        )


# ---------------------------------------------------------------------------
# News Agent (sentiment) — no fabrication when no news feed is wired
# ---------------------------------------------------------------------------


@register_agent
class NewsAgent(BaseAgent):
    """News / sentiment lens.

    When no news research is available (the default), returns ``None`` —
    NEVER invents sentiment.  When the research engine populates
    ``ctx.research_cache['news:<symbol>']`` with a sentiment payload,
    this agent consumes it.
    """

    id = "news"
    name = "News & Sentiment Analyst"
    kind = AgentKind.NEWS

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok:
            return None
        news = ctx.research_cache.get(f"news:{snapshot.symbol}")
        if not news:
            return None
        sentiment = news.get("sentiment", "neutral")
        score = {"positive": 0.25, "negative": -0.25, "neutral": 0.0}.get(sentiment, 0.0)
        claims = [self.evidence(f"news sentiment: {sentiment}", source="news", reference=f"{snapshot.symbol}:news")]
        direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=f"news score {score:+.2f} (sentiment={sentiment})",
            invalidation="sentiment reversal",
            evidence=tuple(claims),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors),
        )


# ---------------------------------------------------------------------------
# Risk Agent — the sceptical one
# ---------------------------------------------------------------------------


@register_agent
class RiskAgent(BaseAgent):
    """Risk lens — votes AGAINST trades when tail risk is elevated.

    This agent is special: even when other specialists agree on a
    direction, the Risk Agent can vote against it because of drawdown,
    volatility, or concentration.  The orchestrator weights this
    agent's disagreement explicitly (it's the "disagreement_penalty"
    in the :class:`Confidence` formula).
    """

    id = "risk"
    name = "Risk Management Officer"
    kind = AgentKind.RISK

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok:
            return None
        claims = []
        score = 0.0  # risk agent's "score" is a risk penalty, not a direction

        if factors.annualised_vol > 0.6:
            claims.append(self.evidence(f"elevated volatility {factors.annualised_vol:.0%}", source="risk", reference=f"{snapshot.symbol}:vol"))
            score -= 0.3
        if factors.drawdown > 0.15:
            claims.append(self.evidence(f"drawdown from peak {factors.drawdown:.0%}", source="risk", reference=f"{snapshot.symbol}:dd"))
            score -= 0.3
        if ctx.portfolio_drawdown > 0.05:
            claims.append(self.evidence(f"portfolio already in {ctx.portfolio_drawdown:.0%} drawdown", source="risk", reference="portfolio:dd"))
            score -= 0.2

        # Risk agent's direction mirrors its score: a strong negative means
        # "do not take any new long position here".  It's NOT a short call —
        # the orchestrator interprets a Risk FLAT/SHORT signal as a veto
        # against new longs, never as an instruction to short.
        if score <= -0.3:
            direction = SignalDirection.FLAT  # veto on new longs
            thesis = f"risk veto: aggregate risk penalty {score:+.2f}"
        elif score >= 0.0:
            direction = SignalDirection.FLAT
            thesis = f"risk neutral: penalty {score:+.2f}"
        else:
            direction = SignalDirection.FLAT
            thesis = f"risk caution: penalty {score:+.2f}"

        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=thesis,
            invalidation="volatility/drawdown normalise",
            evidence=tuple(claims) or (self.evidence("risk profile acceptable", source="risk"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors, disagreement_penalty=min(1.0, abs(score))),
        )


# ---------------------------------------------------------------------------
# Data Validation Agent — the freshness cop
# ---------------------------------------------------------------------------


@register_agent
class DataValidationAgent(BaseAgent):
    """Checks data quality.  Returns FLAT + warning when data is sparse."""

    id = "data_validation"
    name = "Data Validation Agent"
    kind = AgentKind.DATA_VALIDATION

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok:
            return Recommendation(
                symbol=snapshot.symbol,
                direction=SignalDirection.FLAT,
                thesis="data unavailable — no opinion",
                invalidation="data becomes available",
                evidence=(self.evidence(f"data fetch failed: {snapshot.error}", source="data_validation", reference=snapshot.symbol),),
                agent_id=self.id,
                agent_kind=self.kind,
                confidence=self.confidence_from_factors(factors, disagreement_penalty=1.0),
            )
        claims = []
        penalty = 0.0
        if factors.rows < 60:
            claims.append(self.evidence(f"only {factors.rows} bars (need >=60)", source="data_validation", reference=f"{snapshot.symbol}:rows"))
            penalty += 0.5
        if factors.rows < 30:
            penalty += 0.5
        if snapshot.freshness_score < 0.5:
            claims.append(self.evidence(f"low freshness score {snapshot.freshness_score:.2f}", source="data_validation", reference=f"{snapshot.symbol}:freshness"))
            penalty += 0.3
        return Recommendation(
            symbol=snapshot.symbol,
            direction=SignalDirection.FLAT,
            thesis=f"data validation penalty {penalty:.2f}",
            invalidation="data quality improves",
            evidence=tuple(claims) or (self.evidence("data quality acceptable", source="data_validation"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors, disagreement_penalty=min(1.0, penalty)),
        )


# ---------------------------------------------------------------------------
# Market Monitor Agent — detects unusual activity
# ---------------------------------------------------------------------------


@register_agent
class MarketMonitorAgent(BaseAgent):
    """Detects unusual volume / volatility expansion."""

    id = "market_monitor"
    name = "Market Monitor Agent"
    kind = AgentKind.MARKET_MONITOR

    def analyze(
        self,
        snapshot: MarketSnapshot,
        factors: FactorSnapshot,
        ctx: AgentContext,
    ) -> Optional[Recommendation]:
        if not snapshot.ok or factors.rows < 30:
            return None
        claims = []
        score = 0.0
        if factors.volume_ratio_5_20 > 1.5:
            score += 0.2
            claims.append(self.evidence(f"unusual volume expansion (5d/20d {factors.volume_ratio_5_20:.2f}x)", source="market_monitor", reference=f"{snapshot.symbol}:vol"))
        if factors.up_day_volume_dominance > 0.65:
            score += 0.15
            claims.append(self.evidence(f"up-day volume dominance {factors.up_day_volume_dominance:.0%}", source="market_monitor", reference=f"{snapshot.symbol}:flow"))
        elif factors.up_day_volume_dominance < 0.35:
            score -= 0.15
            claims.append(self.evidence(f"down-day volume dominance {1 - factors.up_day_volume_dominance:.0%}", source="market_monitor", reference=f"{snapshot.symbol}:flow"))

        direction = SignalDirection.LONG if score >= 0.2 else (SignalDirection.SHORT if score <= -0.2 else SignalDirection.FLAT)
        return Recommendation(
            symbol=snapshot.symbol,
            direction=direction,
            thesis=f"monitor score {score:+.2f}",
            invalidation="volume normalises",
            evidence=tuple(claims) or (self.evidence("no unusual activity", source="market_monitor"),),
            agent_id=self.id,
            agent_kind=self.kind,
            confidence=self.confidence_from_factors(factors),
        )
