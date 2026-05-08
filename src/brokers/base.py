from __future__ import annotations
from abc import ABC, abstractmethod


class BrokerBase(ABC):
    """ブローカー共通インターフェース。GMO / IBKR など将来の移植先もここを継承する。"""

    @abstractmethod
    def get_ticker(self, symbol: str) -> dict:
        """現在の板情報・最終価格を返す。"""

    @abstractmethod
    def get_ohlcv(self, symbol: str, interval: str, limit: int) -> list[dict]:
        """OHLCVデータを返す。interval例: '1hour', '1day'"""
