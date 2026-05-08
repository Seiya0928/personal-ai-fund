"""
post_trade_report.py — 最後の発注に対するレポートを生成するスクリプト。

live_order_once.py が終了した後に手動で実行しても使える。
pending_orders テーブルの最新注文を対象にレポートを生成する。

使い方:
  python scripts/post_trade_report.py
  python scripts/post_trade_report.py --order-id ORDER_ID
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

import sqlite3
from src.risk.risk_config import load_config
from src.risk.execution_state import ExecutionState, ExecutionStore
from src.risk.pending_orders import PendingOrderStore, DB_PATH
from src.risk.post_trade_reporter import generate_report, save_report
from src.utils.logger import get_logger

log = get_logger(__name__)


def _get_latest_order_id(db_path: Path) -> str | None:
    """pending_orders テーブルから最新の order_id を返す。"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT order_id FROM pending_orders ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row["order_id"] if row else None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="発注後検証レポートを生成する")
    parser.add_argument(
        "--order-id", default=None,
        help="レポート対象の order_id（省略時は最新注文）",
    )
    args = parser.parse_args()

    config = load_config()

    order_id = args.order_id
    if order_id is None:
        order_id = _get_latest_order_id(DB_PATH)
        if order_id is None:
            log.error("pending_orders に注文が見つかりません。live_order_once.py を先に実行してください。")
            return 1
        log.info(f"最新注文を対象にします: order_id={order_id}")

    # adapter（DRY_RUN=false かつ APIキー設定済みなら API 残高確認あり）
    adapter = None
    if not config.dry_run:
        try:
            from src.brokers.gmo_private_adapter import load_adapter_from_env
            adapter = load_adapter_from_env()
        except Exception as e:
            log.warning(f"アダプター初期化失敗（API残高確認はスキップ）: {e}")

    # 現在の state を DB から復元（最簡易）
    exec_store = ExecutionStore(db_path=DB_PATH)
    state_now = ExecutionState()
    for ex in exec_store.load_today():
        state_now.apply_execution(ex)

    report = generate_report(
        order_id=order_id,
        state_before=state_now,   # 事後レポートのため before も同じ値を使う
        state_after=state_now,
        config=config,
        adapter=adapter,
    )

    md_path, log_path = save_report(report)

    log.info(f"レポート: {md_path}")
    log.info(f"ログ: {log_path}")
    next_label = "✅ OK" if report.next_order_allowed else "❌ NG"
    log.info(f"次回発注可否: {next_label}")
    if report.next_order_blocked_reasons:
        for reason in report.next_order_blocked_reasons:
            log.warning(f"  NG理由: {reason}")

    return 0 if report.next_order_allowed else 1


if __name__ == "__main__":
    sys.exit(main())
