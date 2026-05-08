import time
from typing import Optional
from datetime import datetime, timedelta, timezone
import requests
from src.brokers.base import BrokerBase
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.coin.z.com/public/v1"
MAX_RETRIES = 3
RETRY_WAIT = 2  # seconds


class GMOPublicBroker(BrokerBase):
    """GMOコイン Public API（認証不要）のラッパー。"""

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{BASE_URL}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != 0:
                    raise ValueError(f"APIエラー status={data.get('status')}: {data}")
                return data
            except Exception as e:
                log.warning(f"リトライ {attempt}/{MAX_RETRIES} - {e}")
                if attempt == MAX_RETRIES:
                    log.error(f"リクエスト失敗（最大リトライ超過）: {url}")
                    raise
                time.sleep(RETRY_WAIT * attempt)

    def get_ticker(self, symbol: str = "BTC_JPY") -> dict:
        data = self._get("/ticker", params={"symbol": symbol})
        item = data["data"][0]
        return {
            "symbol": item["symbol"],
            "ask": float(item["ask"]),
            "bid": float(item["bid"]),
            "last": float(item["last"]),
            "volume": float(item["volume"]),
            "timestamp": item["timestamp"],
        }

    def get_ohlcv(self, symbol: str = "BTC_JPY", interval: str = "1hour", limit: int = 200) -> list[dict]:
        rows = self.get_ohlcv_history(symbol=symbol, interval=interval, limit=limit)
        return rows[-limit:]

    def get_ohlcv_history(self, symbol: str = "BTC_JPY", interval: str = "1hour", limit: int = 1000) -> list[dict]:
        """
        可能な範囲で過去分の OHLCV をまとめて取得する。
        1hour 以下は日単位、1day 以上は年単位で遡る。
        """
        now = datetime.now(timezone.utc)
        if interval in ("1day", "1week", "1month"):
            keys = [str(year) for year in range(now.year, now.year - 5, -1)]
        else:
            # 1hour は 1日単位でしか取れないため、必要本数より十分広く遡る
            # 旧実装が当日分しか保存していないケースを埋めるため、最低90日分を見る
            lookback_days = max(90, min(365, (limit // 24) + 60))
            keys = [
                (now - timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(lookback_days)
            ]

        merged: dict[str, dict] = {}
        for key in keys:
            data = self._get("/klines", params={"symbol": symbol, "interval": interval, "date": key})
            for row in data.get("data", []):
                merged[row["openTime"]] = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "timestamp": row["openTime"],
                }

        rows = [merged[key] for key in sorted(merged.keys())]
        return rows[-limit:]
