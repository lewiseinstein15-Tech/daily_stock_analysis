# -*- coding: utf-8 -*-
"""Tests for the Jexi app account bridge (keys + notifications)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jexi_market.app_account import app_configured, apply_account_keys, push_notification
from jexi_market.config import MarketConfig, reset_config
from jexi_market.notifications import AppReporter, NtfyReporter, make_reporter


def _wired_config(**over):
    cfg = MarketConfig()
    cfg.jexi_app_server = "https://jexi.test"
    cfg.jexi_app_agent_secret = "agent-secret"
    cfg.jexi_app_email = "user@jexi.test"
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


# ---------------------------------------------------------------- configured

def test_app_configured_requires_all_three():
    cfg = _wired_config()
    assert app_configured(cfg)
    cfg2 = _wired_config(jexi_app_agent_secret="")
    assert not app_configured(cfg2)
    cfg3 = _wired_config(jexi_app_email="")
    assert not app_configured(cfg3)


# ---------------------------------------------------------------- keys apply

def test_apply_account_keys_loads_alpaca(monkeypatch):
    cfg = _wired_config()
    payload = {
        "set": True,
        "mode": "paper",
        "aiProvider": "openai",
        "aiKey": "sk-test",
        "brokerName": "alpaca-paper",
        "brokerKey": "AK123",
        "brokerSecret": "SEC456",
    }
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _Resp(payload)

    monkeypatch.setattr("jexi_market.app_account.requests.get", fake_get)
    assert apply_account_keys(cfg) is True
    assert captured["url"].endswith("/api/agent/keys")
    assert captured["headers"]["x-agent-secret"] == "agent-secret"
    assert cfg.alpaca_api_key == "AK123"
    assert cfg.alpaca_api_secret == "SEC456"
    assert cfg.alpaca_environment == "paper"
    assert cfg.broker == "alpaca"
    assert cfg.app_account_mode == "paper"


def test_apply_account_keys_live_mode_enables_live(monkeypatch):
    cfg = _wired_config()
    cfg.live_trading_enabled = False
    payload = {
        "set": True,
        "mode": "live",
        "brokerName": "alpaca-live",
        "brokerKey": "LIVEKEY",
        "brokerSecret": "LIVESEC",
    }
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    assert apply_account_keys(cfg) is True
    assert cfg.alpaca_environment == "live"
    assert cfg.alpaca_base_url == "https://api.alpaca.markets"
    assert cfg.live_trading_enabled is True
    assert cfg.app_account_mode == "live"


def test_apply_account_keys_paper_keys_stay_paper_even_in_live_mode(monkeypatch):
    cfg = _wired_config()
    payload = {"set": True, "mode": "live", "brokerName": "alpaca-paper", "brokerKey": "PK", "brokerSecret": "PS"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    apply_account_keys(cfg)
    assert cfg.alpaca_environment == "paper"
    assert cfg.live_trading_enabled is False


# ---------------------------------------------------------------- pocket option

def test_apply_account_keys_pocketoption_demo_forced(monkeypatch):
    cfg = _wired_config()
    monkeypatch.delenv("POCKET_OPTION_SSID", raising=False)
    monkeypatch.delenv("POCKET_OPTION_DEMO", raising=False)
    payload = {"set": True, "mode": "paper", "brokerName": "pocketoption", "brokerKey": "ssid-demo-token"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    assert apply_account_keys(cfg) is True
    import os
    assert os.environ["POCKET_OPTION_SSID"] == "ssid-demo-token"
    assert os.environ["POCKET_OPTION_DEMO"] == "1"          # demo is forced for the demo choice
    assert cfg.broker == "pocketoption"
    assert cfg.live_trading_enabled is False


def test_apply_account_keys_pocketoption_live_blocked_until_app_mode_live(monkeypatch):
    cfg = _wired_config()
    cfg.live_trading_enabled = False
    monkeypatch.delenv("JEXI_LIVE_TRADING_ENABLED", raising=False)
    payload = {"set": True, "mode": "paper", "brokerName": "pocketoption-live", "brokerKey": "ssid-live-token"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    apply_account_keys(cfg)
    import os
    assert os.environ["POCKET_OPTION_DEMO"] == "0"
    assert "JEXI_LIVE_TRADING_ENABLED" not in os.environ    # app says paper -> live gate stays shut
    assert cfg.live_trading_enabled is False


def test_apply_account_keys_pocketoption_live_enabled_in_live_mode(monkeypatch):
    cfg = _wired_config()
    cfg.live_trading_enabled = False
    monkeypatch.delenv("JEXI_LIVE_TRADING_ENABLED", raising=False)
    payload = {"set": True, "mode": "live", "brokerName": "pocketoption-live", "brokerKey": "ssid-live-token"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    apply_account_keys(cfg)
    import os
    assert os.environ["POCKET_OPTION_SSID"] == "ssid-live-token"
    assert os.environ["POCKET_OPTION_DEMO"] == "0"
    assert os.environ["JEXI_LIVE_TRADING_ENABLED"] == "1"   # app confirmed live -> adapter gate opened
    assert cfg.live_trading_enabled is True
    assert cfg.broker == "pocketoption"


def test_apply_account_keys_unreachable_returns_false(monkeypatch):
    cfg = _wired_config()
    import requests as _requests

    def boom(url, **kwargs):
        raise _requests.exceptions.ConnectionError("no network")

    monkeypatch.setattr("jexi_market.app_account.requests.get", boom)
    assert apply_account_keys(cfg) is False


def test_apply_account_keys_no_keys_yet(monkeypatch):
    cfg = _wired_config()
    payload = {"set": False, "mode": "paper"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    assert apply_account_keys(cfg) is True
    assert cfg.alpaca_api_key == ""
    assert cfg.broker in ("auto", "")


# ---------------------------------------------------------------- notifications

def test_push_notification_posts_to_agent_notify(monkeypatch):
    cfg = _wired_config()
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update({"url": url, "json": json, "headers": headers})
        return _Resp({"ok": True}, status=201)

    monkeypatch.setattr("jexi_market.app_account.requests.post", fake_post)
    ok = push_notification(cfg, "Bought 2 AAPL.", kind="win", title="Hi")
    assert ok is True
    assert seen["url"].endswith("/api/agent/notify")
    assert seen["json"]["email"] == "user@jexi.test"
    assert seen["json"]["kind"] == "win"
    assert seen["headers"]["x-agent-secret"] == "agent-secret"


def test_make_reporter_picks_app_when_wired():
    cfg = _wired_config()
    assert isinstance(make_reporter(cfg), AppReporter)
    assert isinstance(make_reporter(MarketConfig()), NtfyReporter)


def test_app_reporter_publish_decision_reuses_renderer(monkeypatch):
    cfg = _wired_config()
    rep = AppReporter(cfg)
    assert rep.enabled
    assert "api/agent/notify" in (rep.endpoint or "")
    # publish path goes through push_notification with kind info/high mapping
    monkeypatch.setattr(
        "jexi_market.notifications.app.push_notification",
        lambda c, message, **kw: kw.get("kind") == "warn" and "PRIORITY" in message,
    )
    assert rep.publish("t", "PRIORITY", priority="high") is True


# ---------------------------------------------------------------- get_config hook

def test_get_config_pulls_account_keys(monkeypatch):
    monkeypatch.setenv("JEXI_APP_SERVER", "https://jexi.test")
    monkeypatch.setenv("JEXI_AGENT_SECRET", "s")
    monkeypatch.setenv("JEXI_APP_EMAIL", "e@jexi.test")
    payload = {"set": True, "mode": "paper", "brokerName": "alpaca-paper", "brokerKey": "K1", "brokerSecret": "S1"}
    monkeypatch.setattr("jexi_market.app_account.requests.get", lambda url, **k: _Resp(payload))
    reset_config()
    from jexi_market.config import get_config

    cfg = get_config()
    try:
        assert cfg.alpaca_api_key == "K1"
    finally:
        reset_config()


@pytest.fixture(autouse=True)
def _clean_singleton():
    reset_config()
    yield
    reset_config()
