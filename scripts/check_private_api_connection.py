"""
check_private_api_connection.py — GMOコイン Private API 接続確認スクリプト。

実行するだけで .env の APIキーが正しく設定されているか、
残高取得が成功するかを確認できる。

【安全設計】
- READ_ONLY=true（デフォルト）のため発注・キャンセルは絶対に呼ばない
- DRY_RUN フラグに関わらず残高取得のみ実行
- APIキー・シークレットはログに絶対に出力しない
- エラー時は安全停止（例外メッセージのみ表示）

使い方:
  python scripts/check_private_api_connection.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加（scripts/ から実行されるため）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brokers.gmo_private_adapter import load_adapter_from_env, MissingAPIKeyError
from src.utils.logger import get_logger

log = get_logger(__name__)


def main() -> int:
    """
    0: 接続成功
    1: APIキー未設定
    2: API通信エラー
    """
    log.info("=" * 60)
    log.info("GMOコイン Private API 接続確認 START")
    log.info("※ 残高取得のみ実行します（発注・キャンセルは行いません）")
    log.info("=" * 60)

    # Step 1: .env からアダプターを生成
    try:
        adapter = load_adapter_from_env()
    except MissingAPIKeyError as e:
        log.error(f"[設定エラー] {e}")
        log.error("→ .env に GMO_API_KEY と GMO_API_SECRET を設定してください")
        log.error("→ .env.example を参考に設定方法を確認してください")
        return 1

    # DRY_RUN の場合はモック接続のみ確認
    if adapter.dry_run:
        log.info("[DRY_RUN=true] モードで実行中 → API通信はスキップします")
        log.info("→ 実際のAPI接続テストは DRY_RUN=false に変更してください")
        log.info("→ ただし READ_ONLY=true のまま変更してください（発注防止）")
        return 0

    # Step 2: 残高取得（READ_ONLY=true でも呼べる）
    log.info("残高取得を試みます...")
    try:
        balance = adapter.get_balance()
    except Exception as e:
        log.error(f"[通信エラー] 残高取得に失敗しました: {e}")
        log.error("確認事項:")
        log.error("  1. GMO_API_KEY / GMO_API_SECRET が正しいか")
        log.error("  2. GMOコインで「現物取引（BTC/JPY）」のAPIが有効か")
        log.error("  3. IPアドレス制限が設定されている場合は解除または追加")
        return 2

    # Step 3: 結果表示（シークレット情報は絶対に出力しない）
    log.info("-" * 40)
    log.info("✅ Private API 接続成功！")
    log.info(f"  円残高 (JPY) : ¥{balance['jpy']:>15,.0f}")
    log.info(f"  BTC残高      : {balance['btc']:>20.8f} BTC")
    log.info(f"  BTC利用可能  : {balance['btc_available']:>20.8f} BTC")
    log.info("-" * 40)

    # READ_ONLY 状態の確認
    if adapter.read_only:
        log.info("🔒 READ_ONLY=true → 発注・キャンセルは保護されています（安全）")
    else:
        log.warning("⚠️  READ_ONLY=false → 発注・キャンセルが可能な状態です")
        log.warning("   実際のトレードを始める前に、十分なテストを行ってください")

    log.info("=" * 60)
    log.info("GMOコイン Private API 接続確認 DONE")
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
