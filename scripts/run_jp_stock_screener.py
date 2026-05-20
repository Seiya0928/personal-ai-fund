#!/usr/bin/env python3
"""日本株スクリーニング bot — メインエントリーポイント。

実行方法:
    ./venv/bin/python scripts/run_jp_stock_screener.py
    ./venv/bin/python scripts/run_jp_stock_screener.py --send-email
    ./venv/bin/python scripts/run_jp_stock_screener.py --dry-run-notify

禁止事項:
    - 実注文・証券API発注は一切行わない
    - DRY_RUN / READ_ONLY を false にしない
    - 信用取引・空売りは扱わない
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.jp_stocks.fetcher import DATA_SOURCE, STOCK_UNIVERSE, fetch_all_quotes
from src.jp_stocks.notifier import send_screening_email
from src.jp_stocks.reporter import generate_report, save_report
from src.jp_stocks.screener import run_screening
from src.jp_stocks.signal_history import append_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="日本株スクリーニング bot（実注文なし・研究用）")
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="スクリーニング結果をメール送信する",
    )
    parser.add_argument(
        "--dry-run-notify",
        action="store_true",
        help="送信せずメール本文プレビューを CLI に出力する",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 55)
    logger.info("日本株スクリーニング bot 開始")
    logger.info(f"対象銘柄数: {len(STOCK_UNIVERSE)}")
    logger.info("※ 実注文なし・研究用スクリーニングのみ")
    if args.send_email:
        logger.info("メール通知: 有効 (--send-email)")
    if args.dry_run_notify:
        logger.info("メール通知: dry-run プレビューモード (--dry-run-notify)")
    logger.info("=" * 55)

    # Step 1: データ取得
    logger.info("Step 1/4: yfinance からデータ取得中...")
    quotes, errors = fetch_all_quotes()

    # Step 2: スクリーニング
    logger.info("Step 2/4: スクリーニング実行中...")
    result = run_screening(quotes, errors, data_source=DATA_SOURCE)

    logger.info(
        f"結果: CANDIDATE={result.candidate_count} / "
        f"WATCH={result.watch_count} / "
        f"SKIP={result.skip_count} / "
        f"エラー={len(errors)}"
    )

    # Step 3: レポート生成・保存
    logger.info("Step 3/4: レポート生成中...")
    report_text = generate_report(result)
    report_path = save_report(result, report_text)
    logger.info(f"レポート: {report_path}")

    # Step 4: 履歴保存
    logger.info("Step 4/4: 履歴保存中...")
    append_result(result)

    # Step 5: メール通知
    email_result = send_screening_email(
        result=result,
        report_path=report_path,
        requested=args.send_email or args.dry_run_notify,
        dry_run_notify=args.dry_run_notify,
    )

    # ── サマリー表示 ─────────────────────────────────────────────────
    logger.info("=" * 55)
    logger.info("スクリーニング完了")

    if result.candidate_signals:
        logger.info(f"=== JP_STOCK_CANDIDATE ({result.candidate_count} 件) ===")
        for sig in result.candidate_signals:
            q = sig.quote
            if q:
                logger.info(
                    f"  {q.code} {q.name}: "
                    f"{q.gap_rate:+.1f}% / 出来高比 {q.volume_ratio:.1f}x"
                )
                for reason in sig.reasons:
                    logger.info(f"    → {reason}")

    if result.watch_signals:
        logger.info(f"=== JP_STOCK_WATCH ({result.watch_count} 件) ===")
        for sig in result.watch_signals:
            logger.info(f"  {sig.code} {sig.name}: {'; '.join(sig.reasons)}")

    if not result.candidate_signals and not result.watch_signals:
        logger.info("本日の候補銘柄はありません。")

    if result.is_stale:
        logger.warning("⚠️  データが stale 状態です。yfinance のデータ更新を確認してください。")

    if errors:
        logger.warning(f"⚠️  データ取得エラー {len(errors)} 件")

    # ── メール結果表示 ────────────────────────────────────────────────
    if args.dry_run_notify and email_result.payload_preview:
        print("")
        print("── メール本文プレビュー ──────────────────────────────")
        print(f"件名: {email_result.payload_preview['subject']}")
        print("─" * 52)
        print(email_result.payload_preview["body"])
        print("─" * 52)

    if args.send_email or args.dry_run_notify:
        if email_result.skipped_reason == "EMAIL_SMTP_CONFIG not set":
            logger.warning("メール通知スキップ: EMAIL_SMTP_CONFIG not set")
            logger.warning("  .env に ALERT_EMAIL_SMTP_HOST / PORT / USERNAME / PASSWORD / FROM / TO を設定してください")
        elif email_result.sent:
            logger.info("メール送信成功")
        elif email_result.skipped_reason == "dry_run_notify=true":
            logger.info("メール送信スキップ (dry-run)")
        elif email_result.error:
            logger.error(f"メール送信失敗: {email_result.error}")
        else:
            logger.info(f"メール送信スキップ: {email_result.skipped_reason}")

    logger.info("")
    logger.info("Next Action:")
    logger.info("  JP_STOCK_CANDIDATE → チャート・出来高・板を人間が確認する。実注文しない。")
    logger.info("  JP_STOCK_WATCH     → チャート確認のみ。手動売買しない。")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
