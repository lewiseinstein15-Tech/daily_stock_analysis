# -*- coding: utf-8 -*-
"""Tests for the ntfy reporter."""

from unittest.mock import patch, MagicMock

from jexi_market.config import MarketConfig
from jexi_market.contracts import (
    Confidence,
    Decision,
    Evidence,
    MarketRegime,
    Recommendation,
    SignalDirection,
)
from jexi_market.notifications.reporter import NtfyReporter


def _make_decision(direction=SignalDirection.LONG) -> Decision:
    return Decision(
        symbol="AAPL",
        direction=direction,
        confidence=Confidence(agreement=0.85, data_freshness=1.0, evidence_count=4),
        entry=180.0,
        stop_loss=170.0,
        take_profit=200.0,
        position_fraction=0.10,
        risk_per_trade=0.02,
        thesis="strong technical momentum; macro regime bull",
        invalidation="close below SMA50",
        evidence=(
            Evidence(claim="price above SMA20", source="technical"),
            Evidence(claim="RSI 55 (neutral)", source="technical"),
            Evidence(claim="bull regime", source="macro"),
        ),
        supporting_agents=("technical", "macro"),
        opposing_agents=("risk",),
        risks=("elevated volatility",),
        regime=MarketRegime.BULL,
    )


def _make_recommendations():
    return [
        Recommendation(
            symbol="AAPL", direction=SignalDirection.LONG,
            thesis="technical long", agent_id="technical",
            agent_kind=None,  # will be set below
            confidence=Confidence(agreement=0.8, data_freshness=1.0, evidence_count=2),
            evidence=(Evidence(claim="tech signal", source="technical"),),
        ),
        Recommendation(
            symbol="AAPL", direction=SignalDirection.FLAT,
            thesis="risk veto", agent_id="risk",
            agent_kind=None,
            confidence=Confidence(agreement=0.0, data_freshness=1.0, evidence_count=1, disagreement_penalty=0.4),
            evidence=(Evidence(claim="vol elevated", source="risk"),),
        ),
    ]


def test_reporter_offline_mode_prints_to_stdout(capsys):
    """When the reporter's endpoint is forced to None, it prints to stdout."""
    config = MarketConfig()
    config.ntfy_url = ""
    config.jexi_ntfy_topic = ""
    reporter = NtfyReporter(config)
    # Force offline mode by nulling the endpoint
    reporter._endpoint = None
    assert reporter.enabled is False
    ok = reporter.publish("Test Title", "Test body", priority="default")
    assert ok is False
    captured = capsys.readouterr()
    assert "Test Title" in captured.out


def test_reporter_renders_full_report_format():
    config = MarketConfig()
    config.ntfy_url = ""  # offline so we don't try to push
    reporter = NtfyReporter(config)
    decision = _make_decision()
    recs = _make_recommendations()
    # Patch agent_kind since we left it as None above
    from jexi_market.contracts import AgentKind
    recs[0] = Recommendation(**{**recs[0].__dict__, "agent_kind": AgentKind.TECHNICAL})
    recs[1] = Recommendation(**{**recs[1].__dict__, "agent_kind": AgentKind.RISK})

    text = reporter.render_report(
        decision=decision,
        recommendations=recs,
        agent_ids_run=["technical", "risk", "macro"],
        task="Analyze AAPL",
        regime="bull",
        timezone="EAT",
    )

    # Must contain the exact section headers from the spec
    assert "JEXI MARKET REPORT" in text
    assert "━" * 20 in text
    assert "TIME:" in text
    assert "TASK:" in text
    assert "ACTION:" in text
    assert "CONFIDENCE:" in text
    assert "WHY:" in text
    assert "RISKS:" in text
    assert "AGENTS:" in text
    assert "PROPOSED ENTRY:" in text
    assert "STOP:" in text
    assert "TARGET:" in text
    assert "RISK:" in text
    assert "EVIDENCE:" in text
    assert "WHAT JEXI DID:" in text
    assert "NEXT ACTION:" in text

    # Action label mapping
    assert "BUY CANDIDATE" in text

    # Confidence formatted as percentage
    assert "%" in text

    # Evidence sources present
    assert "[technical]" in text
    assert "[macro]" in text


def test_reporter_action_label_for_short():
    config = MarketConfig()
    config.ntfy_url = ""
    reporter = NtfyReporter(config)
    decision = _make_decision(direction=SignalDirection.SHORT)
    text = reporter.render_report(
        decision=decision,
        recommendations=[],
        agent_ids_run=[],
        task="test",
        regime="bear",
    )
    assert "SHORT CANDIDATE" in text


def test_reporter_action_label_for_flat():
    config = MarketConfig()
    config.ntfy_url = ""
    reporter = NtfyReporter(config)
    decision = _make_decision(direction=SignalDirection.FLAT)
    text = reporter.render_report(
        decision=decision,
        recommendations=[],
        agent_ids_run=[],
        task="test",
        regime="sideways",
    )
    assert "HOLD / WATCH" in text


def test_reporter_publishes_when_configured():
    config = MarketConfig()
    config.ntfy_url = "https://ntfy.sh/jexi_test_topic"
    config.ntfy_token = ""
    reporter = NtfyReporter(config)
    assert reporter.enabled is True

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("jexi_market.notifications.reporter.requests.post", return_value=mock_resp) as mock_post:
        ok = reporter.publish("Title", "Body", priority="high")
    assert ok is True
    mock_post.assert_called_once()
    # Check the payload went to the right server
    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.sh"
    payload = kwargs["json"]
    assert payload["topic"] == "jexi_test_topic"
    assert payload["title"] == "Title"
    assert payload["message"] == "Body"
    assert payload["priority"] == 4  # high


def test_reporter_handles_http_failure():
    config = MarketConfig()
    config.ntfy_url = "https://ntfy.sh/jexi_test_topic"
    reporter = NtfyReporter(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("jexi_market.notifications.reporter.requests.post", return_value=mock_resp):
        ok = reporter.publish("Title", "Body")
    assert ok is False


def test_reporter_handles_network_exception():
    import requests
    config = MarketConfig()
    config.ntfy_url = "https://ntfy.sh/jexi_test_topic"
    reporter = NtfyReporter(config)

    with patch("jexi_market.notifications.reporter.requests.post", side_effect=requests.exceptions.ConnectionError("net down")):
        ok = reporter.publish("Title", "Body")
    assert ok is False


def test_reporter_priority_map():
    """All spec priorities map to ntfy's 1-5 scale."""
    config = MarketConfig()
    config.ntfy_url = "https://ntfy.sh/test"
    reporter = NtfyReporter(config)
    assert reporter.PRIORITY_MAP["min"] == 1
    assert reporter.PRIORITY_MAP["low"] == 2
    assert reporter.PRIORITY_MAP["default"] == 3
    assert reporter.PRIORITY_MAP["high"] == 4
    assert reporter.PRIORITY_MAP["emergency"] == 5
