# -*- coding: utf-8 -*-
"""Tests for the v0.5 agent stack: debate, risk team, LLM arbiter,
skills pack, memory reflection, and orchestrator wiring."""

import json

import pandas as pd
import pytest

from jexi_market.agents import AgentContext
from jexi_market.agents.debate import DebateStage, DebatePoint, debate_evidence
from jexi_market.agents.llm_arbiter import LLMArbiter, ArbiterVerdict
from jexi_market.agents.risk_team import RiskTeam
from jexi_market.config import MarketConfig
from jexi_market.contracts import (
    AgentKind,
    Confidence,
    Decision,
    MarketRegime,
    Recommendation,
    RiskEnvelope,
    SignalDirection,
)
from jexi_market.data import MarketSnapshot, load_synthetic_frame
from jexi_market.indicators import FactorSnapshot, compute_factors
from jexi_market.memory import PerformanceMemory
from jexi_market.orchestrator import MarketBoss
from jexi_market.risk import PortfolioState
from jexi_market.skills import SkillRegistry, build_default_skills
from jexi_market.skills.pack import (
    CorrelationGuardSkill,
    EarningsProximitySkill,
    GapRiskSkill,
    LiquiditySkill,
    VolatilityRegimeSkill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bull_factors(symbol="BULL") -> FactorSnapshot:
    return FactorSnapshot(
        symbol=symbol, rows=120, latest_close=110.0,
        sma_50=100.0, rsi_14=55.0, macd_hist=0.4, macd_line=1.0, macd_signal=0.6,
        momentum_20d=0.05, annualised_vol=0.3, atr_14=2.0, atr_pct=0.018,
        volume_ratio_5_20=1.3, drawdown=-0.02,
    )


def _bear_factors(symbol="BEAR") -> FactorSnapshot:
    return FactorSnapshot(
        symbol=symbol, rows=120, latest_close=90.0,
        sma_50=100.0, rsi_14=78.0, macd_hist=-0.5, macd_line=0.5, macd_signal=1.0,
        momentum_20d=-0.06, annualised_vol=0.75, atr_14=5.0, atr_pct=0.055,
        volume_ratio_5_20=0.8, drawdown=-0.15,
    )


def _rec(agent_id, direction, *, agreement=0.7, kind=AgentKind.TECHNICAL, thesis=""):
    return Recommendation(
        symbol="TEST",
        direction=direction,
        thesis=thesis or f"{agent_id} case",
        agent_id=agent_id,
        agent_kind=kind,
        confidence=Confidence(
            agreement=agreement, data_freshness=0.9, evidence_count=2,
        ),
    )


def _decision(direction=SignalDirection.LONG, *, fraction=0.15, confidence=None):
    return Decision(
        symbol="TEST",
        direction=direction,
        confidence=confidence or Confidence(agreement=0.75, data_freshness=0.9, evidence_count=4),
        entry=100.0, stop_loss=95.0, take_profit=112.0,
        position_fraction=fraction, risk_per_trade=0.02,
        thesis="test trade",
    )


def _portfolio(**overrides) -> PortfolioState:
    base = dict(
        equity=100_000.0, cash=60_000.0, positions_value=40_000.0,
        open_positions=3, sector_exposure={}, daily_pnl=0.0,
        peak_equity=100_000.0, paper_trading_days=40, live_trading_active=False,
    )
    base.update(overrides)
    return PortfolioState(**base)


# ---------------------------------------------------------------------------
# Debate
# ---------------------------------------------------------------------------


class TestDebate:
    def test_bull_wins_on_uptrend(self):
        v = DebateStage().run(
            symbol="BULL",
            recommendations=[_rec("technical", SignalDirection.LONG)],
            factors=_bull_factors(),
            regime=MarketRegime.BULL,
            proposed_direction=SignalDirection.LONG,
        )
        assert v.winner == "bull"
        assert v.confidence_adjustment > 0
        assert v.confidence_adjustment <= 0.10
        assert v.bull_points and "debate" in v.summary.lower() or "won" in v.summary.lower()

    def test_bear_wins_on_downtrend(self):
        v = DebateStage().run(
            symbol="BEAR",
            recommendations=[_rec("technical", SignalDirection.SHORT)],
            factors=_bear_factors(),
            regime=MarketRegime.BEAR,
            proposed_direction=SignalDirection.SHORT,
        )
        assert v.winner == "bear"
        assert v.confidence_adjustment > 0

    def test_debate_against_proposal_gives_negative(self):
        v = DebateStage().run(
            symbol="BEAR",
            recommendations=[],
            factors=_bear_factors(),
            regime=MarketRegime.BEAR,
            proposed_direction=SignalDirection.LONG,
        )
        assert v.winner == "bear"
        assert v.confidence_adjustment < 0

    def test_split_when_balanced(self):
        # Neutral factors: both sides get similar small material
        f = FactorSnapshot(symbol="FLAT", rows=120, latest_close=100.0, rsi_14=52.0)
        v = DebateStage().run(
            symbol="FLAT",
            recommendations=[
                _rec("a", SignalDirection.LONG, agreement=0.5),
                _rec("b", SignalDirection.SHORT, agreement=0.5),
            ],
            factors=f,
            regime=MarketRegime.SIDEWAYS,
            proposed_direction=SignalDirection.FLAT,
        )
        assert v.confidence_adjustment == 0.0

    def test_adjustment_hard_capped(self):
        stage = DebateStage()
        assert stage._adjustment("bull", 0.99, SignalDirection.LONG) <= 0.10
        assert stage._adjustment("bear", 0.99, SignalDirection.LONG) >= -0.10

    def test_points_capped_per_side(self):
        v = DebateStage().run(
            symbol="BULL",
            recommendations=[
                _rec(f"agent{i}", SignalDirection.LONG) for i in range(10)
            ],
            factors=_bull_factors(),
            regime=MarketRegime.BULL,
            proposed_direction=SignalDirection.LONG,
        )
        assert len(v.bull_points) <= DebateStage.MAX_POINTS_PER_SIDE

    def test_debate_evidence_labels(self):
        v = DebateStage().run(
            symbol="BULL",
            recommendations=[_rec("technical", SignalDirection.LONG)],
            factors=_bull_factors(),
            regime=MarketRegime.BULL,
            proposed_direction=SignalDirection.LONG,
        )
        evs = debate_evidence(v)
        claims = [e.claim for e in evs]
        assert any(c.startswith("[bull]") for c in claims)
        assert all(e.source == "debate" for e in evs)


# ---------------------------------------------------------------------------
# Risk team
# ---------------------------------------------------------------------------


class TestRiskTeam:
    def test_healthy_trade_approved(self):
        v = RiskTeam().review(
            _decision(), _portfolio(), _bull_factors(), RiskEnvelope(),
        )
        assert v.veto is False
        assert v.n_approve >= 2
        assert v.position_scale >= 0.75

    def test_veto_when_neutral_and_conservative_reject(self):
        # Breached drawdown halt + daily loss + low confidence
        p = _portfolio(equity=88_000.0, peak_equity=100_000.0, daily_pnl=-5_000.0)
        weak_conf = Confidence(agreement=0.2, data_freshness=0.5, evidence_count=1)
        v = RiskTeam().review(
            _decision(confidence=weak_conf, fraction=0.30),
            p, _bear_factors(), RiskEnvelope(),
        )
        assert v.veto is True
        assert v.position_scale == 0.0

    def test_one_rejection_trims(self):
        # Only the conservative reviewer objects (elevated vol, chunky size)
        v = RiskTeam().review(
            _decision(fraction=0.30), _portfolio(), _bear_factors(), RiskEnvelope(),
        )
        assert 0.5 <= v.position_scale <= 1.0
        assert v.veto is False

    def test_earnings_concern_surfaces(self):
        v = RiskTeam().review(
            _decision(), _portfolio(), _bull_factors(), RiskEnvelope(),
            earnings_in_days=2,
        )
        cons = [r for r in v.reviewers if r.reviewer == "conservative"][0]
        assert any("Earnings" in c for c in cons.concerns)

    def test_flat_direction_is_noop(self):
        v = RiskTeam().review(
            _decision(direction=SignalDirection.FLAT), _portfolio(), _bull_factors(), RiskEnvelope(),
        )
        assert v.veto is False

    def test_reviewers_are_real_names(self):
        v = RiskTeam().review(_decision(), _portfolio(), _bull_factors(), RiskEnvelope())
        names = {r.reviewer for r in v.reviewers}
        assert names == {"aggressive", "neutral", "conservative"}


# ---------------------------------------------------------------------------
# LLM arbiter
# ---------------------------------------------------------------------------


class TestLLMArbiter:
    def test_disabled_without_key(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                  "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("JEXI_LLM_ARBITER", "auto")
        assert LLMArbiter.enabled() is False

    def test_disabled_by_flag(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("JEXI_LLM_ARBITER", "off")
        assert LLMArbiter.enabled() is False

    def test_flat_proposal_skips_call(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        a = LLMArbiter()
        called = []
        a.transport = lambda *args: called.append(args) or (200, "{}")
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.FLAT,
        )
        assert v.verdict == "no_opinion"
        assert not called

    def test_valid_response_is_used(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "verdict": "agree", "direction_hint": "long",
                "confidence_delta": 0.08, "reason": "Evidence is coherent.",
            })}}],
        })

        a = LLMArbiter()
        seen = {}

        def fake_transport(endpoint, headers, body_bytes, timeout):
            seen["endpoint"] = endpoint
            seen["auth"] = headers.get("Authorization", "")
            return (200, body)

        a.transport = fake_transport
        v = a.arbitrate(
            symbol="T",
            factors_summary={"latest_close": 100.0},
            recommendations=[_rec("technical", SignalDirection.LONG)],
            proposed_direction=SignalDirection.LONG,
        )
        assert v.ok is True
        assert v.verdict == "agree"
        assert v.confidence_delta == 0.08
        assert "api.openai.com" in seen["endpoint"]
        assert seen["auth"] == "Bearer test-key"

    def test_delta_hard_clamped(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "verdict": "agree", "direction_hint": "long",
                "confidence_delta": 0.9, "reason": "overconfident model",
            })}}],
        })
        a = LLMArbiter()
        a.transport = lambda *args: (200, body)
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.LONG,
        )
        assert v.confidence_delta == 0.15

    def test_malformed_response_never_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        a = LLMArbiter()
        a.transport = lambda *args: (200, "not json at all {{{")
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.LONG,
        )
        assert v.ok is False
        assert v.error

    def test_http_error_never_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        a = LLMArbiter()
        a.transport = lambda *args: (500, "server error")
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.LONG,
        )
        assert v.ok is False

    def test_prose_wrapped_json_is_extracted(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        inner = json.dumps({"verdict": "disagree", "direction_hint": "flat",
                            "confidence_delta": -0.1, "reason": "weak case"})
        body = json.dumps({"choices": [{"message": {"content": f"Sure!\n```json\n{inner}\n```"}}]})
        a = LLMArbiter()
        a.transport = lambda *args: (200, body)
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.LONG,
        )
        assert v.ok is True
        assert v.verdict == "disagree"

    def test_gemini_provider_shape(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "gkey")
        seen = {}
        body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": json.dumps({
                "verdict": "agree", "direction_hint": "short",
                "confidence_delta": 0.05, "reason": "ok"})}]}}],
        })

        def transport(endpoint, headers, body_bytes, timeout):
            seen["endpoint"] = endpoint
            seen["key"] = headers.get("x-goog-api-key", "")
            return (200, body)

        a = LLMArbiter()
        a.transport = transport
        v = a.arbitrate(
            symbol="T", factors_summary={}, recommendations=[],
            proposed_direction=SignalDirection.SHORT,
        )
        assert v.ok is True
        assert "generativelanguage" in seen["endpoint"]
        assert seen["key"] == "gkey"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class TestSkills:
    def _ctx(self, research_cache=None, held=None):
        return AgentContext(
            research_cache=research_cache or {},
            extras={"held_symbols": held or []},
        )

    def _snap(self, df):
        return MarketSnapshot(symbol="TEST", ok=True, df=df, provider="synthetic",
                              rows=len(df), freshness_score=1.0)

    def test_earnings_proximity_flags(self):
        skill = EarningsProximitySkill()
        ctx = self._ctx({"calendar:TEST": {"days_to_earnings": 2, "source": "yfinance"}})
        out = skill.run(self._snap(pd.DataFrame()), _bull_factors("TEST"), ctx)
        assert out.risk_flags and out.size_scale == 0.5

    def test_earnings_dormant_when_unknown(self):
        skill = EarningsProximitySkill()
        ctx = self._ctx({})
        assert skill.applies_to(self._snap(pd.DataFrame()), _bull_factors("TEST"), ctx) is False

    def test_volatility_hot_tape(self):
        f = _bull_factors("TEST")
        f = FactorSnapshot(**{**f.__dict__, "atr_pct": 0.09})
        out = VolatilityRegimeSkill().run(self._snap(pd.DataFrame()), f, self._ctx())
        assert out.risk_flags and out.size_scale == 0.6

    def test_volatility_squeeze_note(self):
        f = FactorSnapshot(symbol="TEST", rows=120, latest_close=100.0,
                           atr_pct=0.012, bb_upper=101.0, bb_middle=100.0, bb_lower=99.0)
        out = VolatilityRegimeSkill().run(self._snap(pd.DataFrame()), f, self._ctx())
        assert out.size_scale is None
        assert any("squeeze" in n for n in out.notes)

    def test_liquidity_thin(self):
        df = pd.DataFrame({"close": [1.0] * 25, "volume": [2_000.0] * 25})
        out = LiquiditySkill().run(self._snap(df), _bull_factors("TEST"), self._ctx())
        assert out.risk_flags and out.size_scale == 0.5

    def test_gap_risk_flags_gappy_stock(self):
        rows = 40
        closes = [100.0] * rows
        opens = [103.5 if i % 2 == 0 else 100.0 for i in range(rows)]  # 50% big gaps
        df = pd.DataFrame({"open": opens, "close": closes})
        out = GapRiskSkill().run(self._snap(df), _bull_factors("TEST"), self._ctx())
        assert out.risk_flags and out.size_scale == 0.75

    def test_correlation_guard_same_sector(self):
        ctx = self._ctx(
            {"sector:TEST": "Technology", "sector:HELD": "Technology"},
            held=["HELD"],
        )
        out = CorrelationGuardSkill().run(self._snap(pd.DataFrame()), _bull_factors("TEST"), ctx)
        assert out.risk_flags and out.size_scale == 0.7

    def test_registry_clamps_and_folds(self):
        # Hot tape + thin liquidity together -> global scale is the min, clamped
        df = pd.DataFrame({"close": [1.0] * 25, "volume": [1_000.0] * 25})
        f = FactorSnapshot(symbol="TEST", rows=120, latest_close=1.0, atr_pct=0.09)
        report = SkillRegistry(build_default_skills()).run_all(self._snap(df), f, self._ctx())
        assert "volatility_regime" in report.ran
        assert report.size_scale is not None and report.size_scale <= 0.6
        assert report.evidence  # evidence collected

    def test_skills_list(self):
        assert [s.id for s in build_default_skills()] == [
            "earnings_proximity", "volatility_regime",
            "liquidity_check", "gap_risk", "correlation_guard",
        ]


# ---------------------------------------------------------------------------
# Memory reflection (FinMem pattern)
# ---------------------------------------------------------------------------


class TestReflection:
    def _memory_with_history(self):
        mem = PerformanceMemory(":memory:")
        for i in range(3):
            d = _decision()
            d = Decision(
                symbol=f"S{i}", direction=SignalDirection.LONG,
                confidence=d.confidence, entry=100.0, stop_loss=95.0,
                position_fraction=0.1,
                supporting_agents=("bad_agent",),
                opposing_agents=(),
            )
            mem.record_decision(d)
            mem.close_trade(
                d.decision_id, exit_price=90.0, pnl_pct=-0.10,
                exit_reason="stop", agents_correct=["market_monitor"],
                agents_wrong=["bad_agent"],
            )
        return mem

    def test_reflection_flags_drifting_agent(self):
        mem = self._memory_with_history()
        out = mem.reflect()
        assert out["n_trades"] == 3
        assert out["win_rate"] == 0.0
        assert any("bad_agent" in lesson for lesson in out["lessons"])

    def test_reflection_empty_history(self):
        mem = PerformanceMemory(":memory:")
        out = mem.reflect()
        assert out == {"lessons": [], "n_trades": 0}


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------


def _make_synthetic_snapshot(symbol="SYNTH", rows=120, drift=0.002) -> MarketSnapshot:
    seed = sum(bytearray(symbol.encode("utf-8"))) % 1000
    df = load_synthetic_frame(symbol, days=rows, seed=seed)
    df["close"] = df["close"] * (1.0 + drift * df.index)
    df["high"] = df["close"] * 1.01
    df["low"] = df["close"] * 0.99
    df["open"] = df["close"] * 0.999
    return MarketSnapshot(symbol=symbol, ok=True, df=df, provider="synthetic",
                          rows=rows, freshness_score=1.0)


class TestOrchestratorWiring:
    def test_run_result_carries_all_stages(self, monkeypatch):
        config = MarketConfig()
        config.ntfy_url = ""
        boss = MarketBoss(config, enable_enrichment=False)
        snap = _make_synthetic_snapshot("AAPL", rows=120, drift=0.003)
        monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

        result = boss.analyze_symbol("AAPL", days=120)
        assert result.error is None
        assert result.decision is not None
        # v0.5 stages all present
        assert result.debate is not None
        assert "winner" in result.debate
        assert result.risk_team is not None
        assert len(result.risk_team["reviewers"]) == 3
        assert result.skills is not None
        assert "volatility_regime" in result.skills["ran"]

    def test_debate_evidence_in_decision(self, monkeypatch):
        config = MarketConfig()
        config.ntfy_url = ""
        boss = MarketBoss(config, enable_enrichment=False)
        snap = _make_synthetic_snapshot("MSFT", rows=120, drift=0.004)
        monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

        result = boss.analyze_symbol("MSFT", days=120)
        d = result.decision
        assert d is not None
        if result.debate["winner"] != "split":
            claims = [e.claim for e in d.evidence]
            assert any(c.startswith("[bull]") or c.startswith("[bear]") for c in claims)

    def test_risk_team_can_scale_fraction(self, monkeypatch):
        config = MarketConfig()
        config.ntfy_url = ""
        boss = MarketBoss(config, enable_enrichment=False)
        snap = _make_synthetic_snapshot("NVDA", rows=120, drift=0.003)
        monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

        result = boss.analyze_symbol("NVDA", days=120)
        assert result.risk_team is not None
        scale = result.risk_team["position_scale"]
        assert 0.0 <= scale <= 1.0

    def test_arbiter_absent_without_key(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                  "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        config = MarketConfig()
        config.ntfy_url = ""
        boss = MarketBoss(config, enable_enrichment=False)
        snap = _make_synthetic_snapshot("TSLA", rows=120, drift=0.002)
        monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

        result = boss.analyze_symbol("TSLA", days=120)
        assert result.arbiter is None

    def test_skills_risk_flags_reach_decision_risks(self, monkeypatch):
        config = MarketConfig()
        config.ntfy_url = ""
        boss = MarketBoss(config, enable_enrichment=False)
        snap = _make_synthetic_snapshot("AMD", rows=120, drift=0.02)
        monkeypatch.setattr(boss.data_client, "get_daily", lambda symbol, days=120, **kw: snap)

        result = boss.analyze_symbol("AMD", days=120)
        assert result.decision is not None
        assert result.skills is not None
        # If skills raised flags, they must appear in the decision's risks
        for flag in result.skills["risk_flags"]:
            assert any(flag in r for r in result.decision.risks)
