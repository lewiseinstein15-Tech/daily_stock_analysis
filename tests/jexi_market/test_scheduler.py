# -*- coding: utf-8 -*-
"""Tests for the autonomous scheduler."""

from unittest.mock import MagicMock, patch

from jexi_market.config import MarketConfig
from jexi_market.scheduler import AutonomousScheduler, JobResult


def test_scheduler_runs_scan_job_once(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    sched = AutonomousScheduler(config)
    # Patch the scanner's scan method to return empty list (no network)
    monkeypatch.setattr(sched.pipeline.scanner, "scan", lambda universe, days=120: [])
    result = sched.run_once("scan")
    assert isinstance(result, JobResult)
    assert result.job_name == "scan"
    assert result.success is True
    assert result.finished_at is not None


def test_scheduler_runs_monitor_job(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    sched = AutonomousScheduler(config)
    # Patch memory to return no recent trades
    monkeypatch.setattr(sched.memory, "recent_trades", lambda limit=50: [])
    result = sched.run_once("monitor")
    assert result.job_name == "monitor"
    assert result.success is True
    assert result.summary["n_open_trades"] == 0


def test_scheduler_runs_analyze_job(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    sched = AutonomousScheduler(config)
    # Patch pipeline to return an empty run
    from jexi_market.pipeline import PipelineRun
    empty_run = PipelineRun()
    empty_run.summary = {"n_scanned": 0, "n_candidates": 0, "n_approved": 0, "n_rejected": 0}
    monkeypatch.setattr(sched.pipeline, "run_full", lambda **kw: empty_run)
    result = sched.run_once("analyze")
    assert result.job_name == "analyze"
    assert result.success is True


def test_scheduler_runs_daily_summary_job(monkeypatch):
    config = MarketConfig()
    config.ntfy_url = ""
    sched = AutonomousScheduler(config)
    monkeypatch.setattr(sched.memory, "stats_summary", lambda: {"n_trades": 0})
    monkeypatch.setattr(sched.memory, "agent_stats", lambda: {})
    monkeypatch.setattr(sched.memory, "paper_trading_days", lambda: 5)
    # Patch reporter.publish to avoid real ntfy calls
    monkeypatch.setattr(sched.boss.reporter, "publish", lambda *a, **kw: True)
    result = sched.run_once("daily_summary")
    assert result.job_name == "daily_summary"
    assert result.success is True


def test_scheduler_unknown_job_raises():
    sched = AutonomousScheduler(MarketConfig())
    try:
        sched.run_once("nonexistent")
        assert False, "should have raised ValueError"
    except ValueError as exc:
        assert "nonexistent" in str(exc)


def test_scheduler_request_stop():
    sched = AutonomousScheduler(MarketConfig())
    assert sched._stop_requested is False
    sched.request_stop()
    assert sched._stop_requested is True


def test_job_result_to_dict():
    r = JobResult(job_name="test", success=True, summary={"x": 1})
    r.finished_at = r.started_at + 1.0
    d = r.to_dict()
    assert d["job_name"] == "test"
    assert d["success"] is True
    assert d["summary"] == {"x": 1}
    assert "elapsed_seconds" in d
