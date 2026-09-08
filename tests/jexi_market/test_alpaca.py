# -*- coding: utf-8 -*-
"""Tests for the Alpaca client (mocked HTTP)."""

from unittest.mock import patch, MagicMock

from jexi_market.config import MarketConfig
from jexi_market.contracts import Confidence, Decision, Evidence, MarketRegime, SignalDirection
from jexi_market.execution.alpaca import AlpacaClient, AccountInfo, Order


def _mock_response(status: int = 200, json_data: dict = None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.raise_for_status.return_value = None
    return resp


def test_client_defaults_to_paper():
    config = MarketConfig()
    config.alpaca_environment = "paper"
    client = AlpacaClient(config)
    assert client.paper_trading is True


def test_client_forces_paper_when_live_not_enabled():
    """Even if ALPACA_ENV=live, without JEXI_LIVE_TRADING_ENABLED it falls back to paper."""
    config = MarketConfig()
    config.alpaca_environment = "live"
    config.live_trading_enabled = False
    client = AlpacaClient(config)
    assert client.paper_trading is True


def test_client_uses_live_when_explicitly_enabled():
    config = MarketConfig()
    config.alpaca_environment = "live"
    config.live_trading_enabled = True
    client = AlpacaClient(config)
    assert client.paper_trading is False


def test_client_configured_false_when_no_credentials():
    config = MarketConfig()
    config.alpaca_api_key = ""
    config.alpaca_api_secret = ""
    client = AlpacaClient(config)
    assert client.configured is False


def test_client_configured_true_when_credentials_present():
    config = MarketConfig()
    config.alpaca_api_key = "test_key"
    config.alpaca_api_secret = "test_secret"
    client = AlpacaClient(config)
    assert client.configured is True


def test_get_account_returns_empty_when_not_configured():
    config = MarketConfig()
    client = AlpacaClient(config)
    account = client.get_account()
    assert account.paper_trading is True
    assert account.equity == 0.0


def test_get_account_parses_response():
    config = MarketConfig()
    config.alpaca_api_key = "k"
    config.alpaca_api_secret = "s"
    client = AlpacaClient(config)
    mock_data = {
        "id": "acc-123",
        "status": "ACTIVE",
        "cash": "10000.50",
        "equity": "150000.75",
        "buying_power": "300000.0",
        "portfolio_value": "150000.75",
        "paper_trading": True,
    }
    with patch("jexi_market.execution.alpaca.requests.get", return_value=_mock_response(200, mock_data)):
        account = client.get_account()
    assert account.id == "acc-123"
    assert account.status == "ACTIVE"
    assert account.cash == 10000.50
    assert account.equity == 150000.75
    assert account.paper_trading is True


def test_get_positions_returns_typed_objects():
    config = MarketConfig()
    config.alpaca_api_key = "k"
    config.alpaca_api_secret = "s"
    client = AlpacaClient(config)
    mock_data = [
        {
            "symbol": "AAPL",
            "qty": "10",
            "side": "long",
            "market_value": "2000.0",
            "cost_basis": "1800.0",
            "unrealized_pl": "200.0",
            "unrealized_plpc": "0.1111",
            "current_price": "200.0",
        }
    ]
    with patch("jexi_market.execution.alpaca.requests.get", return_value=_mock_response(200, mock_data)):
        positions = client.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].qty == 10.0
    assert positions[0].side == "long"
    assert positions[0].current_price == 200.0


def test_submit_order_returns_typed_order():
    config = MarketConfig()
    config.alpaca_api_key = "k"
    config.alpaca_api_secret = "s"
    client = AlpacaClient(config)
    mock_data = {
        "id": "order-456",
        "status": "new",
        "symbol": "AAPL",
        "qty": "5",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "filled_qty": "0",
        "filled_avg_price": None,
        "created_at": "2024-01-01T00:00:00Z",
    }
    with patch("jexi_market.execution.alpaca.requests.post", return_value=_mock_response(200, mock_data)):
        order = client.submit_order("AAPL", 5, "buy")
    assert order.id == "order-456"
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.qty == 5.0


def test_execute_decision_raises_when_not_configured():
    config = MarketConfig()
    client = AlpacaClient(config)
    decision = Decision(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        confidence=Confidence(),
        entry=100.0,
    )
    try:
        client.execute_decision(decision, portfolio_equity=100_000.0, latest_price=100.0)
        assert False, "should have raised"
    except RuntimeError as exc:
        assert "not configured" in str(exc).lower()


def test_execute_decision_raises_for_flat():
    config = MarketConfig()
    config.alpaca_api_key = "k"
    config.alpaca_api_secret = "s"
    client = AlpacaClient(config)
    decision = Decision(
        symbol="AAPL",
        direction=SignalDirection.FLAT,
        confidence=Confidence(),
    )
    try:
        client.execute_decision(decision, portfolio_equity=100_000.0, latest_price=100.0)
        assert False, "should have raised"
    except ValueError as exc:
        assert "FLAT" in str(exc)


def test_execute_decision_computes_qty():
    config = MarketConfig()
    config.alpaca_api_key = "k"
    config.alpaca_api_secret = "s"
    client = AlpacaClient(config)
    decision = Decision(
        symbol="AAPL",
        direction=SignalDirection.LONG,
        confidence=Confidence(),
        entry=100.0,
        position_fraction=0.10,  # 10% of $100k = $10k
    )
    mock_data = {
        "id": "order-test",
        "status": "new",
        "symbol": "AAPL",
        "qty": "100",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "filled_qty": "0",
        "filled_avg_price": None,
        "created_at": "2024-01-01T00:00:00Z",
    }
    with patch("jexi_market.execution.alpaca.requests.post", return_value=_mock_response(200, mock_data)):
        order = client.execute_decision(decision, portfolio_equity=100_000.0, latest_price=100.0)
    # $10k / $100 = 100 shares
    assert order.qty == 100.0
    assert order.side == "buy"
