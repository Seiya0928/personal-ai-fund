import pytest
from pathlib import Path
from src.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(db_path=tmp_path / "test.db")


def test_save_ticker_dedup(store):
    ticker = {"symbol": "BTC_JPY", "ask": 10000.0, "bid": 9900.0, "last": 9950.0, "volume": 1.5, "timestamp": "2024-01-01T00:00:00.000Z"}
    assert store.save_ticker(ticker) is True
    assert store.save_ticker(ticker) is False  # 重複


def test_load_latest_ticker(store):
    ticker1 = {"symbol": "BTC_JPY", "ask": 10000.0, "bid": 9900.0, "last": 9950.0, "volume": 1.5, "timestamp": "2024-01-01T00:00:00.000Z"}
    ticker2 = {"symbol": "BTC_JPY", "ask": 11000.0, "bid": 10900.0, "last": 10950.0, "volume": 2.5, "timestamp": "2024-01-02T00:00:00.000Z"}
    store.save_ticker(ticker1)
    store.save_ticker(ticker2)

    latest = store.load_latest_ticker("BTC_JPY")

    assert latest["last"] == 10950.0


def test_save_and_load_ohlcv(store):
    rows = [
        {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0, "timestamp": str(i * 3600000)}
        for i in range(5)
    ]
    saved = store.save_ohlcv(rows, "BTC_JPY", "1hour")
    assert saved == 5
    loaded = store.load_ohlcv("BTC_JPY", "1hour")
    assert len(loaded) == 5
