# 実注文なし・研究用シグナルのみ
# このモジュールは実注文APIを一切呼びません。

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from src.fx.models import FXSignal
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fund.db"


class FXSignalStorage:
    """
    USD/JPY FXシグナルのSQLiteストレージ（研究用・実注文なし）
    既存の fund.db に fx_signals_usdjpy テーブルを追加する。
    """

    TABLE = "fx_signals_usdjpy"

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id   TEXT    UNIQUE NOT NULL,
                    symbol      TEXT    NOT NULL,
                    action      TEXT    NOT NULL,
                    price       REAL,
                    ask         REAL,
                    bid         REAL,
                    spread_pips REAL,
                    timestamp   TEXT,
                    reasons     TEXT,
                    stop_loss   REAL,
                    take_profit REAL,
                    skip_reason TEXT,
                    created_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
        log.debug(f"FXSignalStorage: テーブル '{self.TABLE}' 確認済み ({self.db_path})")

    def save(self, signal: FXSignal) -> bool:
        """
        シグナルを保存する。重複（同一 signal_id）の場合は False を返す。
        実注文は一切行わない。
        """
        reasons_json = json.dumps(signal.reasons, ensure_ascii=False)
        try:
            with self._connect() as conn:
                conn.execute(
                    f"""INSERT OR IGNORE INTO {self.TABLE}
                        (signal_id, symbol, action, price, ask, bid, spread_pips,
                         timestamp, reasons, stop_loss, take_profit, skip_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        signal.signal_id,
                        signal.symbol,
                        signal.action,
                        signal.price,
                        signal.ask,
                        signal.bid,
                        signal.spread_pips,
                        signal.timestamp,
                        reasons_json,
                        signal.stop_loss,
                        signal.take_profit,
                        signal.skip_reason,
                    ),
                )
                saved = conn.total_changes > 0
            if saved:
                log.info(
                    f"FXシグナル保存: {signal.signal_id} action={signal.action} price={signal.price}"
                )
            else:
                log.debug(f"FXシグナル重複スキップ: {signal.signal_id}")
            return saved
        except Exception as e:
            log.error(f"FXシグナル保存エラー: {e}")
            return False

    def list_signals(
        self,
        limit: int = 100,
        action_filter: Optional[str] = None,
    ) -> list[FXSignal]:
        """シグナル一覧を取得する（新しい順）"""
        try:
            with self._connect() as conn:
                if action_filter:
                    rows = conn.execute(
                        f"""SELECT * FROM {self.TABLE}
                            WHERE action = ?
                            ORDER BY created_at DESC LIMIT ?""",
                        (action_filter, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"""SELECT * FROM {self.TABLE}
                            ORDER BY created_at DESC LIMIT ?""",
                        (limit,),
                    ).fetchall()
            return [self._row_to_signal(r) for r in rows]
        except Exception as e:
            log.error(f"FXシグナル取得エラー: {e}")
            return []

    def get_latest(self, n: int = 10) -> list[FXSignal]:
        """最新 n 件を取得する"""
        return self.list_signals(limit=n)

    def _row_to_signal(self, row: sqlite3.Row) -> FXSignal:
        d = dict(row)
        try:
            reasons = json.loads(d.get("reasons") or "[]")
        except (json.JSONDecodeError, TypeError):
            reasons = []
        return FXSignal(
            signal_id=d["signal_id"],
            symbol=d["symbol"],
            action=d["action"],
            price=d.get("price") or 0.0,
            ask=d.get("ask") or 0.0,
            bid=d.get("bid") or 0.0,
            spread_pips=d.get("spread_pips") or 0.0,
            timestamp=d.get("timestamp") or "",
            reasons=reasons,
            stop_loss=d.get("stop_loss"),
            take_profit=d.get("take_profit"),
            skip_reason=d.get("skip_reason"),
        )
