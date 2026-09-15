# -*- coding: utf-8 -*-
"""The default JEXI skill pack — five concrete, deterministic skills.

1. ``earnings_proximity`` — binary event awareness (yfinance calendar via
   the research cache; no invented dates).
2. ``volatility_regime`` — ATR-based hot/calm tape detection.
3. ``liquidity_check`` — dollar-volume adequacy for the intended size.
4. ``gap_risk`` — historical overnight-gap behaviour from the fetched bars.
5. ``correlation_guard`` — same-sector concentration against live holdings.

Each skill: applies cheaply, reads only data already fetched, and emits
evidence + risk flags + (optionally) a position-size scale.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from jexi_market.contracts import Evidence
from jexi_market.data import MarketSnapshot
from jexi_market.indicators import FactorSnapshot
from jexi_market.skills.base import Skill, SkillOutput

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Earnings proximity
# ---------------------------------------------------------------------------


class EarningsProximitySkill(Skill):
    id = "earnings_proximity"
    name = "Earnings proximity"

    def applies_to(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> bool:
        cache = getattr(ctx, "research_cache", None) or {}
        return any(k.startswith("calendar:") for k in cache)

    def run(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> SkillOutput:
        out = SkillOutput()
        cache = getattr(ctx, "research_cache", {}) or {}
        entry = cache.get(f"calendar:{factors.symbol}")
        days = None
        if isinstance(entry, dict):
            days = entry.get("days_to_earnings")
        if days is None:
            return out
        try:
            days = int(days)
        except (TypeError, ValueError):
            return out
        if days < 0:
            return out
        if days <= 5:
            out.risk_flags.append(f"Earnings land in {days} day(s) — binary event risk")
            out.size_scale = 0.5
            out.evidence.append(self._evidence(
                f"Earnings report within {days} day(s) (source: {entry.get('source', 'calendar')})",
                "calendar", 0.9,
            ))
            out.notes.append(f"earnings_in_days={days}")
        elif days <= 12:
            out.risk_flags.append(f"Earnings within {days} days — new entries carry event risk")
            out.size_scale = 0.8
            out.evidence.append(self._evidence(
                f"Earnings report in {days} days", "calendar", 0.8,
            ))
        else:
            out.notes.append(f"earnings_in_days={days} — clear of the event")
        return out


# ---------------------------------------------------------------------------
# 2. Volatility regime
# ---------------------------------------------------------------------------


class VolatilityRegimeSkill(Skill):
    id = "volatility_regime"
    name = "Volatility regime"

    def run(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> SkillOutput:
        out = SkillOutput()
        atr_pct = factors.atr_pct
        if atr_pct is None and factors.atr_14 and factors.latest_close:
            atr_pct = factors.atr_14 / factors.latest_close
        if not atr_pct:
            return out
        if atr_pct > 0.06:
            out.risk_flags.append(f"Hot tape: daily range {atr_pct:.1%} of price")
            out.size_scale = 0.6
            out.evidence.append(self._evidence(
                f"ATR is {atr_pct:.1%} of price — swings are large", "factors:atr_pct", 0.9,
            ))
        elif atr_pct < 0.015 and factors.bb_upper and factors.bb_middle and factors.bb_lower:
            width = (factors.bb_upper - factors.bb_lower) / factors.bb_middle if factors.bb_middle else 0
            if width < 0.06:
                out.notes.append("Volatility squeeze — expansion often follows; breakout triggers matter more than usual")
                out.evidence.append(self._evidence(
                    f"Bollinger width {width:.1%} with ATR {atr_pct:.1%} — volatility squeeze",
                    "factors:bb", 0.7,
                ))
        else:
            out.notes.append(f"Volatility normal (ATR {atr_pct:.1%})")
        return out


# ---------------------------------------------------------------------------
# 3. Liquidity check
# ---------------------------------------------------------------------------


class LiquiditySkill(Skill):
    id = "liquidity_check"
    name = "Liquidity check"

    MIN_DOLLAR_VOLUME = 5_000_000  # $5M/day to trade cleanly

    def applies_to(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> bool:
        df = getattr(snapshot, "df", None)
        return df is not None and {"close", "volume"}.issubset(set(df.columns))

    def run(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> SkillOutput:
        out = SkillOutput()
        df = snapshot.df
        tail = df.tail(20)
        dollar_vol = (tail["close"].astype(float) * tail["volume"].astype(float)).mean()
        if dollar_vol != dollar_vol:  # NaN
            return out
        if dollar_vol < self.MIN_DOLLAR_VOLUME:
            out.risk_flags.append(
                f"Thin liquidity: ~${dollar_vol/1e6:.1f}M/day traded — exits may slip"
            )
            out.size_scale = 0.5
            out.evidence.append(self._evidence(
                f"Average dollar volume ~${dollar_vol/1e6:.1f}M/day over 20 sessions",
                "market_data", 0.85,
            ))
        else:
            out.notes.append(f"Liquidity healthy (~${dollar_vol/1e6:.0f}M/day)")
        return out


# ---------------------------------------------------------------------------
# 4. Gap risk
# ---------------------------------------------------------------------------


class GapRiskSkill(Skill):
    id = "gap_risk"
    name = "Gap risk"

    def applies_to(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> bool:
        df = getattr(snapshot, "df", None)
        return df is not None and {"open", "close"}.issubset(set(df.columns)) and len(df) >= 30

    def run(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> SkillOutput:
        out = SkillOutput()
        df = snapshot.df
        prev_close = df["close"].shift(1)
        open_ = df["open"]
        gaps = ((open_ - prev_close) / prev_close).abs().dropna()
        if len(gaps) < 30:
            return out
        big_gap_freq = float((gaps > 0.03).mean())
        median_gap = float(gaps.median())
        if big_gap_freq > 0.20:
            out.risk_flags.append(
                f"Gappy stock: {big_gap_freq:.0%} of sessions opened >3% away — stops can be jumped"
            )
            out.size_scale = 0.75
            out.evidence.append(self._evidence(
                f"{big_gap_freq:.0%} of last {len(gaps)} sessions gapped >3% at the open",
                "market_data", 0.85,
            ))
        else:
            out.notes.append(f"Gap behaviour normal (median open gap {median_gap:.2%})")
        return out


# ---------------------------------------------------------------------------
# 5. Correlation / concentration guard
# ---------------------------------------------------------------------------


class CorrelationGuardSkill(Skill):
    id = "correlation_guard"
    name = "Correlation guard"

    def applies_to(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> bool:
        extras = getattr(ctx, "extras", None) or {}
        return bool(extras.get("held_symbols")) and bool(getattr(ctx, "research_cache", None))

    def run(self, snapshot: MarketSnapshot, factors: FactorSnapshot, ctx: Any) -> SkillOutput:
        out = SkillOutput()
        extras = getattr(ctx, "extras", {}) or {}
        cache = getattr(ctx, "research_cache", {}) or {}
        held = list(extras.get("held_symbols") or [])
        my_sector = cache.get(f"sector:{factors.symbol}")
        if not my_sector:
            return out
        same_sector: List[str] = []
        for sym in held:
            if sym == factors.symbol:
                continue
            if cache.get(f"sector:{sym}") == my_sector:
                same_sector.append(sym)
        if same_sector:
            out.risk_flags.append(
                f"Already holding {', '.join(same_sector[:3])} in the same sector ({my_sector}) — stacking exposure"
            )
            out.size_scale = 0.7
            out.evidence.append(self._evidence(
                f"{factors.symbol} shares the {my_sector} sector with open position(s): "
                f"{', '.join(same_sector[:3])}",
                "portfolio", 0.9,
            ))
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_default_skills() -> List[Skill]:
    return [
        EarningsProximitySkill(),
        VolatilityRegimeSkill(),
        LiquiditySkill(),
        GapRiskSkill(),
        CorrelationGuardSkill(),
    ]
