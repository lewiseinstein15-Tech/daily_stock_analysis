# -*- coding: utf-8 -*-
"""Offline tests for the J.E.X.I. pilot (no network; `pytest -m "not network"`).

Covers: persona registry load/validation, metrics math, specialist direction
on synthetic frames, long+short papersim, regime classifier, execution sizing,
and the self-improvement loop against fiducial synthetic data.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.jexi.loop import JexiLearningLoop
from src.jexi.metrics import (
    compute_max_drawdown,
    compute_sharpe,
    scenario_metrics_snapshot,
    total_return,
    win_rate,
)
from src.jexi.notify import JexiNotifier
from src.jexi.orchestrator import (
    JexiBossAgent,
    RegimeAssessment,
    RegimeClassifier,
    SterlingExecutionOptimiser,
)
from src.jexi.papersim import SignalPlan, simulate_plans
from src.jexi.persona import PersonaRegistry, get_persona_registry
from src.jexi.specialist import analyze_stock_with_persona


def make_frame(closes, code="X") -> pd.DataFrame:
    """Build a OHLCV frame from a close price series with deterministic dates."""
    closes = [float(c) for c in closes]
    dates = pd.bdate_range("2014-01-02", periods=len(closes))
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.01 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.99 for o, c in zip(opens, closes)]
    volume = [10_000 + i * 3 for i in range(len(closes))]
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volume,
        },
        index=range(len(closes)),
    )


class FakeFetcher:
    def __init__(self, frames):
        self.frames = frames

    def get_daily_data(self, code, days=None, start_date=None, end_date=None):
        return self.frames.get(code, make_frame([100.0] * 120)), "fake"


class StubConfig:
    jexi_risk_per_trade = 0.02
    jexi_max_position_fraction = 0.25
    jexi_max_iterations = 1
    jexi_target_win_rate = 0.55
    jexi_target_sharpe = 1.2
    jexi_target_max_drawdown = 0.15
    jexi_target_min_total_return = 0.05
    jexi_ntfy_url = None
    jexi_ntfy_server = None
    jexi_ntfy_topic = "jexi_reports"
    jexi_ntfy_token = None
    ntfy_url = None
    ntfy_token = None


# ---------------------------------------------------------------------------
# persona registry
# ---------------------------------------------------------------------------


class TestPersonaRegistry:
    def test_all_fifty_specialists_load(self):
        registry = get_persona_registry()
        specialists = registry.specialists()
        assert len(specialists) == 50
        ids = [p.id for p in specialists]
        assert len(ids) == len(set(ids)), "duplicate persona ids"

    def test_leadership_bundle(self):
        registry = get_persona_registry()
        ids = [p.id for p in registry.leadership.all]
        assert ids == ["jexi", "thorne", "sterling"]

    @staticmethod
    def _registry_with(path, specialists_yaml) -> PersonaRegistry:
        yaml = "leadership:\n  jexi: {name: Jexi}\n  thorne: {name: Thorne}\n  sterling: {name: Sterling}\n"
        yaml += "specialists:\n" + specialists_yaml
        path.write_text(yaml, encoding="utf-8")
        return PersonaRegistry(path)

    def test_validation_rejects_unknown_tilt(self, tmp_path):
        bad = "  - {id: x, name: X, role: r, tilt: astrology, brief: b}\n"
        with pytest.raises(ValueError):
            self._registry_with(tmp_path / "bad.yaml", bad).load()

    def test_validation_rejects_unknown_tool(self, tmp_path):
        bad = "  - {id: x, name: X, role: r, tilt: quant, brief: b, tools: [no_such_tool]}\n"
        with pytest.raises(ValueError):
            self._registry_with(tmp_path / "bad.yaml", bad).load()


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_total_return_and_drawdown(self):
        equity = [100.0, 110.0, 121.0, 108.0]
        assert abs(total_return(equity) - 0.08) < 1e-9
        assert abs(compute_max_drawdown(equity) - (121.0 - 108.0) / 121.0) < 1e-9

    def test_sharpe_flat_series_is_zero(self):
        assert compute_sharpe([0.1, 0.1, 0.1]) == 0.0

    def test_win_rate(self):
        trades = [
            {"pnl_pct": 0.5, "reason": "take_profit"},
            {"pnl_pct": -0.2, "reason": "stop_loss"},
            {"pnl_pct": 0.1, "reason": "stop_loss"},
            {"pnl_pct": None, "reason": "open"},
        ]
        assert win_rate(trades) == 2 / 3

    def test_snapshot_packages_targets(self):
        metrics = scenario_metrics_snapshot([100.0, 110.0], [{"pnl_pct": 0.1}])
        assert set(metrics) >= {"win_rate", "sharpe", "max_drawdown", "total_return", "n_trades"}


# ---------------------------------------------------------------------------
# specialists on synthetic frames
# ---------------------------------------------------------------------------


class TestSpecialists:
    def test_momentum_tilt_bull_frame(self):
        registry = get_persona_registry()
        bull = make_frame([100 * (1 + 0.02 * i) for i in range(120)])
        ops = [
            analyze_stock_with_persona(p, bull)
            for p in registry.specialists()
            if p.tilt == "momentum"
        ]
        assert ops
        assert all(op.signal in ("long", "flat") for op in ops)          # no shorts in a bull
        assert sum(op.signal == "long" for op in ops) >= len(ops) * 0.5  # majority long

    def test_bear_frame_not_overweight_bull(self):
        registry = get_persona_registry()
        bear = make_frame([100 * (1 - 0.02 * i) for i in range(120)])
        longish = sum(1 for p in registry.specialists() if analyze_stock_with_persona(p, bear).signal == "long")
        assert longish <= len(registry.specialists()) * 0.4

    def test_opinion_dict_roundtrip(self):
        registry = get_persona_registry()
        frame = make_frame([100.0] * 80)
        d = analyze_stock_with_persona(registry.specialists()[0], frame).to_dict()
        assert d["signal"] in ("long", "flat", "short")


# ---------------------------------------------------------------------------
# papersim (long + short)
# ---------------------------------------------------------------------------


class TestPapersim:
    def test_long_and_short_both_trade(self):
        ups = make_frame([100 * (1 + 0.01 * i) for i in range(40)])
        downs = make_frame([100 * (1 - 0.01 * i) for i in range(40)])
        plans = [
            SignalPlan(code="UP", name="bo", signal="long", confidence=0.9),
            SignalPlan(code="DOWN", name="be", signal="short", confidence=0.9),
        ]
        frames = {"UP": ups, "DOWN": downs}
        sim = simulate_plans(plans, frames, risk_per_trade=0.02, max_position_fraction=0.25)
        up_trades = [t for t in sim.trades if t.code == "UP"]
        down_trades = [t for t in sim.trades if t.code == "DOWN"]
        assert up_trades and down_trades
        assert all(t.direction == "long" for t in up_trades)
        assert all(t.direction == "short" for t in down_trades)
        assert any(t.pnl_pct > 0 for t in up_trades)
        assert any(t.pnl_pct > 0 for t in down_trades)

    def test_position_fraction_capped(self):
        frame = make_frame([100 * (1 + 0.005 * i) for i in range(40)])
        plans = [SignalPlan(code="UP", name="x", signal="long", confidence=0.9, stop_loss_pct=0.02)]
        sim = simulate_plans(plans, {"UP": frame}, risk_per_trade=0.02, max_position_fraction=0.25)
        assert sim.equity_series
        assert all(v > 0 for v in sim.equity_series)

    def test_short_stop_loss_is_above_entry(self):
        frame = make_frame([100 * (1 - 0.01 * i) for i in range(40)])
        plans = [SignalPlan(code="DN", name="x", signal="short", confidence=0.9, stop_loss_pct=0.05, take_profit_pct=0.03)]
        sim = simulate_plans(plans, {"DN": frame}, risk_per_trade=0.02)
        assert sim.trades
        first = sim.trades[0]
        assert first.reason == "take_profit"  # down-frame with tight 3% profit target
        assert first.exit_price < first.entry_price


# ---------------------------------------------------------------------------
# regime classifier & execution optimiser
# ---------------------------------------------------------------------------


class TestRegimeAndExecution:
    def test_bull_classification(self):
        frame = make_frame([100 * (1 + 0.002 * i) for i in range(200)])
        assessment = RegimeClassifier().classify(frame)
        assert assessment.regime in ("bull", "sideways")
        assert isinstance(assessment, RegimeAssessment)

    def test_volatile_classification(self):
        closes = [100.0]
        for _ in range(200):
            closes.append(closes[-1] * (1.0 + (0.12 if _ % 2 else -0.10)))
        frame = make_frame(closes)
        assessment = RegimeClassifier().classify(frame)
        assert assessment.regime == "volatile"

    def test_sizing_respects_risk_and_cap(self):
        optimiser = SterlingExecutionOptimiser()
        out = optimiser.optimise(
            SignalPlan(code="X", name="x", signal="long", confidence=0.8),
            risk_per_trade=0.02,
            max_position_fraction=0.25,
            annualised_vol=0.3,
        )
        assert out.position_fraction <= 0.25

    def test_high_vol_halves_size(self):
        optimiser = SterlingExecutionOptimiser()
        low = optimiser.optimise(
            SignalPlan(code="X", name="x", signal="long", confidence=0.8),
            annualised_vol=0.2,
        )
        high = optimiser.optimise(
            SignalPlan(code="X", name="x", signal="long", confidence=0.8),
            annualised_vol=0.5,
        )
        assert low.position_fraction > 0
        assert high.position_fraction <= low.position_fraction * 0.55


# ---------------------------------------------------------------------------
# end-to-end loop (offline, synthetic data)
# ---------------------------------------------------------------------------


class TestLearningLoop:
    def _make_agent(self) -> JexiBossAgent:
        config = StubConfig()
        up = [100.0]
        down = [100.0]
        side = [100.0]
        vol = [100.0]
        for i in range(2400):
            up.append(up[-1] * 1.002)
            down.append(down[-1] * 0.998)
            side.append(side[-1] + 5 * math.sin(i / 10))
            vol.append(vol[-1] * (1.04 if i % 2 else 0.96))
        frames = {
            "UP": make_frame(up),
            "DN": make_frame(down),
            "SIDE": make_frame(side),
            "VOL": make_frame(vol),
        }
        return JexiBossAgent(
            config=config,
            notifier=JexiNotifier(None),
            fetcher=FakeFetcher(frames),
        )

    def test_runs_and_keeps_weight_bounds(self, tmp_path):
        agent = self._make_agent()
        loop = JexiLearningLoop(
            agent,
            ticker_lists={
                "bull": ["UP"],
                "bear": ["DN"],
                "sideways": ["SIDE"],
                "volatile": ["VOL"],
            },
            max_iterations=2,
            targets={
                "win_rate": 0.3,
                "sharpe": 0.0,
                "max_drawdown": 0.6,
                "min_total_return": -0.3,
            },
        )
        loop.journal_dir = tmp_path
        result = loop.run(stop_on_first_pass=False)
        assert result.iterations
        for weighting in agent.adaptive_weights.values():
            assert 0.2 <= weighting <= 3.0
        assert tmp_path.joinpath("last_loop.json").exists()

    def test_map_invariant_code_matches(self):
        agent = self._make_agent()
        loop = JexiLearningLoop(agent, ticker_lists={"bull": ["UP"]})
        assert "UP" in loop.ticker_lists["bull"]


# ---------------------------------------------------------------------------
# research backend (offline: parsing, blending, caching)
# ---------------------------------------------------------------------------


class TestResearchBackend:
    def test_resolve_off_when_unconfigured(self):
        from src.jexi.research import RESEARCH_OFF, resolve_research_backend

        assert resolve_research_backend(StubConfig(), explicit=None) == RESEARCH_OFF
        assert resolve_research_backend(StubConfig(), explicit="off") == RESEARCH_OFF

    def test_parse_opinion_extracts_json(self):
        from src.jexi.research import _parse_opinion

        opinion = _parse_opinion(
            'Some preamble\n{"direction":"long","conviction":0.82,"rationale":"r","risk":"rw"}\ntrailing',
            "opencode_cli",
            model="test",
        )
        assert opinion is not None and opinion.ok
        assert opinion.direction == "long"
        assert abs(opinion.conviction - 0.82) < 1e-9
        assert opinion.backend == "opencode_cli"

    def test_parse_opinion_rejects_junk(self):
        from src.jexi.research import _parse_opinion

        assert _parse_opinion("", "opencode_cli") is None
        assert _parse_opinion("not json at all", "opencode_cli") is None
        assert _parse_opinion('{"direction":"long","conviction":99}', "opencode_cli") is None

    def test_research_blends_into_opinion(self, monkeypatch):
        from src.jexi.research import ResearchOpinion
        from src.jexi.specialist import analyze_stock_with_persona
        from src.jexi.persona import get_persona_registry

        persona = [p for p in get_persona_registry().specialists() if p.id == "vix"][0]
        frame = make_frame([100 * (1 + 0.005 * i) for i in range(40)])

        def fake_research(code, df, persona_, **kwargs):
            return ResearchOpinion(direction="long", conviction=0.9, rationale="research sees upside",
                                   backend="opencode_cli", model="test")

        monkeypatch.setattr("src.jexi.research.run_persona_research", fake_research)
        op = analyze_stock_with_persona(persona, frame, code="X", research="opencode_cli")
        assert op.research is not None
        assert op.research["direction"] == "long"
        assert op.signal == "long"
        assert any("research" in r for r in op.rationale)

    def test_research_failure_keeps_factor_opinion(self, monkeypatch):
        from src.jexi.specialist import analyze_stock_with_persona
        from src.jexi.persona import get_persona_registry

        persona = [p for p in get_persona_registry().specialists() if p.id == "vix"][0]
        frame = make_frame([100 * (1 + 0.005 * i) for i in range(40)])

        monkeypatch.setattr("src.jexi.research.run_persona_research", lambda *a, **k: None)
        baseline = analyze_stock_with_persona(persona, frame)
        with_research = analyze_stock_with_persona(persona, frame, code="X", research="opencode_cli")
        assert with_research.research is None
        assert abs(with_research.score - baseline.score) < 1e-9

    def test_research_cache_hits(self, monkeypatch):
        from src.jexi.research import run_persona_research
        from src.jexi.persona import get_persona_registry

        persona = [p for p in get_persona_registry().specialists() if p.id == "vix"][0]
        frame = make_frame([100.0] * 40)
        calls = {"n": 0}

        def fake_call(prompt_file, **kwargs):
            calls["n"] += 1
            return '{"direction":"short","conviction":0.7,"rationale":"r","risk":"w"}'

        monkeypatch.setattr("src.jexi.research._call_opencode", fake_call)
        cache = {}
        first = run_persona_research("X", frame, persona, backend="opencode_cli", cache=cache, bucket="b1")
        second = run_persona_research("X", frame, persona, backend="opencode_cli", cache=cache, bucket="b1")
        assert first is not None and second is not None
        assert calls["n"] == 1
        assert cache.keys()
        # different bucket -> new research call
        third = run_persona_research("X", frame, persona, backend="opencode_cli", cache=cache, bucket="b2")
        assert third is not None
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# papersim equity integrity (regression: no cumulative-gain re-multiply,
# one entry per rebalance, max-holding enforcement)
# ---------------------------------------------------------------------------


class TestPapersimIntegrity:
    def test_daily_delta_marking_not_cumulative(self):
        frame = make_frame([100.0, 110.0, 121.0, 133.1])[:4].reset_index(drop=True)
        plan = SignalPlan(code="X", signal="long", entry_price=100.0,
                          stop_loss_pct=0.5, take_profit_pct=0.9, max_holding_days=30)
        sim = simulate_plans([plan], {"X": frame}, risk_per_trade=0.02, max_position_fraction=0.25)
        # fraction = min(0.02/0.5, 0.25) = 0.04; equity compounds on the daily
        # delta (+10% each bar), never on the cumulative gain since entry.
        growth = sim.equity_series[-1] / sim.equity_series[0] - 1.0
        expected = (1.0 + 0.04 * 0.10) ** 3 - 1.0
        assert abs(growth - expected) < 1e-9
        # still marks-to-market at the end: no fictitious compounding
        assert growth < 0.5

    def test_single_entry_per_rebalance(self):
        # +15% on bar 2 would take profit; the same plan must NOT re-open on bar 3.
        frame = make_frame([100.0, 115.0, 100.0, 100.0])[:4].reset_index(drop=True)
        plan = SignalPlan(code="X", signal="long", entry_price=100.0,
                          stop_loss_pct=0.5, take_profit_pct=0.14)
        sim = simulate_plans([plan], {"X": frame}, risk_per_trade=0.02, max_position_fraction=0.25)
        assert len(sim.trades) == 1
        assert sim.trades[0].reason == "take_profit"

    def test_max_holding_days_enforced(self):
        frame = make_frame([100.0] * 10).reset_index(drop=True)
        plan = SignalPlan(code="X", signal="long", entry_price=100.0,
                          stop_loss_pct=0.5, take_profit_pct=0.95, max_holding_days=3)
        sim = simulate_plans([plan], {"X": frame}, risk_per_trade=0.02, max_position_fraction=0.25)
        assert len(sim.trades) == 1
        assert sim.trades[0].reason == "max_holding"
        assert sim.trades[0].days_held == 3


# ---------------------------------------------------------------------------
# rolling backtest (offline, synthetic, no look-ahead)
# ---------------------------------------------------------------------------


class TestRollingBacktest:
    def _agent(self) -> JexiBossAgent:
        bull = [100.0]
        for _ in range(2900):
            bull.append(bull[-1] * 1.0015)
        frames = {"UP": make_frame(bull, code="UP")}
        agent = JexiBossAgent(
            config=StubConfig(),
            notifier=JexiNotifier(None),
            fetcher=FakeFetcher(frames),
        )
        return agent

    def test_backtest_bounds_window_and_produces_metrics(self):
        agent = self._agent()
        loop = JexiLearningLoop(
            agent,
            ticker_lists={"bull": ["UP"]},
            max_iterations=1,
            rebalance_days=10,
            lookback_days=80,
            specialist_ids=["vix", "mac"],
        )
        outcome = loop.backtest_scenario("2020-11-01", "2021-12-31", ["UP"])
        for key in ("win_rate", "sharpe", "max_drawdown", "total_return", "n_trades"):
            assert key in outcome
        assert outcome["_n_chunks"] > 0
        assert outcome["pass_scenario"] in (True, False)
        # every trade must open inside the scenario window (no look-ahead)
        for trade in outcome["_trades"]:
            assert "2020-11-01" <= trade["entry_date"] <= "2021-12-31"

    def test_backtest_short_window_returns_zero_metrics(self):
        agent = self._agent()
        loop = JexiLearningLoop(
            agent,
            ticker_lists={"volatile": ["UP"]},
            max_iterations=1,
            rebalance_days=10,
            lookback_days=80,
            specialist_ids=["vix"],
        )
        outcome = loop.backtest_scenario("1990-01-01", "1990-01-10", ["UP"])
        assert outcome["n_trades"] == 0
        assert outcome["pass_scenario"] is False

    def test_adapt_moves_weights_by_persona_credit(self):
        agent = JexiBossAgent(
            config=StubConfig(),
            notifier=JexiNotifier(None),
            fetcher=FakeFetcher({"UP": make_frame([100.0] * 120)}),
        )
        loop = JexiLearningLoop(agent, ticker_lists={"bull": ["UP"]}, max_iterations=1)
        before_vix = agent.adaptive_weights["vix"]
        before_mac = agent.adaptive_weights["mac"]
        before_za = agent.adaptive_weights["za"]
        log = loop._adapt("bull", {"_persona_credit": {"vix": 1.0, "mac": -0.5}}, 1)
        assert agent.adaptive_weights["vix"] > before_vix
        assert agent.adaptive_weights["mac"] < before_mac
        assert agent.adaptive_weights["za"] == before_za
        assert log and isinstance(log, list)

    def test_trend_gate_vetoes_against_trend(self):
        from src.jexi.papersim import SignalPlan

        # UP is below its own SMA at the end of an extended decline.
        falling = [100.0 * (0.995 ** i) for i in range(120)]
        agent = JexiBossAgent(
            config=StubConfig(),
            notifier=JexiNotifier(None),
            fetcher=FakeFetcher({"UP": make_frame(falling, code="UP")}),
        )
        loop = JexiLearningLoop(
            agent, ticker_lists={"bear": ["UP"]}, max_iterations=1,
            trend_gate=True, rebalance_days=10, lookback_days=120,
            specialist_ids=["vix"],
        )
        plan = SignalPlan(code="UP", signal="long")
        frames = loop._load_scenario_frames("2020-11-01", "2021-12-31", ["UP"])
        gated = loop._trend_gate_plans([plan], frames, "2020-11-02")
        assert gated[0].signal == "flat"
        # a rising tape keeps a long and vetoes a short
        rising = [100.0 * (1.005 ** i) for i in range(120)]
        agent2 = JexiBossAgent(
            config=StubConfig(), notifier=JexiNotifier(None),
            fetcher=FakeFetcher({"UP": make_frame(rising, code="UP")}),
        )
        loop2 = JexiLearningLoop(agent2, ticker_lists={"bull": ["UP"]}, trend_gate=True)
        frames2 = loop2._load_scenario_frames("2020-11-01", "2021-12-31", ["UP"])
        go_long = loop2._trend_gate_plans([SignalPlan(code="UP", signal="long")], frames2, "2020-11-02")
        go_short = loop2._trend_gate_plans([SignalPlan(code="UP", signal="short")], frames2, "2020-11-02")
        assert go_long[0].signal == "long"
        assert go_short[0].signal == "flat"
