"""
rehearse_live_order.py — 実発注リハーサル。

実際のAPIには発注リクエストを送らずに、発注フローを最初から最後まで通す。
本番と同じ順番で:
  1. pre_trade_sync()    — 口座状態取得（DRY_RUN=true のためモック）
  2. check_order_allowed() — リスクチェック
  3. place_order() は呼ばない — 注文予定内容だけ表示
  4. SQLite に rehearsal として保存
  5. 「これはリハーサルです」と表示

目的:
  口座開通後・実発注前の最終確認に使う。
  リハーサルが問題なく通って初めて rehearse_live_order.py の役目が終わる。
  その後、READ_ONLY=false に変更して初回実発注に臨む。

使い方:
  python scripts/rehearse_live_order.py
"""
from __future__ import annotations

import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from src.risk.risk_manager import RiskManager
from src.risk.risk_config import load_config
from src.risk.order_sizing import size_btc_jpy_limit_buy
from src.risk.pending_orders import DB_PATH
from src.utils.logger import get_logger

load_dotenv()

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[1]

# リハーサル用の注文パラメーター（最小単位・最低額）
REHEARSAL_SYMBOL     = "BTC_JPY"
REHEARSAL_SIDE       = "BUY"
REHEARSAL_ORDER_TYPE = "LIMIT"
REHEARSAL_AMOUNT_JPY = 1_000.0   # 最大注文額の上限いっぱい


@dataclass
class RehearsalRecord:
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: float
    amount_jpy: float
    risk_check_passed: bool
    risk_check_reason: str
    rehearsed_at: float


class RehearsalStore:
    """リハーサル記録の SQLite 永続化。"""

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
                CREATE TABLE IF NOT EXISTS rehearsals (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol             TEXT NOT NULL,
                    side               TEXT NOT NULL,
                    order_type         TEXT NOT NULL,
                    price              REAL NOT NULL,
                    quantity           REAL NOT NULL,
                    amount_jpy         REAL NOT NULL,
                    risk_check_passed  INTEGER NOT NULL DEFAULT 0,
                    risk_check_reason  TEXT NOT NULL DEFAULT '',
                    rehearsed_at       REAL NOT NULL
                )
            """)

    def save(self, record: RehearsalRecord):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO rehearsals
                   (symbol, side, order_type, price, quantity, amount_jpy,
                    risk_check_passed, risk_check_reason, rehearsed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.symbol, record.side, record.order_type,
                    record.price, record.quantity, record.amount_jpy,
                    int(record.risk_check_passed), record.risk_check_reason,
                    record.rehearsed_at,
                ),
            )
        log.info(f"リハーサル記録保存: {record.symbol} {record.side} {record.quantity:.8f} @ ¥{record.price:,.0f}")

    def load_all(self) -> list:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM rehearsals ORDER BY rehearsed_at DESC"
            ).fetchall()


def get_current_price() -> Optional[float]:
    """Public API から現在価格を取得（接続失敗時は None）。"""
    try:
        import requests
        resp = requests.get(
            "https://api.coin.z.com/public/v1/ticker",
            params={"symbol": "BTC_JPY"},
            timeout=5,
        )
        data = resp.json()
        if data.get("status") == 0:
            items = data.get("data", [])
            if items:
                return float(items[0].get("last", 0))
    except Exception:
        pass
    return None


def run_rehearsal(
    db_path: Path = DB_PATH,
    current_price: Optional[float] = None,
) -> RehearsalRecord:
    """
    リハーサルを実行して RehearsalRecord を返す。
    place_order() は呼ばない（実 API への発注リクエストなし）。
    """
    # RiskManager は常に DRY_RUN=true で起動（リハーサルなので）
    config = load_config()
    config.dry_run = True   # リハーサルは必ず DRY_RUN
    rm = RiskManager(config=config, db_path=db_path)

    # Step 1: pre_trade_sync（DRY_RUN=true → モックデータを返す）
    state = rm.pre_trade_sync(REHEARSAL_SYMBOL)
    log.info(f"[リハーサル Step1] pre_trade_sync 完了: btc_held={state.btc_held:.8f} jpy={state.balance_jpy:,.0f}")

    # Step 2: 現在価格を取得（失敗時はフォールバック価格を使う）
    if current_price is None:
        current_price = get_current_price()
    if current_price is None or current_price <= 0:
        log.warning("[リハーサル] 現在価格の取得に失敗しました。フォールバック価格 ¥10,000,000 を使用します")
        current_price = 10_000_000.0

    sized_order = size_btc_jpy_limit_buy(
        target_amount_jpy=REHEARSAL_AMOUNT_JPY,
        reference_price_jpy=current_price,
    )

    log.info(
        f"[リハーサル] 想定注文: {REHEARSAL_SYMBOL} {REHEARSAL_SIDE} "
        f"{sized_order.quantity:.8f} BTC @ ¥{sized_order.price:,.0f}"
    )
    log.info(
        f"[リハーサル] 注文金額: ¥{sized_order.amount_jpy:,.0f} "
        f"(target=¥{REHEARSAL_AMOUNT_JPY:,.0f})"
    )

    # Step 3: check_order_allowed（リスクチェック）
    result = rm.check_order_allowed(
        symbol=REHEARSAL_SYMBOL,
        side=REHEARSAL_SIDE,
        order_type=REHEARSAL_ORDER_TYPE,
        amount_jpy=sized_order.amount_jpy,
        current_price_jpy=sized_order.price,
        state=state,
    )
    log.info(f"[リハーサル Step2] リスクチェック: {result}")

    # Step 4: place_order() は呼ばない → 注文予定内容だけ表示
    log.info("")
    log.info("=" * 60)
    log.info("【注文予定内容（実際には送信しません）】")
    log.info(f"  シンボル   : {REHEARSAL_SYMBOL}")
    log.info(f"  売買方向   : {REHEARSAL_SIDE}")
    log.info(f"  注文タイプ : {REHEARSAL_ORDER_TYPE}")
    log.info(f"  指値価格   : ¥{sized_order.price:>15,.0f}")
    log.info(f"  数量       : {sized_order.quantity:.8f} BTC")
    log.info(f"  注文金額   : ¥{sized_order.amount_jpy:>10,.0f}")
    log.info(f"  リスクチェック結果: {'✅ ALLOWED' if result.allowed else '❌ BLOCKED'} — {result.reason}")
    log.info("=" * 60)
    log.info("")

    # Step 5: SQLite に rehearsal として保存
    record = RehearsalRecord(
        symbol=REHEARSAL_SYMBOL,
        side=REHEARSAL_SIDE,
        order_type=REHEARSAL_ORDER_TYPE,
        price=sized_order.price,
        quantity=sized_order.quantity,
        amount_jpy=sized_order.amount_jpy,
        risk_check_passed=result.allowed,
        risk_check_reason=result.reason,
        rehearsed_at=time.time(),
    )
    store = RehearsalStore(db_path=db_path)
    store.save(record)

    return record


def main() -> int:
    log.info("=" * 60)
    log.info("実発注リハーサル START")
    log.info("※ このスクリプトは実際の注文を送信しません")
    log.info("=" * 60)

    record = run_rehearsal()

    log.info("")
    log.info("=" * 60)
    log.info("【重要】これはリハーサルです。実注文は送信していません。")
    log.info("")
    if record.risk_check_passed:
        log.info("✅ リスクチェック通過。リハーサル完了。")
        log.info("")
        log.info("次のステップ（実発注の準備）:")
        log.info("  1. scripts/pre_live_checklist.py が ALL OK であることを確認")
        log.info("  2. GMOコインのAPI設定で「出金」権限が無効であることを確認")
        log.info("  3. .env の READ_ONLY=false に変更")
        log.info("  4. 初回発注は ¥1,000 の指値注文から")
        log.info("  5. 発注直後に GMOコインの管理画面で注文を確認")
    else:
        log.warning(f"❌ リスクチェック NG: {record.risk_check_reason}")
        log.warning("   上記の問題を解決してから再実行してください。")
    log.info("=" * 60)

    return 0 if record.risk_check_passed else 1


if __name__ == "__main__":
    sys.exit(main())
