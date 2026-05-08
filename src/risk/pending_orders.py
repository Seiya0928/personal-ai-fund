"""
pending_orders.py — 未約定注文の管理。

注文ID単位で管理し、約定・キャンセル・タイムアウトで状態を更新する。
Private API 実装後は get_open_orders() の結果をここに同期する。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fund.db"

# 注文ステータス定数
STATUS_OPEN      = "OPEN"
STATUS_FILLED    = "FILLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED   = "EXPIRED"


@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    side: str
    order_type: str
    price: float        # 指値価格
    quantity: float     # BTC量
    amount_jpy: float   # 円換算注文額
    status: str = STATUS_OPEN
    created_at: float = 0.0
    updated_at: float = 0.0
    is_dry_run: bool = True


class PendingOrderStore:
    """未約定注文の SQLite 永続化。"""

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
                CREATE TABLE IF NOT EXISTS pending_orders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id   TEXT NOT NULL UNIQUE,
                    symbol     TEXT NOT NULL,
                    side       TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    price      REAL NOT NULL,
                    quantity   REAL NOT NULL,
                    amount_jpy REAL NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'OPEN',
                    is_dry_run INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    def save(self, order: PendingOrder):
        now = time.time()
        order.created_at = order.created_at or now
        order.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pending_orders
                   (order_id, symbol, side, order_type, price, quantity,
                    amount_jpy, status, is_dry_run, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order.order_id, order.symbol, order.side, order.order_type,
                 order.price, order.quantity, order.amount_jpy,
                 order.status, int(order.is_dry_run), order.created_at, order.updated_at),
            )
        log.info(f"注文保存: {order.order_id} {order.symbol} {order.side} {order.status}")

    def update_status(self, order_id: str, status: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_orders SET status=?, updated_at=? WHERE order_id=?",
                (status, time.time(), order_id),
            )
        log.info(f"注文ステータス更新: {order_id} → {status}")

    def load_open(self, symbol: Optional[str] = None) -> List[PendingOrder]:
        query = "SELECT * FROM pending_orders WHERE status=?"
        params: list = [STATUS_OPEN]
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_order(r) for r in rows]

    def load_by_id(self, order_id: str) -> Optional[PendingOrder]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_orders WHERE order_id=?", (order_id,)
            ).fetchone()
        return self._row_to_order(row) if row else None

    def open_order_count(self, symbol: Optional[str] = None) -> int:
        return len(self.load_open(symbol))

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> PendingOrder:
        return PendingOrder(
            order_id=row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row["order_type"],
            price=row["price"],
            quantity=row["quantity"],
            amount_jpy=row["amount_jpy"],
            status=row["status"],
            is_dry_run=bool(row["is_dry_run"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
