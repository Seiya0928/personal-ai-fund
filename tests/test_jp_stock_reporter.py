"""日本株スクリーニング レポート生成のテスト。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.jp_stocks.models import (
    JP_STOCK_CANDIDATE,
    JP_STOCK_SKIP,
    JP_STOCK_WATCH,
    ScreeningResult,
    ScreeningSignal,
    StockQuote,
)
from src.jp_stocks.reporter import generate_report

JST = timezone(timedelta(hours=9))


def _make_result(**overrides) -> ScreeningResult:
    defaults = dict(
        run_at=datetime(2026, 5, 20, 9, 0, 0, tzinfo=JST),
        data_source="yfinance (test)",
        data_date="2026-05-19",
        is_stale=False,
        total_screened=3,
        skip_count=1,
        watch_count=1,
        candidate_count=1,
        signals=[],
        errors=[],
    )
    defaults.update(overrides)
    return ScreeningResult(**defaults)


def _make_quote(code: str = "7203", **kw) -> StockQuote:
    return StockQuote(
        code=code,
        name="トヨタ自動車",
        market="Prime",
        sector="自動車",
        prev_close=2000.0,
        current_price=2100.0,
        change_pct=5.0,
        volume=2_000_000,
        avg_volume_20d=1_000_000,
        turnover_jpy=4_200_000_000,
        high_52w=2_500.0,
        low_52w=1_500.0,
        data_date="2026-05-19",
        is_stale=False,
        **kw,
    )


def _make_signal(status: str, code: str = "7203") -> ScreeningSignal:
    return ScreeningSignal(
        code=code,
        name="テスト銘柄",
        market="Prime",
        sector="テスト",
        status=status,
        reasons=["テスト理由 +5.0% / 出来高比 2.0x"],
        quote=_make_quote(code=code),
    )


class TestGenerateReport:
    def test_report_contains_header(self):
        result = _make_result()
        report = generate_report(result)
        assert "# 日本株スクリーニング結果" in report

    def test_report_contains_run_at(self):
        result = _make_result()
        report = generate_report(result)
        assert "2026-05-20 09:00:00 JST" in report

    def test_report_contains_data_date(self):
        result = _make_result()
        report = generate_report(result)
        assert "2026-05-19" in report

    def test_fresh_label_when_not_stale(self):
        result = _make_result(is_stale=False)
        report = generate_report(result)
        assert "fresh" in report
        assert "stale" not in report.lower().replace("stale", "HIDDEN")

    def test_stale_label_when_stale(self):
        result = _make_result(is_stale=True)
        report = generate_report(result)
        assert "stale" in report

    def test_candidate_section_present(self):
        sig = _make_signal(JP_STOCK_CANDIDATE)
        result = _make_result(signals=[sig], candidate_count=1)
        report = generate_report(result)
        assert "JP_STOCK_CANDIDATE" in report
        assert "テスト理由" in report

    def test_watch_section_present(self):
        sig = _make_signal(JP_STOCK_WATCH)
        result = _make_result(signals=[sig], watch_count=1, candidate_count=0)
        report = generate_report(result)
        assert "JP_STOCK_WATCH" in report

    def test_no_candidate_message_when_empty(self):
        result = _make_result(candidate_count=0, signals=[])
        report = generate_report(result)
        assert "候補銘柄はありません" in report

    def test_next_action_section(self):
        result = _make_result()
        report = generate_report(result)
        assert "Next Action" in report
        assert "実注文しない" in report

    def test_error_section_when_errors_exist(self):
        result = _make_result(errors=["7203: タイムアウト", "8306: データ不足"])
        report = generate_report(result)
        assert "データ取得エラー" in report
        assert "タイムアウト" in report

    def test_no_error_section_when_no_errors(self):
        result = _make_result(errors=[])
        report = generate_report(result)
        assert "データ取得エラー" not in report

    def test_report_contains_safety_disclaimer(self):
        """レポートに実注文禁止の注記が含まれること。"""
        result = _make_result()
        report = generate_report(result)
        assert "実注文" in report
        assert "発注" in report or "研究用" in report

    def test_summary_counts(self):
        result = _make_result(total_screened=65, candidate_count=2,
                              watch_count=5, skip_count=58)
        report = generate_report(result)
        assert "65" in report
        assert "2" in report

    def test_error_list_truncated_at_10(self):
        errors = [f"銘柄{i}: エラー" for i in range(20)]
        result = _make_result(errors=errors)
        report = generate_report(result)
        # 最大 10 件 + "他 N 件" のメッセージ
        assert "他 10 件" in report
