# 実注文なし・研究用シグナルのみ
# このモジュールは実注文APIを一切呼びません。

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

SignalAction = Literal["BUY", "SELL", "WATCH", "SKIP"]


@dataclass
class Candle:
    """1本のローソク足データ"""
    timestamp: str  # ISO 8601
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceSnapshot:
    """現在の価格スナップショット（bid/ask）"""
    ask: float
    bid: float
    timestamp: str  # ISO 8601

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2

    @property
    def spread_pips(self) -> float:
        # USD/JPY: 1pip = 0.01
        return round((self.ask - self.bid) / 0.01, 4)


@dataclass
class FXSignal:
    """FXシグナル（研究用・実注文なし）"""
    signal_id: str
    symbol: str
    action: SignalAction
    price: float          # mid price
    ask: float
    bid: float
    spread_pips: float
    timestamp: str        # ISO JST
    reasons: list[str] = field(default_factory=list)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    skip_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "action": self.action,
            "price": self.price,
            "ask": self.ask,
            "bid": self.bid,
            "spread_pips": self.spread_pips,
            "timestamp": self.timestamp,
            "reasons": self.reasons,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "skip_reason": self.skip_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FXSignal:
        return cls(
            signal_id=d["signal_id"],
            symbol=d["symbol"],
            action=d["action"],
            price=d["price"],
            ask=d["ask"],
            bid=d["bid"],
            spread_pips=d["spread_pips"],
            timestamp=d["timestamp"],
            reasons=d.get("reasons", []),
            stop_loss=d.get("stop_loss"),
            take_profit=d.get("take_profit"),
            skip_reason=d.get("skip_reason"),
        )
