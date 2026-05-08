import sqlite3
import time
from pathlib import Path
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fund.db"


class DuplicateOrderGuard:
    """同一内容（symbol+side+order_type+amount_jpy）の注文を一定時間ブロックする。"""

    def __init__(self, db_path: Path = DB_PATH, guard_seconds: int = 60):
        self.db_path = db_path
        self.guard_seconds = guard_seconds
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS order_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol       TEXT NOT NULL,
                    side         TEXT NOT NULL,
                    order_type   TEXT NOT NULL,
                    amount_jpy   REAL NOT NULL,
                    is_dry_run   INTEGER NOT NULL DEFAULT 1,
                    status       TEXT NOT NULL DEFAULT 'simulated',
                    created_at   REAL NOT NULL
                )
            """)

    def is_duplicate(self, symbol: str, side: str, order_type: str, amount_jpy: float) -> bool:
        cutoff = time.time() - self.guard_seconds
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id FROM order_log
                   WHERE symbol=? AND side=? AND order_type=? AND amount_jpy=?
                     AND created_at > ?
                   LIMIT 1""",
                (symbol, side, order_type, amount_jpy, cutoff),
            ).fetchone()
        if row:
            log.warning(f"重複注文ブロック: {symbol} {side} {order_type} ¥{amount_jpy} (直近{self.guard_seconds}秒以内に同一注文)")
            return True
        return False

    def record(self, symbol: str, side: str, order_type: str, amount_jpy: float,
               is_dry_run: bool = True, status: str = "simulated"):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO order_log (symbol, side, order_type, amount_jpy, is_dry_run, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (symbol, side, order_type, amount_jpy, int(is_dry_run), status, time.time()),
            )
        log.info(f"注文ログ記録: {symbol} {side} {order_type} ¥{amount_jpy} dry_run={is_dry_run} status={status}")

    def today_order_count(self) -> int:
        import datetime
        today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM order_log WHERE created_at >= ?",
                (today_start,),
            ).fetchone()
        return row[0]
