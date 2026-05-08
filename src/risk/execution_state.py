"""
execution_state.py — 残高・ポジション・本日約定履歴の管理。

口座と同期するデータはすべてここを通す。
将来 Private API が使えるようになったら、
_sync_from_api() の中身を実装するだけで対応できる構造にしている。
"""
from __future__ import annotations

import sqlite3
import time
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fund.db"


@dataclass
class Execution:
    symbol: str
    side: str        # BUY / SELL
    price: float
    quantity: float  # BTC量
    timestamp: float  # unix time
    execution_id: str = ""
    avg_entry_price_at_trade: float = 0.0  # 約定時点の平均取得単価（損益計算用）

    @property
    def value_jpy(self) -> float:
        return self.price * self.quantity

    @property
    def realized_pnl_jpy(self) -> float:
        """SELLのみ: 実現損益。avg_entry_price_at_trade が設定されている場合のみ計算。"""
        if self.side != "SELL" or self.avg_entry_price_at_trade <= 0:
            return 0.0
        return (self.price - self.avg_entry_price_at_trade) * self.quantity


@dataclass
class ExecutionState:
    """現在の残高・ポジション・本日約定履歴を保持する。"""
    balance_jpy: float = 0.0       # 円残高（モック時は仮想値）
    btc_held: float = 0.0          # 保有BTC量
    avg_entry_price: float = 0.0   # 平均取得単価
    executions_today: List[Execution] = field(default_factory=list)
    last_synced_at: float = 0.0

    def position_value_jpy(self, current_price: float) -> float:
        """保有BTCの評価額（pending分を含む）。"""
        return self.btc_held * current_price

    def effective_btc(self, pending_buy_qty: float = 0.0, pending_sell_qty: float = 0.0) -> float:
        """
        約定済み + pending BUY分 - pending SELL分 の実効BTC量。
        ポジション上限チェックに使う。
        """
        return self.btc_held + pending_buy_qty - pending_sell_qty

    def daily_loss_jpy(self, current_price: float = 0.0) -> float:
        """本日の実現損失合計（SELLのみ）を返す。含み損は含まない。"""
        loss = 0.0
        for ex in self.executions_today:
            pnl = ex.realized_pnl_jpy
            if pnl < 0:
                loss += abs(pnl)
        return loss

    def daily_execution_count(self) -> int:
        return len(self.executions_today)

    def apply_execution(self, ex: Execution):
        """約定を状態に反映する（加重平均取得単価を更新）。"""
        if ex.side == "BUY":
            total_cost = self.avg_entry_price * self.btc_held + ex.price * ex.quantity
            self.btc_held += ex.quantity
            self.avg_entry_price = total_cost / self.btc_held if self.btc_held > 0 else 0.0
            self.balance_jpy -= ex.value_jpy
        elif ex.side == "SELL":
            # 損益計算用に約定時点の平均取得単価をExecutionに記録する
            ex.avg_entry_price_at_trade = self.avg_entry_price
            self.btc_held = max(0.0, self.btc_held - ex.quantity)
            self.balance_jpy += ex.value_jpy
            if self.btc_held == 0:
                self.avg_entry_price = 0.0
        self.executions_today.append(ex)
        log.info(
            f"約定反映: {ex.side} {ex.quantity:.8f} BTC @ ¥{ex.price:,.0f}"
            f" | 保有BTC={self.btc_held:.8f} 円残高=¥{self.balance_jpy:,.0f}"
        )


class ExecutionStore:
    """約定ログの SQLite 永続化。"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT,
                    symbol       TEXT NOT NULL,
                    side         TEXT NOT NULL,
                    price        REAL NOT NULL,
                    quantity     REAL NOT NULL,
                    is_dry_run   INTEGER NOT NULL DEFAULT 1,
                    timestamp    REAL NOT NULL
                )
            """)

    def save(self, ex: Execution, is_dry_run: bool = True):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO executions
                   (execution_id, symbol, side, price, quantity, is_dry_run, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ex.execution_id, ex.symbol, ex.side, ex.price,
                 ex.quantity, int(is_dry_run), ex.timestamp),
            )
        log.info(
            f"約定ログ保存: {ex.symbol} {ex.side} "
            f"{ex.quantity:.8f}BTC @ ¥{ex.price:,.0f} dry_run={is_dry_run}"
        )

    def load_today(self, symbol: str | None = None) -> List[Execution]:
        today_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        query = "SELECT * FROM executions WHERE timestamp >= ?"
        params: list = [today_start]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY timestamp ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Execution(
                symbol=r["symbol"],
                side=r["side"],
                price=r["price"],
                quantity=r["quantity"],
                timestamp=r["timestamp"],
                execution_id=r["execution_id"] or "",
            )
            for r in rows
        ]

    def daily_execution_count(self, symbol: str | None = None) -> int:
        return len(self.load_today(symbol))
