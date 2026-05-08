"""BTC/JPY の ticker と 1hour / 1day OHLCV をできるだけ広く取得して保存する。"""
import sys
from pathlib import Path

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


def main():
    broker = GMOPublicBroker()
    store = SQLiteStore()

    log.info("=== ticker取得 ===")
    ticker = broker.get_ticker(SYMBOL)
    store.save_ticker(ticker)
    log.info(f"BTC/JPY last={ticker['last']:,.0f} ask={ticker['ask']:,.0f} bid={ticker['bid']:,.0f}")

    for interval, limit in INTERVAL_LIMITS.items():
        log.info(f"=== OHLCV取得 ({interval}) ===")
        rows = broker.get_ohlcv_history(SYMBOL, interval, limit=limit)
        saved = store.save_ohlcv(rows, SYMBOL, interval)
        log.info(f"新規保存: {saved}件 / 取得件数: {len(rows)}件")

        csv_path = Path(__file__).resolve().parents[1] / "data" / f"{SYMBOL}_{interval}.csv"
        store.export_ohlcv_csv(SYMBOL, interval, csv_path)
        log.info(f"CSV出力: {csv_path}")


if __name__ == "__main__":
    main()
