# 実注文なし・研究用スクリーニング通知のみ
# このモジュールは実注文APIを一切呼びません。
from __future__ import annotations

import smtplib
import logging
from pathlib import Path
from typing import Optional

from src.alerts.email_notifier import (
    EmailSendResult,
    build_email_payload,
    load_email_config_from_env,
    send_email_via_smtp,
)
from src.jp_stocks.models import JP_STOCK_CANDIDATE, JP_STOCK_WATCH, ScreeningResult

logger = logging.getLogger(__name__)

SEP = "─" * 52


def build_subject(result: ScreeningResult) -> str:
    """スクリーニング結果に応じたメール件名を返す。"""
    if result.candidate_count >= 1:
        return (
            f"【JP Stock Screener】候補あり: "
            f"CANDIDATE={result.candidate_count} WATCH={result.watch_count}"
        )
    if result.watch_count >= 1:
        return f"【JP Stock Screener】監視銘柄あり: WATCH={result.watch_count}"
    return "【JP Stock Screener】候補なし"


def build_body(result: ScreeningResult, report_path: Optional[Path] = None) -> str:
    """スクリーニング結果のメール本文（プレーンテキスト）を生成する。"""
    run_str = result.run_at.strftime("%Y-%m-%d %H:%M:%S JST")
    lines: list[str] = []

    lines += [
        "日本株スクリーニング結果",
        "",
        f"実行日時    : {run_str}",
        f"データ取得元: {result.data_source}",
        f"対象銘柄数  : {result.total_screened} 銘柄",
        f"CANDIDATE  : {result.candidate_count} 件",
        f"WATCH      : {result.watch_count} 件",
        f"エラー      : {len(result.errors)} 件",
        f"データ状態  : {'stale（古い）' if result.is_stale else 'fresh'}",
    ]
    if report_path:
        lines.append(f"レポート    : {report_path}")

    # CANDIDATE セクション
    lines += ["", SEP, f"JP_STOCK_CANDIDATE ({result.candidate_count} 件)", SEP, ""]
    if result.candidate_signals:
        for i, sig in enumerate(result.candidate_signals[:10], 1):
            q = sig.quote
            if q:
                lines += [
                    f"[{i}] {q.code} {q.name}  ({q.market} / {q.sector})",
                    f"    現在値  : {q.current_price:>10,.0f} 円   前日比: {q.gap_rate:+.1f}%",
                    f"    出来高比: {q.volume_ratio:>8.1f} x    売買代金: {q.turnover_jpy / 1e8:.1f} 億円",
                ]
                for reason in sig.reasons:
                    lines.append(f"    理由    : {reason}")
                lines.append("")
    else:
        lines += ["本日の候補銘柄はありません。", ""]

    # WATCH セクション
    lines += [SEP, f"JP_STOCK_WATCH ({result.watch_count} 件)", SEP, ""]
    if result.watch_signals:
        for i, sig in enumerate(result.watch_signals[:10], 1):
            q = sig.quote
            if q:
                lines += [
                    f"[{i}] {q.code} {q.name}  ({q.market} / {q.sector})",
                    f"    前日比: {q.gap_rate:+.1f}%   出来高比: {q.volume_ratio:.1f}x",
                ]
                for reason in sig.reasons:
                    lines.append(f"    理由: {reason}")
                lines.append("")
    else:
        lines += ["監視銘柄はありません。", ""]

    # Next Action
    lines += [
        SEP,
        "Next Action",
        SEP,
        "",
        "JP_STOCK_CANDIDATE → チャート・出来高・板を人間が確認する。実注文しない。",
        "JP_STOCK_WATCH     → チャート確認のみ。手動売買しない。",
        "候補なし            → 何もしない。記録のみ。",
        "",
        SEP,
        "実注文は行いません。これは研究用スクリーニング通知です。",
        SEP,
    ]

    # エラーがあれば付記
    if result.errors:
        lines += ["", f"データ取得エラー ({len(result.errors)} 件):"]
        for err in result.errors[:5]:
            lines.append(f"  - {err}")
        if len(result.errors) > 5:
            lines.append(f"  ... 他 {len(result.errors) - 5} 件")

    return "\n".join(lines)


def send_screening_email(
    result: ScreeningResult,
    report_path: Optional[Path] = None,
    requested: bool = False,
    dry_run_notify: bool = False,
    config=None,
) -> EmailSendResult:
    """スクリーニング結果をメール送信する（または dry-run プレビューを返す）。

    Parameters
    ----------
    requested : bool
        --send-email フラグが指定された場合 True
    dry_run_notify : bool
        --dry-run-notify フラグが指定された場合 True。送信せずプレビューのみ。
    config : EmailConfig | None
        None の場合は環境変数から自動ロード。
    """
    if config is None:
        config = load_email_config_from_env()

    subject = build_subject(result)
    body = build_body(result, report_path)
    preview_payload = {"subject": subject, "body": body}

    # 送信リクエストなし
    if not requested:
        return EmailSendResult(
            requested=False,
            sent=False,
            skipped_reason="send_email_not_requested",
            error=None,
            payload_preview=preview_payload if dry_run_notify else None,
        )

    # dry-run: プレビューのみ
    if dry_run_notify:
        return EmailSendResult(
            requested=True,
            sent=False,
            skipped_reason="dry_run_notify=true",
            error=None,
            payload_preview=preview_payload,
        )

    # SMTP 設定なし
    if config is None:
        return EmailSendResult(
            requested=True,
            sent=False,
            skipped_reason="EMAIL_SMTP_CONFIG not set",
            error=None,
            payload_preview=None,
        )

    # 実送信
    payload = build_email_payload(subject, body, config)
    try:
        send_email_via_smtp(config, payload)
        logger.info(f"メール送信成功: {subject}")
        return EmailSendResult(
            requested=True,
            sent=True,
            skipped_reason=None,
            error=None,
            payload_preview=None,
        )
    except smtplib.SMTPException as exc:
        logger.error(f"メール送信失敗: {exc}")
        return EmailSendResult(
            requested=True,
            sent=False,
            skipped_reason="email_smtp_error",
            error=exc.__class__.__name__,
            payload_preview=None,
        )
