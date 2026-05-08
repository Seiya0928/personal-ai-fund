import sqlite3
import csv
from pathlib import Path
from typing import Optional
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fund.db"


class SQLiteStore:
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
                CREATE TABLE IF NOT EXISTS ticker (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT    NOT NULL,
                    ask       REAL,
                    bid       REAL,
                    last      REAL,
                    volume    REAL,
                    timestamp TEXT    NOT NULL,
                    UNIQUE(symbol, timestamp)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT NOT NULL,
                    interval  TEXT NOT NULL,
                    open      REAL,
                    high      REAL,
                    low       REAL,
                    close     REAL,
                    volume    REAL,
                    timestamp TEXT NOT NULL,
                    UNIQUE(symbol, interval, timestamp)
                )
            """)

    def save_ticker(self, ticker: dict) -> bool:
        """重複（symbol + timestamp）は無視して保存。保存できたら True を返す。"""
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO ticker (symbol, ask, bid, last, volume, timestamp)
                       VALUES (:symbol, :ask, :bid, :last, :volume, :timestamp)""",
                    ticker,
                )
                saved = conn.total_changes > 0
            if saved:
                log.info(f"ticker保存: {ticker['symbol']} last={ticker['last']} ts={ticker['timestamp']}")
            else:
                log.debug(f"ticker重複スキップ: {ticker['symbol']} ts={ticker['timestamp']}")
            return saved
        except Exception as e:
            log.error(f"ticker保存エラー: {e}")
            return False

    def save_ohlcv(self, rows: list[dict], symbol: str, interval: str) -> int:
        """OHLCVをまとめて保存。重複はスキップ。保存件数を返す。"""
        saved = 0
        try:
            with self._connect() as conn:
                for row in rows:
                    before = conn.execute("SELECT changes()").fetchone()[0]
                    conn.execute(
                        """INSERT OR IGNORE INTO ohlcv
                           (symbol, interval, open, high, low, close, volume, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (symbol, interval, row["open"], row["high"], row["low"],
                         row["close"], row["volume"], row["timestamp"]),
                    )
                    saved += conn.execute("SELECT changes()").fetchone()[0]
            log.info(f"OHLCV保存: {saved}件 ({symbol} {interval})")
        except Exception as e:
            log.error(f"OHLCV保存エラー: {e}")
        return saved

    def load_ohlcv(self, symbol: str, interval: str, limit: int = 500) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT open, high, low, close, volume, timestamp
                   FROM ohlcv WHERE symbol=? AND interval=?
                   ORDER BY timestamp DESC LIMIT ?""",
                (symbol, interval, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def load_latest_ticker(self, symbol: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT symbol, ask, bid, last, volume, timestamp
                   FROM ticker WHERE symbol=?
                   ORDER BY timestamp DESC LIMIT 1""",
                (symbol,),
            ).fetchone()
        return dict(row) if row else None

    def export_ohlcv_csv(self, symbol: str, interval: str, out_path: Path) -> Path:
        rows = self.load_ohlcv(symbol, interval, limit=10000)
        out_path.parent.mkdir(exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)
        log.info(f"CSVエクスポート: {out_path} ({len(rows)}件)")
        return out_path
