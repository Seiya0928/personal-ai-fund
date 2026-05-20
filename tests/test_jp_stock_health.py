"""日本株スクリーニング ヘルスチェックのテスト。"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.jp_stocks import health as health_mod
from src.jp_stocks.health import HealthResult, check_health, render_health

JST = timezone(timedelta(hours=9))


def _make_entry(
    hours_ago: float = 1.0,
    is_stale: bool = False,
    candidate_count: int = 0,
    error_count: int = 0,
) -> dict:
    run_at = datetime.now(JST) - timedelta(hours=hours_ago)
    return {
        "run_at": run_at.isoformat(),
        "data_source": "yfinance (test)",
        "data_date": "2026-05-19",
        "is_stale": is_stale,
        "total": 65,
        "skip": 65 - candidate_count,
        "watch": 0,
        "candidate": candidate_count,
        "candidates": [],
        "watches": [],
        "error_count": error_count,
        "errors": [],
    }


class TestCheckHealth:
    def test_ok_when_recent_run_and_fresh(self):
        """直近実行・fresh データ → OK。"""
        entry = _make_entry(hours_ago=1.0, is_stale=False)
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.status == "OK"
        assert result.ok is True

    def test_warning_when_no_history(self):
        """履歴なし → WARNING。"""
        with patch("src.jp_stocks.health.get_last_entry", return_value=None):
            result = check_health()
        assert result.status == "WARNING"
        assert "未実行" in result.message

    def test_warning_when_stale(self):
        """stale データ → WARNING。"""
        entry = _make_entry(hours_ago=1.0, is_stale=True)
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.status == "WARNING"
        assert "stale" in result.message

    def test_warning_when_run_too_old(self):
        """最終実行から 48 時間超 → WARNING。"""
        entry = _make_entry(hours_ago=50.0, is_stale=False)
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.status == "WARNING"
        assert "50" in result.message or "時間" in result.message

    def test_warning_when_too_many_errors(self):
        """エラー件数が閾値超 → WARNING。"""
        entry = _make_entry(hours_ago=1.0, error_count=25)
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.status == "WARNING"
        assert "エラー" in result.message

    def test_ng_when_run_at_is_invalid(self):
        """run_at が不正な形式 → NG。"""
        entry = {"run_at": "NOT_A_DATE", "is_stale": False}
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.status == "NG"

    def test_ok_property_true_for_ok(self):
        entry = _make_entry(hours_ago=1.0)
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.ok is True

    def test_ok_property_true_for_warning(self):
        """WARNING は ok=True（致命的ではない）。"""
        with patch("src.jp_stocks.health.get_last_entry", return_value=None):
            result = check_health()
        assert result.ok is True

    def test_ok_property_false_for_ng(self):
        entry = {"run_at": "INVALID", "is_stale": False}
        with patch("src.jp_stocks.health.get_last_entry", return_value=entry):
            result = check_health()
        assert result.ok is False


class TestRenderHealth:
    def test_render_ok_contains_status(self):
        r = HealthResult(status="OK", message="正常", details=["detail1"])
        text = render_health(r)
        assert "OK" in text
        assert "正常" in text
        assert "detail1" in text

    def test_render_warning_contains_icon(self):
        r = HealthResult(status="WARNING", message="stale です")
        text = render_health(r)
        assert "WARNING" in text
        assert "⚠️" in text

    def test_render_ng_contains_icon(self):
        r = HealthResult(status="NG", message="重大なエラー")
        text = render_health(r)
        assert "NG" in text
        assert "❌" in text
