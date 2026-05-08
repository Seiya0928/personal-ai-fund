"""
pre_live_checklist.py — 実発注前の最終チェックリスト。

全項目 OK になるまで実発注を絶対に開始しないこと。
このスクリプトが ALL OK を返して初めて READ_ONLY=false を検討する。

チェック項目:
  1.  DRY_RUN=false
  2.  READ_ONLY=false
  3.  STOP_TRADING ファイルが存在しない
  4.  GMO_API_KEY が設定されている
  5.  GMO_API_SECRET が設定されている
  6.  出金権限 → APIキーに出金権限を付与しないこと（運用上の確認）
  7.  max_order_amount_jpy <= 1,000 円
  8.  max_daily_orders <= 1 回
  9.  成行注文（MARKET）が許可リストにない
 10.  レバレッジ口座は利用しない（許可シンボルが BTC_JPY のみ）
 11.  注文タイプが LIMIT のみ
 12.  DB 接続成功
 13.  ログディレクトリへの書き込み可能
 14.  未処理（OPEN）の pending_orders が存在しない

使い方:
  python scripts/pre_live_checklist.py
"""
from __future__ import annotations

import os
import sys
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from src.risk.risk_config import load_config, RiskConfig
from src.risk.pending_orders import PendingOrderStore, DB_PATH
from src.utils.logger import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str


def run_checklist(
    config: RiskConfig = None,
    db_path: Path = DB_PATH,
    stop_trading_file: Path = None,
    env: dict = None,
) -> List[CheckResult]:
    """
    チェックリストを実行して CheckResult のリストを返す。
    all(r.ok for r in results) が True のとき全項目 OK。

    引数はすべてテスト用のオーバーライド。本番呼び出しでは省略可。
    """
    load_dotenv()

    if config is None:
        config = load_config()
    if stop_trading_file is None:
        stop_trading_file = config.stop_trading_file
    if env is None:
        env = os.environ

    results: List[CheckResult] = []

    # --- 1. DRY_RUN=false ---
    dry_run_val = env.get("DRY_RUN", "true").lower()
    dry_run_active = dry_run_val not in ("false", "0", "no")
    results.append(CheckResult(
        name="DRY_RUN=false",
        ok=not dry_run_active,
        message="OK: DRY_RUN=false" if not dry_run_active
                else "NG: DRY_RUN=true のままです。.env を DRY_RUN=false に変更してください",
    ))

    # --- 2. READ_ONLY=false ---
    read_only_val = env.get("READ_ONLY", "true").lower()
    read_only_active = read_only_val not in ("false", "0", "no")
    results.append(CheckResult(
        name="READ_ONLY=false",
        ok=not read_only_active,
        message="OK: READ_ONLY=false" if not read_only_active
                else "NG: READ_ONLY=true のままです。.env を READ_ONLY=false に変更してください",
    ))

    # --- 3. STOP_TRADING ファイルなし ---
    stop_exists = stop_trading_file.exists()
    results.append(CheckResult(
        name="STOP_TRADING なし",
        ok=not stop_exists,
        message="OK: STOP_TRADING ファイルなし" if not stop_exists
                else f"NG: {stop_trading_file} が存在します。rm STOP_TRADING で削除してください",
    ))

    # --- 4. GMO_API_KEY 設定済み ---
    api_key = env.get("GMO_API_KEY", "").strip()
    results.append(CheckResult(
        name="GMO_API_KEY 設定済み",
        ok=bool(api_key),
        message="OK: GMO_API_KEY が設定されています" if api_key
                else "NG: GMO_API_KEY が未設定です。.env に設定してください",
    ))

    # --- 5. GMO_API_SECRET 設定済み ---
    api_secret = env.get("GMO_API_SECRET", "").strip()
    results.append(CheckResult(
        name="GMO_API_SECRET 設定済み",
        ok=bool(api_secret),
        message="OK: GMO_API_SECRET が設定されています" if api_secret
                else "NG: GMO_API_SECRET が未設定です。.env に設定してください",
    ))

    # --- 6. 出金権限なし確認（運用上の確認項目）---
    # GMOコインのAPI設定で「出金」権限を付与していないことを手動確認する項目。
    # コードで自動判定できないため、実行者に確認を促す。
    # このチェックは環境変数 WITHDRAWAL_API_DISABLED=confirmed で通過させる。
    withdrawal_confirmed = env.get("WITHDRAWAL_API_DISABLED", "").lower() == "confirmed"
    results.append(CheckResult(
        name="出金権限なし（手動確認）",
        ok=withdrawal_confirmed,
        message="OK: 出金権限なしを確認済み" if withdrawal_confirmed
                else (
                    "NG: GMOコインのAPI設定で「出金」権限が無効であることを確認してください。\n"
                    "     確認後、.env に WITHDRAWAL_API_DISABLED=confirmed を追記してください"
                ),
    ))

    # --- 7. max_order_amount_jpy <= 1,000 円 ---
    amount_ok = config.max_order_amount_jpy <= 1_000.0
    results.append(CheckResult(
        name="最大注文額 ≤ ¥1,000",
        ok=amount_ok,
        message=f"OK: max_order_amount_jpy=¥{config.max_order_amount_jpy:,.0f}" if amount_ok
                else f"NG: max_order_amount_jpy=¥{config.max_order_amount_jpy:,.0f} が上限 ¥1,000 を超えています",
    ))

    # --- 8. max_daily_orders <= 1 回 ---
    orders_ok = config.max_daily_orders <= 1
    results.append(CheckResult(
        name="最大日次注文回数 ≤ 1",
        ok=orders_ok,
        message=f"OK: max_daily_orders={config.max_daily_orders}" if orders_ok
                else f"NG: max_daily_orders={config.max_daily_orders} が上限 1 を超えています",
    ))

    # --- 9. 成行注文（MARKET）が許可リストにない ---
    market_blocked = "MARKET" not in [t.upper() for t in config.allowed_order_types]
    results.append(CheckResult(
        name="成行注文（MARKET）禁止",
        ok=market_blocked,
        message="OK: MARKET は許可リストにありません" if market_blocked
                else "NG: allowed_order_types に MARKET が含まれています。LIMIT のみにしてください",
    ))

    # --- 10. 許可シンボルが BTC_JPY のみ（レバレッジ口座を誤って使わない）---
    symbols_ok = config.allowed_symbols == ["BTC_JPY"]
    results.append(CheckResult(
        name="許可シンボル BTC_JPY のみ",
        ok=symbols_ok,
        message="OK: BTC_JPY のみ" if symbols_ok
                else f"NG: allowed_symbols={config.allowed_symbols}。BTC_JPY のみにしてください",
    ))

    # --- 11. 注文タイプが LIMIT のみ ---
    types_ok = [t.upper() for t in config.allowed_order_types] == ["LIMIT"]
    results.append(CheckResult(
        name="注文タイプ LIMIT のみ",
        ok=types_ok,
        message="OK: LIMIT のみ" if types_ok
                else f"NG: allowed_order_types={config.allowed_order_types}。LIMIT のみにしてください",
    ))

    # --- 12. DB 接続成功 ---
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
        db_msg = f"OK: DB 接続成功 ({db_path})"
    except Exception as e:
        db_ok = False
        db_msg = f"NG: DB 接続失敗: {e}"
    results.append(CheckResult(name="DB 接続", ok=db_ok, message=db_msg))

    # --- 13. ログディレクトリへの書き込み可能 ---
    log_dir = ROOT / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
        test_file = log_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        log_ok = True
        log_msg = f"OK: ログ書き込み可能 ({log_dir})"
    except Exception as e:
        log_ok = False
        log_msg = f"NG: ログ書き込み不可: {e}"
    results.append(CheckResult(name="ログ書き込み可能", ok=log_ok, message=log_msg))

    # --- 14. 未処理（OPEN）の pending_orders が存在しない ---
    try:
        store = PendingOrderStore(db_path=db_path)
        open_count = store.open_order_count()
        pending_ok = open_count == 0
        pending_msg = "OK: 未処理注文なし" if pending_ok \
            else f"NG: OPEN 状態の注文が {open_count} 件残っています。watch_orders() で処理してから再実行してください"
    except Exception as e:
        pending_ok = False
        pending_msg = f"NG: pending_orders 確認失敗: {e}"
    results.append(CheckResult(name="未処理注文なし", ok=pending_ok, message=pending_msg))

    return results


def main() -> int:
    """0: 全項目 OK / 1: NG あり"""
    log.info("=" * 60)
    log.info("実発注前チェックリスト START")
    log.info("=" * 60)

    results = run_checklist()

    all_ok = True
    for r in results:
        status = "✅" if r.ok else "❌"
        log.info(f"{status} [{r.name}] {r.message}")
        if not r.ok:
            all_ok = False

    log.info("-" * 60)
    if all_ok:
        log.info("✅ ALL OK — 全チェック通過。rehearse_live_order.py を実行してください。")
        log.info("   その後に初めて READ_ONLY=false を検討してください。")
    else:
        ng_count = sum(1 for r in results if not r.ok)
        log.error(f"❌ {ng_count} 項目が NG です。上記を修正してから再実行してください。")
        log.error("   NG が残っている間は絶対に実発注しないでください。")
    log.info("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
