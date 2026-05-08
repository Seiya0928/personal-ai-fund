"""
live_order_once.py — 1回だけ実発注するための専用スクリプト。

【重要な制限】
  - このスクリプトは1回の実行で1件だけ発注して終了する
  - 自動ループ・定期実行は禁止
  - 注文タイプは LIMIT（指値）のみ
  - 注文金額は最大 ¥1,000
  - 成行（MARKET）・レバレッジは禁止

実行順序:
  1. pre_live_checklist   — 全安全項目を確認
  2. pre_trade_sync()     — 口座残高・ポジションを同期
  3. check_order_allowed() — リスクチェック
  4. manual_approval      — 端末への手動承認入力（必須）
  5. place_order()        — 実際の発注
  6. watch_orders()       — 約定・タイムアウトを監視（最大で config の order_timeout_seconds 秒）
  7. post_trade_report    — 発注後検証レポートを生成・保存

使い方:
  python scripts/live_order_once.py

環境変数（.env）:
  DRY_RUN=false
  READ_ONLY=false
  GMO_API_KEY=...
  GMO_API_SECRET=...
  WITHDRAWAL_API_DISABLED=confirmed
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from scripts.pre_live_checklist import run_checklist
from src.brokers.gmo_private_adapter import load_adapter_from_env
from src.risk.risk_config import load_config
from src.risk.risk_manager import RiskManager
from src.risk.order_sizing import size_btc_jpy_limit_buy
from src.risk.order_executor import ManualApprovalDeniedError
from src.risk.post_trade_reporter import generate_report, generate_failed_order_report, save_report
from src.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 注文パラメーター（変更時は必ず pre_live_checklist.py も通すこと）
# ---------------------------------------------------------------------------
SYMBOL     = "BTC_JPY"
SIDE       = "BUY"
ORDER_TYPE = "LIMIT"
AMOUNT_JPY = 1_000.0   # 最大注文額上限いっぱいの ¥1,000


def get_current_price() -> float:
    """Public API から現在価格を取得する。失敗したら RuntimeError。"""
    import requests
    resp = requests.get(
        "https://api.coin.z.com/public/v1/ticker",
        params={"symbol": SYMBOL},
        timeout=5,
    )
    data = resp.json()
    if data.get("status") != 0:
        raise RuntimeError(f"価格取得失敗: {data}")
    items = data.get("data", [])
    if not items:
        raise RuntimeError("価格データが空です")
    price = float(items[0].get("last", 0))
    if price <= 0:
        raise RuntimeError(f"不正な価格: {price}")
    return price


def main() -> int:
    """0: 発注・監視完了 / 1: 中止（安全）"""
    log.info("=" * 60)
    log.info("live_order_once.py — 実発注スクリプト")
    log.info("  ※ このスクリプトは1回実行したら終了します")
    log.info("  ※ 自動ループ・定期実行は禁止です")
    log.info("=" * 60)

    # -----------------------------------------------------------------------
    # Step 1: pre_live_checklist — 全安全項目確認
    # -----------------------------------------------------------------------
    log.info("[Step 1] 発注前チェックリスト実行...")
    results = run_checklist()
    failed = [r for r in results if not r.ok]
    if failed:
        log.error("❌ チェックリストに NG があります。以下を修正してから再実行してください:")
        for r in failed:
            log.error(f"   [{r.name}] {r.message}")
        return 1
    log.info("✅ チェックリスト: 全項目 OK")

    # -----------------------------------------------------------------------
    # Step 2: アダプター・RiskManager を初期化
    # -----------------------------------------------------------------------
    log.info("[Step 2] アダプター初期化...")
    try:
        adapter = load_adapter_from_env()
    except Exception as e:
        log.error(f"❌ アダプター初期化失敗: {e}")
        return 1

    if adapter.dry_run:
        log.error("❌ DRY_RUN=true です。.env を DRY_RUN=false に変更してください。")
        return 1
    if adapter.read_only:
        log.error("❌ READ_ONLY=true です。.env を READ_ONLY=false に変更してください。")
        return 1

    config = load_config()
    rm = RiskManager(config=config, adapter=adapter)
    log.info("✅ アダプター初期化完了")
    state = None

    # -----------------------------------------------------------------------
    # Step 3: 現在価格を取得
    # -----------------------------------------------------------------------
    log.info("[Step 3] 現在価格取得...")
    try:
        current_price = get_current_price()
    except Exception as e:
        log.error(f"❌ 価格取得失敗: {e}")
        return 1
    try:
        sized_order = size_btc_jpy_limit_buy(
            target_amount_jpy=AMOUNT_JPY,
            reference_price_jpy=current_price,
        )
    except ValueError as e:
        log.error(f"❌ 注文サイズ計算失敗: {e}")
        return 1
    log.info(
        f"✅ 現在価格: ¥{current_price:,.0f} → 指値価格: ¥{sized_order.price:,.0f} "
        f"数量: {sized_order.quantity:.8f} BTC 注文額: ¥{sized_order.amount_jpy:,.0f}"
    )

    # -----------------------------------------------------------------------
    # Step 4: pre_trade_sync — 残高・ポジション同期
    # -----------------------------------------------------------------------
    log.info("[Step 4] 口座状態同期...")
    try:
        state = rm.pre_trade_sync(SYMBOL)
    except Exception as e:
        log.error(f"❌ 口座同期失敗: {e}")
        return 1
    log.info(f"✅ 同期完了: BTC={state.btc_held:.8f} 円残高=¥{state.balance_jpy:,.0f}")

    # -----------------------------------------------------------------------
    # Step 5: check_order_allowed — リスクチェック
    # -----------------------------------------------------------------------
    log.info("[Step 5] リスクチェック...")
    result = rm.check_order_allowed(
        symbol=SYMBOL,
        side=SIDE,
        order_type=ORDER_TYPE,
        amount_jpy=sized_order.amount_jpy,
        current_price_jpy=sized_order.price,
        state=state,
    )
    log.info(f"リスクチェック結果: {result}")
    if not result.allowed:
        log.error(f"❌ リスクチェック NG: {result.reason}")
        return 1
    log.info("✅ リスクチェック: OK")

    # -----------------------------------------------------------------------
    # Step 6: place_order — 手動承認ゲート + 実発注
    #   manual_approval は OrderExecutor 内部で呼ばれる
    # -----------------------------------------------------------------------
    log.info("[Step 6] 発注（手動承認が必要です）...")
    try:
        pending = rm.place_order(
            symbol=SYMBOL,
            side=SIDE,
            order_type=ORDER_TYPE,
            price=sized_order.price,
            quantity=sized_order.quantity,
            amount_jpy=sized_order.amount_jpy,
        )
    except ManualApprovalDeniedError as e:
        log.warning(f"⛔ 発注中止: {e}")
        return 1
    except Exception as e:
        log.error(f"❌ 発注失敗: {e}")
        if state is not None:
            try:
                report = generate_failed_order_report(
                    symbol=SYMBOL,
                    side=SIDE,
                    order_type=ORDER_TYPE,
                    order_price=sized_order.price,
                    order_quantity=sized_order.quantity,
                    order_amount_jpy=sized_order.amount_jpy,
                    state_before=state,
                    config=config,
                    errors=[str(e)],
                )
                md_path, _ = save_report(report)
                log.info(f"⚠️  発注失敗レポート保存: {md_path}")
            except Exception as report_error:
                log.error(f"⚠️  発注失敗レポート生成失敗: {report_error}")
        return 1

    log.info(f"✅ 発注完了: order_id={pending.order_id}")

    # -----------------------------------------------------------------------
    # Step 7: watch_orders — 約定・タイムアウト監視
    # -----------------------------------------------------------------------
    log.info("[Step 7] 約定監視（GMOコインの管理画面でも確認してください）...")
    timeout = config.order_timeout_seconds
    interval = config.polling_interval_seconds
    deadline = time.time() + timeout

    while time.time() < deadline:
        processed = rm.watch_orders()
        if pending.order_id in processed:
            updated = rm.pending_store.load_by_id(pending.order_id)
            log.info(f"注文処理完了: order_id={pending.order_id} status={updated.status if updated else '?'}")
            break
        log.debug(f"監視中... 残り {deadline - time.time():.0f}秒")
        time.sleep(interval)
    else:
        log.warning(f"⚠️  タイムアウト({timeout}秒)。注文 {pending.order_id} は未処理のままです。")
        log.warning("   GMOコインの管理画面で注文状態を確認してください。")

    # -----------------------------------------------------------------------
    # Step 8: post_trade_report — 発注後検証レポートを生成・保存
    #   レポート生成失敗は発注処理の結果に影響しない（独立したステップ）
    # -----------------------------------------------------------------------
    log.info("[Step 8] 発注後検証レポート生成...")
    try:
        # watch_orders 後の最新状態を取得
        state_after = rm.pre_trade_sync(SYMBOL)
        report = generate_report(
            order_id=pending.order_id,
            state_before=state,
            state_after=state_after,
            config=config,
            db_path=rm.pending_store.db_path,
            adapter=adapter,
        )
        md_path, log_path = save_report(report)
        log.info(f"✅ レポート保存: {md_path}")
        next_label = "✅ OK" if report.next_order_allowed else "❌ NG"
        log.info(f"次回発注可否: {next_label}")
        if report.next_order_blocked_reasons:
            for reason in report.next_order_blocked_reasons:
                log.warning(f"  NG理由: {reason}")
    except Exception as e:
        log.error(f"⚠️  レポート生成失敗（発注処理は完了済み）: {e}")

    log.info("=" * 60)
    log.info("live_order_once.py 終了。次の実発注は改めて本スクリプトを実行してください。")
    log.info("次回発注前に reports/ のレポートで「次回発注可否 OK」を確認すること。")
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
