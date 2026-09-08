# -*- coding: utf-8 -*-
"""Tests for the enrichment adapters (fundamentals, news, sector)."""

from unittest.mock import patch, MagicMock

from jexi_market.enrichment import (
    FundamentalAdapter,
    Fundamentals,
    NewsAdapter,
    NewsSnapshot,
    SectorClassifier,
)


def test_fundamentals_dataclass_defaults():
    f = Fundamentals(symbol="AAPL")
    assert f.ok is False
    assert f.pe_ratio is None
    assert f.sector is None
    d = f.to_dict()
    assert d["symbol"] == "AAPL"
    assert d["ok"] is False


def test_fundamental_adapter_returns_none_when_yfinance_missing():
    """Adapter must gracefully handle missing yfinance — never crash."""
    adapter = FundamentalAdapter()
    with patch.dict("sys.modules", {"yfinance": None}):
        # Force ImportError
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=fake_import):
            fund = adapter.get_fundamentals("AAPL")
    assert fund.ok is False
    assert "not installed" in (fund.error or "") or "simulated" in (fund.error or "")


def test_fundamental_adapter_parses_yfinance_info():
    adapter = FundamentalAdapter()
    mock_info = {
        "trailingPE": 25.5,
        "forwardPE": 22.1,
        "priceToBook": 8.2,
        "profitMargins": 0.25,
        "grossMargins": 0.46,
        "operatingMargins": 0.30,
        "returnOnEquity": 1.5,
        "revenueGrowth": 0.10,
        "earningsGrowth": 0.20,
        "earningsQuarterlyGrowth": 0.15,
        "debtToEquity": 150.0,
        "currentRatio": 1.1,
        "marketCap": 3_000_000_000_000,
        "totalCash": 60_000_000_000,
        "totalDebt": 100_000_000_000,
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info
    with patch("yfinance.Ticker", return_value=mock_ticker):
        fund = adapter.get_fundamentals("AAPL")
    assert fund.ok is True
    assert fund.symbol == "AAPL"
    assert fund.pe_ratio == 25.5
    assert fund.forward_pe == 22.1
    assert fund.gross_margin == 0.46
    assert fund.sector == "Technology"
    assert fund.industry == "Consumer Electronics"


def test_fundamental_adapter_handles_empty_info():
    adapter = FundamentalAdapter()
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    with patch("yfinance.Ticker", return_value=mock_ticker):
        fund = adapter.get_fundamentals("UNKNOWN")
    assert fund.ok is False


def test_news_snapshot_dataclass():
    snap = NewsSnapshot(symbol="AAPL")
    assert snap.ok is False
    assert snap.sentiment == "neutral"
    assert snap.items == []


def test_news_adapter_returns_none_when_yfinance_missing():
    adapter = NewsAdapter()
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=fake_import):
        snap = adapter.get_news("AAPL")
    assert snap.ok is False
    assert "not installed" in (snap.error or "") or "simulated" in (snap.error or "")


def test_news_adapter_parses_yfinance_news():
    adapter = NewsAdapter()
    mock_news = [
        {
            "id": "1",
            "content": {
                "title": "Apple Beats Earnings Estimates, Stock Surges",
                "provider": {"displayName": "Bloomberg"},
                "pubDate": "2024-09-08T10:00:00Z",
                "canonicalUrl": {"url": "https://example.com/news/1"},
                "summary": "Apple reported strong Q3 earnings",
            },
        },
        {
            "id": "2",
            "content": {
                "title": "Apple Faces Lawsuit Over Patent Infringement",
                "provider": {"displayName": "Reuters"},
                "pubDate": "2024-09-07T15:30:00Z",
                "canonicalUrl": {"url": "https://example.com/news/2"},
                "summary": "A patent lawsuit was filed",
            },
        },
        {
            "id": "3",
            "content": {
                "title": "Apple Announces Record iPhone Sales",
                "provider": {"displayName": "CNBC"},
                "pubDate": "2024-09-06T09:00:00Z",
                "canonicalUrl": {"url": "https://example.com/news/3"},
                "summary": "Record sales reported",
            },
        },
    ]
    mock_ticker = MagicMock()
    mock_ticker.news = mock_news
    with patch("yfinance.Ticker", return_value=mock_ticker):
        snap = adapter.get_news("AAPL")
    assert snap.ok is True
    assert len(snap.items) == 3
    assert snap.items[0].title == "Apple Beats Earnings Estimates, Stock Surges"
    assert snap.items[0].publisher == "Bloomberg"
    # 2 positive ("Beats", "Record") + 1 negative ("Lawsuit") -> positive sentiment
    assert snap.sentiment == "positive"
    assert snap.sentiment_score > 0


def test_news_adapter_handles_empty_news():
    adapter = NewsAdapter()
    mock_ticker = MagicMock()
    mock_ticker.news = []
    with patch("yfinance.Ticker", return_value=mock_ticker):
        snap = adapter.get_news("UNKNOWN")
    assert snap.ok is False
    assert "no news items" in (snap.error or "")


def test_news_sentiment_keyword_classifier():
    adapter = NewsAdapter()
    from jexi_market.enrichment import NewsItem
    positive_items = [
        NewsItem(title="Stock Beats Estimates, Surges"),
        NewsItem(title="Strong Earnings Growth"),
        NewsItem(title="Upgrade to Buy"),
    ]
    sentiment, score = adapter._classify_sentiment(positive_items)
    assert sentiment == "positive"
    assert score > 0

    negative_items = [
        NewsItem(title="Stock Plunges on Earnings Miss"),
        NewsItem(title="Lawsuit Filed Against Company"),
        NewsItem(title="Downgrade to Sell"),
    ]
    sentiment, score = adapter._classify_sentiment(negative_items)
    assert sentiment == "negative"
    assert score < 0

    neutral_items = [
        NewsItem(title="Company Announces Quarterly Dividend"),
        NewsItem(title="Annual Meeting Scheduled"),
    ]
    sentiment, score = adapter._classify_sentiment(neutral_items)
    assert sentiment == "neutral"
    assert score == 0.0


def test_sector_classifier_uses_fundamental_adapter():
    mock_adapter = MagicMock()
    mock_adapter.get_fundamentals.return_value = Fundamentals(
        symbol="AAPL", ok=True, sector="Technology", industry="Consumer Electronics"
    )
    classifier = SectorClassifier(adapter=mock_adapter)
    assert classifier.classify("AAPL") == "Technology"
    # Second call uses cache
    assert classifier.classify("AAPL") == "Technology"
    # Only one adapter call despite two classify calls
    assert mock_adapter.get_fundamentals.call_count == 1


def test_sector_classifier_returns_unknown_when_no_sector():
    mock_adapter = MagicMock()
    mock_adapter.get_fundamentals.return_value = Fundamentals(symbol="X", ok=True, sector=None)
    classifier = SectorClassifier(adapter=mock_adapter)
    assert classifier.classify("X") == "Unknown"


def test_sector_classifier_classify_many():
    mock_adapter = MagicMock()
    def fake_get(symbol):
        return Fundamentals(symbol=symbol, ok=True, sector="Tech" if symbol.startswith("A") else "Energy")
    mock_adapter.get_fundamentals.side_effect = fake_get
    classifier = SectorClassifier(adapter=mock_adapter)
    result = classifier.classify_many(["AAPL", "MSFT", "XOM"])
    assert result["AAPL"] == "Tech"
    assert result["MSFT"] == "Energy"
    assert result["XOM"] == "Energy"
