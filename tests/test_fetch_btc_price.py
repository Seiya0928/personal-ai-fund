import importlib.util
from pathlib import Path

from src.storage.sqlite_store import SQLiteStore as RealSQLiteStore


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_btc_price.py"
SPEC = importlib.util.spec_from_file_location("fetch_btc_price_module", SCRIPT_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class FakeBroker:
    def __init__(self, empty_ohlcv=False, fail_ticker=False):
        self.empty_ohlcv = empty_ohlcv
        self.fail_ticker = fail_ticker

    def get_ticker(self, symbol):
        if self.fail_ticker:
            raise RuntimeError("ticker error")
        return {
            "symbol": symbol,
            "ask": 101.0,
            "bid": 99.0,
            "last": 100.0,
            "volume": 1.5,
            "timestamp": "2026-05-09T14:09:58.976Z",
        }

    def get_ohlcv_history(self, symbol, interval, limit):
        if self.empty_ohlcv:
            return []
        return [
            {
                "open": 90.0,
                "high": 101.0,
                "low": 89.0,
                "close": 100.0,
                "volume": 1.0,
                "timestamp": "1778274000000" if interval == "1day" else "1778335200000",
            }
        ]


def test_fetch_btc_price_saves_ticker_and_ohlcv(monkeypatch, tmp_path):
    db_path = tmp_path / "fund.db"
    monkeypatch.setattr(module, "GMOPublicBroker", lambda: FakeBroker())
    monkeypatch.setattr(module, "SQLiteStore", lambda: RealSQLiteStore(db_path))

    exit_code = module.main()
    store = RealSQLiteStore(db_path)

    assert exit_code == 0
    assert store.load_latest_ticker("BTC_JPY")["timestamp"] == "2026-05-09T14:09:58.976Z"
    assert len(store.load_ohlcv("BTC_JPY", "1hour")) == 1
    assert len(store.load_ohlcv("BTC_JPY", "1day")) == 1


def test_fetch_btc_price_returns_nonzero_on_ticker_error(monkeypatch, tmp_path):
    db_path = tmp_path / "fund.db"
    monkeypatch.setattr(module, "GMOPublicBroker", lambda: FakeBroker(fail_ticker=True))
    monkeypatch.setattr(module, "SQLiteStore", lambda: RealSQLiteStore(db_path))

    assert module.main() == 1


def test_fetch_btc_price_returns_nonzero_on_empty_ohlcv(monkeypatch, tmp_path):
    db_path = tmp_path / "fund.db"
    monkeypatch.setattr(module, "GMOPublicBroker", lambda: FakeBroker(empty_ohlcv=True))
    monkeypatch.setattr(module, "SQLiteStore", lambda: RealSQLiteStore(db_path))

    assert module.main() == 1


def test_fetch_btc_price_source_does_not_reference_private_order_route():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden = ["private/v1/order", "place_order", "live_order_once", "DRY_RUN=false", "READ_ONLY=false"]
    for token in forbidden:
        assert token not in source
