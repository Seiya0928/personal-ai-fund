"""日本株スクリーニング メール通知のテスト。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.jp_stocks.models import (
    JP_STOCK_CANDIDATE,
    JP_STOCK_SKIP,
    JP_STOCK_WATCH,
    ScreeningResult,
    ScreeningSignal,
    StockQuote,
)
from src.jp_stocks.notifier import build_body, build_subject, send_screening_email

JST = timezone(timedelta(hours=9))


# ── fixture ─────────────────────────────────────────────────────────

def _make_quote(code: str = "7203", change_pct: float = 3.0,
                volume_ratio: float = 2.0, turnover: float = 8e8) -> StockQuote:
    return StockQuote(
        code=code, name=f"銘柄{code}", market="Prime", sector="テスト",
        prev_close=1000.0, current_price=1030.0,
        change_pct=change_pct,
        volume=int(volume_ratio * 1_000_000),
        avg_volume_20d=1_000_000,
        turnover_jpy=turnover,
        high_52w=1200.0, low_52w=800.0,
        data_date="2026-05-20", is_stale=False,
    )


def _make_signal(status: str, code: str = "7203", reasons: list[str] | None = None) -> ScreeningSignal:
    return ScreeningSignal(
        code=code, name=f"銘柄{code}", market="Prime", sector="テスト",
        status=status,
        reasons=reasons or [f"テスト理由 {code}"],
        quote=_make_quote(code=code),
    )


def _make_result(
    candidate_count: int = 0,
    watch_count: int = 0,
    skip_count: int = 3,
    signals: list[ScreeningSignal] | None = None,
    errors: list[str] | None = None,
    is_stale: bool = False,
) -> ScreeningResult:
    return ScreeningResult(
        run_at=datetime(2026, 5, 20, 15, 45, 0, tzinfo=JST),
        data_source="yfinance (test)",
        data_date="2026-05-20",
        is_stale=is_stale,
        total_screened=candidate_count + watch_count + skip_count,
        skip_count=skip_count,
        watch_count=watch_count,
        candidate_count=candidate_count,
        signals=signals or [],
        errors=errors or [],
    )


# ── 件名テスト ────────────────────────────────────────────────────────

class TestBuildSubject:
    def test_candidate_subject(self):
        result = _make_result(candidate_count=2, watch_count=3)
        subject = build_subject(result)
        assert "候補あり" in subject
        assert "CANDIDATE=2" in subject
        assert "WATCH=3" in subject

    def test_watch_only_subject(self):
        result = _make_result(candidate_count=0, watch_count=3)
        subject = build_subject(result)
        assert "監視銘柄あり" in subject
        assert "WATCH=3" in subject
        assert "CANDIDATE" not in subject

    def test_no_signal_subject(self):
        result = _make_result(candidate_count=0, watch_count=0)
        subject = build_subject(result)
        assert "候補なし" in subject

    def test_subject_prefix(self):
        """件名が【JP Stock Screener】で始まること。"""
        for candidate, watch in [(2, 1), (0, 3), (0, 0)]:
            result = _make_result(candidate_count=candidate, watch_count=watch)
            assert build_subject(result).startswith("【JP Stock Screener】")

    def test_single_candidate(self):
        result = _make_result(candidate_count=1, watch_count=0)
        subject = build_subject(result)
        assert "CANDIDATE=1" in subject


# ── 本文テスト ────────────────────────────────────────────────────────

class TestBuildBody:
    def test_body_contains_run_at(self):
        result = _make_result()
        body = build_body(result)
        assert "2026-05-20 15:45:00 JST" in body

    def test_body_contains_data_source(self):
        result = _make_result()
        body = build_body(result)
        assert "yfinance" in body

    def test_body_contains_counts(self):
        result = _make_result(candidate_count=2, watch_count=3)
        body = build_body(result)
        assert "CANDIDATE" in body
        assert "WATCH" in body

    def test_body_contains_safety_disclaimer(self):
        """実注文禁止の明記が本文に含まれること。"""
        result = _make_result()
        body = build_body(result)
        assert "実注文は行いません" in body
        assert "研究用スクリーニング通知" in body

    def test_body_contains_next_action(self):
        result = _make_result()
        body = build_body(result)
        assert "Next Action" in body
        assert "実注文しない" in body

    def test_candidate_details_in_body(self):
        """CANDIDATE 銘柄の詳細が本文に含まれること。"""
        sig = _make_signal(JP_STOCK_CANDIDATE, code="7203",
                           reasons=["ギャップアップ +3.0% / 出来高比 2.0x"])
        result = _make_result(candidate_count=1, signals=[sig])
        body = build_body(result)
        assert "7203" in body
        assert "ギャップアップ" in body

    def test_watch_details_in_body(self):
        """WATCH 銘柄の詳細が本文に含まれること。"""
        sig = _make_signal(JP_STOCK_WATCH, code="8411",
                           reasons=["モメンタム +1.4% / 出来高比 1.6x"])
        result = _make_result(watch_count=1, signals=[sig])
        body = build_body(result)
        assert "8411" in body

    def test_no_candidate_message(self):
        result = _make_result(candidate_count=0)
        body = build_body(result)
        assert "候補銘柄はありません" in body

    def test_report_path_in_body(self):
        result = _make_result()
        path = Path("reports/jp_stock_screener_20260520.md")
        body = build_body(result, report_path=path)
        assert "reports/jp_stock_screener_20260520.md" in body

    def test_error_list_in_body(self):
        result = _make_result(errors=["7203: タイムアウト", "8306: データ不足"])
        body = build_body(result)
        assert "データ取得エラー" in body
        assert "タイムアウト" in body

    def test_stale_note_in_body(self):
        result = _make_result(is_stale=True)
        body = build_body(result)
        assert "stale" in body

    def test_candidate_truncated_at_10(self):
        """CANDIDATE が 11 件以上でも本文は 10 件まで。"""
        # 5桁コードで index counter ([1]〜[10]) との誤一致を防ぐ
        sigs = [_make_signal(JP_STOCK_CANDIDATE, code=f"7{str(i).zfill(4)}") for i in range(11)]
        result = _make_result(candidate_count=11, signals=sigs)
        body = build_body(result)
        assert sigs[9].code in body   # 10 件目は含まれる
        assert sigs[10].code not in body  # 11 件目は含まれない


# ── send_screening_email テスト ──────────────────────────────────────

class TestSendScreeningEmail:
    def test_not_requested_returns_not_sent(self):
        """--send-email なし → 送信しない。"""
        result = _make_result(candidate_count=1)
        email_result = send_screening_email(result, requested=False, dry_run_notify=False)
        assert email_result.sent is False
        assert email_result.requested is False
        assert email_result.skipped_reason == "send_email_not_requested"
        assert email_result.payload_preview is None

    def test_dry_run_returns_preview_without_sending(self):
        """--dry-run-notify → 送信せずプレビューを返す。"""
        result = _make_result(candidate_count=1)
        email_result = send_screening_email(
            result, requested=True, dry_run_notify=True
        )
        assert email_result.sent is False
        assert email_result.skipped_reason == "dry_run_notify=true"
        assert email_result.payload_preview is not None
        assert "subject" in email_result.payload_preview
        assert "body" in email_result.payload_preview

    def test_dry_run_preview_has_disclaimer(self):
        """dry-run プレビューの本文に実注文禁止が含まれること。"""
        result = _make_result()
        email_result = send_screening_email(result, requested=True, dry_run_notify=True)
        assert "実注文は行いません" in email_result.payload_preview["body"]

    def test_no_smtp_config_skips(self):
        """SMTP 設定なし → EMAIL_SMTP_CONFIG not set でスキップ。"""
        result = _make_result()
        email_result = send_screening_email(
            result, requested=True, dry_run_notify=False, config=None
        )
        with patch("src.jp_stocks.notifier.load_email_config_from_env", return_value=None):
            email_result = send_screening_email(
                result, requested=True, dry_run_notify=False, config=None
            )
        assert email_result.sent is False
        assert email_result.skipped_reason == "EMAIL_SMTP_CONFIG not set"

    def test_smtp_success(self):
        """SMTP が正常なら sent=True。"""
        from src.alerts.email_notifier import EmailConfig
        config = EmailConfig(
            host="smtp.example.com", port=587,
            username="user", password="pass",
            from_address="from@example.com",
            to_address="to@example.com",
        )
        result = _make_result(candidate_count=1)
        with patch("src.jp_stocks.notifier.send_email_via_smtp") as mock_send:
            mock_send.return_value = None
            email_result = send_screening_email(
                result, requested=True, dry_run_notify=False, config=config
            )
        assert email_result.sent is True
        assert email_result.skipped_reason is None
        mock_send.assert_called_once()

    def test_smtp_failure_returns_error(self):
        """SMTP 失敗 → sent=False, error に例外クラス名が入る。"""
        import smtplib
        from src.alerts.email_notifier import EmailConfig
        config = EmailConfig(
            host="smtp.example.com", port=587,
            username="user", password="pass",
            from_address="from@example.com",
            to_address="to@example.com",
        )
        result = _make_result()
        with patch("src.jp_stocks.notifier.send_email_via_smtp",
                   side_effect=smtplib.SMTPException("接続エラー")):
            email_result = send_screening_email(
                result, requested=True, dry_run_notify=False, config=config
            )
        assert email_result.sent is False
        assert email_result.skipped_reason == "email_smtp_error"
        assert email_result.error == "SMTPException"

    def test_not_requested_dry_run_shows_no_preview(self):
        """--send-email なし・--dry-run-notify なし → payload_preview は None。"""
        result = _make_result()
        email_result = send_screening_email(result, requested=False, dry_run_notify=False)
        assert email_result.payload_preview is None

    def test_dry_run_without_requested_also_shows_preview(self):
        """--dry-run-notify だけ指定しても requested=True として扱われる。"""
        result = _make_result()
        # run_jp_stock_screener.py で requested=dry_run_notify として渡すため
        email_result = send_screening_email(
            result, requested=True, dry_run_notify=True
        )
        assert email_result.payload_preview is not None


# ── 安全性テスト ─────────────────────────────────────────────────────

class TestNotifierSafety:
    def test_notifier_module_has_no_forbidden_strings(self):
        """notifier.py に実注文関連の文字列が含まれないこと。"""
        notifier_path = Path(__file__).resolve().parents[1] / "src" / "jp_stocks" / "notifier.py"
        content = notifier_path.read_text(encoding="utf-8")
        for forbidden in ["live_order", "place_order", "DRY_RUN=false", "gmo_private"]:
            assert forbidden not in content, f"notifier.py に '{forbidden}' が含まれています"

    def test_send_screening_email_does_not_import_order_modules(self):
        """send_screening_email が注文系モジュールに依存しないこと。"""
        from src.jp_stocks import notifier
        # src.risk, src.brokers の private API は import されていないはず
        import sys
        for mod_name in list(sys.modules.keys()):
            if "gmo_private" in mod_name or "live_order" in mod_name:
                pytest.fail(f"禁止モジュールがロードされています: {mod_name}")
