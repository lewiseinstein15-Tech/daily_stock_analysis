# -*- coding: utf-8 -*-
"""Pocket Option adapter — SSID parsing (bare token vs full auth frame)."""

from __future__ import annotations

import pytest

from jexi_market.brokers.pocketoption import PocketOptionBroker


AUTH_FRAME = (
    '42["auth",{"session":"ldcr4mfusv388quucq3cr570im","isDemo":1,'
    '"uid":103871746,"platform":3,"isFastHistory":true,"isOptimized":true}]'
)


def test_parse_ssid_bare_token():
    parsed = PocketOptionBroker._parse_ssid("ldcr4mfusv388quucq3cr570im")
    assert parsed == {"session": "ldcr4mfusv388quucq3cr570im"}


def test_parse_ssid_full_auth_frame():
    parsed = PocketOptionBroker._parse_ssid(AUTH_FRAME)
    assert parsed["session"] == "ldcr4mfusv388quucq3cr570im"
    assert parsed["isDemo"] == 1
    assert parsed["uid"] == 103871746
    assert parsed["platform"] == 3


def test_parse_ssid_frame_without_42_prefix():
    frame = '["auth",{"session":"tok123","isDemo":1}]'
    parsed = PocketOptionBroker._parse_ssid(frame)
    assert parsed["session"] == "tok123"


def test_parse_ssid_garbage_treated_as_token():
    assert PocketOptionBroker._parse_ssid("  just some text  ") == {"session": "just some text"}
    assert PocketOptionBroker._parse_ssid("") == {"session": ""}


def test_broker_init_parses_saved_ssid(monkeypatch):
    monkeypatch.setenv("POCKET_OPTION_SSID", AUTH_FRAME)
    monkeypatch.setenv("POCKET_OPTION_DEMO", "1")
    broker = PocketOptionBroker()
    assert broker.ssid.startswith("42[")
    assert broker._auth["uid"] == 103871746
    assert broker.demo is True
    assert broker.paper is True
