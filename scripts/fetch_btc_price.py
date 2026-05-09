"""BTC/JPY の ticker と 1hour / 1day OHLCV をできるだけ広く取得して保存する。"""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brokers.gmo_public import GMOPublicBroker
from src.storage.sqlite_store import SQLiteStore
from src.utils.logger import get_logger

log = get_logger("fetch_btc_price")

SYMBOL = "BTC_JPY"
INTERVAL_LIMITS = {
    "1hour": 24 * 180,
    "1day": 1500,
}


def _ticker_saved_or_present(store: SQLiteStore, ticker: dict, saved: bool) -> bool:
    if saved:
        return True
    latest = store.load_latest_ticker(ticker["symbol"])
    return bool(latest and latest.get("timestamp") == ticker.get("timestamp"))


def _latest_ohlcv_timestamp(store: SQLiteStore, interval: str) -> Optional[str]:
    rows = store.load_ohlcv(SYMBOL, interval, limit=1)
    if not rows:
        return None
    return str(rows[-1].get("timestamp"))


def main() -> int:
    broker = GMOPublicBroker()
    store = SQLiteStore()
    log.info(f"DB path: {store.db_path.resolve()}")

    try:
        log.info("=== ticker取得 ===")
        ticker = broker.get_ticker(SYMBOL)
        ticker_saved = store.save_ticker(ticker)
        if not _ticker_saved_or_present(store, ticker, ticker_saved):
            log.error(f"ticker保存確認失敗: symbol={ticker.get('symbol')} ts={ticker.get('timestamp')}")
            return 1
        latest_ticker = store.load_latest_ticker(SYMBOL)
        log.info(
            f"BTC/JPY last={ticker['last']:,.0f} ask={ticker['ask']:,.0f} "
            f"bid={ticker['bid']:,.0f} timestamp={ticker['timestamp']} saved={ticker_saved}"
        )
        log.info(f"DB latest ticker: {latest_ticker}")

        for interval, limit in INTERVAL_LIMITS.items():
            before_latest = _latest_ohlcv_timestamp(store, interval)
            log.info(f"=== OHLCV取得 ({interval}) ===")
            rows = broker.get_ohlcv_history(SYMBOL, interval, limit=limit)
            if not rows:
                log.error(f"OHLCV取得結果が空です: {SYMBOL} {interval}")
                return 1
            saved = store.save_ohlcv(rows, SYMBOL, interval)
            after_latest = _latest_ohlcv_timestamp(store, interval)
            log.info(
                f"OHLCV {interval}: fetched={len(rows)} saved={saved} "
                f"api_first={rows[0]['timestamp']} api_last={rows[-1]['timestamp']} "
                f"db_latest_before={before_latest} db_latest_after={after_latest}"
            )

            csv_path = Path(__file__).resolve().parents[1] / "data" / f"{SYMBOL}_{interval}.csv"
            store.export_ohlcv_csv(SYMBOL, interval, csv_path)
            log.info(f"CSV出力: {csv_path}")
    except Exception:
        log.exception("BTC/JPY Public API fetch failed")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
