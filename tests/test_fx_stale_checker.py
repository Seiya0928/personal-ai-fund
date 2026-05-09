"""Tests for src/fx/fx_stale_checker.py"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from src.fx.fx_stale_checker import check_stale, WARNING_HOURS, INVALID_HOURS

JST = ZoneInfo("Asia/Tokyo")


def _make_now(weekday: int, hour: int = 12) -> datetime:
    """指定の曜日・時間の JST datetime を作る。weekday: 0=Mon ... 6=Sun"""
    # 固定日付: 2026-01-05 (月) から曜日を計算
    base = datetime(2026, 1, 5, hour, 0, 0, tzinfo=JST)  # Monday
    delta_days = (weekday - base.weekday()) % 7
    from datetime import timedelta
    return base + timedelta(days=delta_days)


def _ts_hours_ago(hours: float, now: datetime) -> str:
    from datetime import timedelta
    ts = now - timedelta(hours=hours)
    return ts.isoformat(timespec="seconds")


class TestCheckStale:
    def test_fresh_data(self):
        now = _make_now(0)  # Monday
        ts = _ts_hours_ago(1.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "fresh"
        assert result.is_invalid is False
        assert result.is_warning is False
        assert result.age_hours == pytest.approx(1.0, abs=0.05)

    def test_warning_data(self):
        now = _make_now(0)  # Monday (weekday)
        ts = _ts_hours_ago(7.0, now)  # 7h > WARNING_HOURS(6)
        result = check_stale(ts, now=now)
        assert result.level == "warning"
        assert result.is_warning is True
        assert result.is_invalid is False

    def test_invalid_data(self):
        now = _make_now(0)  # Monday
        ts = _ts_hours_ago(25.0, now)  # 25h > INVALID_HOURS(24)
        result = check_stale(ts, now=now)
        assert result.level == "invalid"
        assert result.is_invalid is True
        assert result.is_warning is True

    def test_weekend_warning_threshold(self):
        # 土曜日 (5): warning threshold = 6 * 6 = 36h → 7h は fresh
        now = _make_now(5)  # Saturday
        ts = _ts_hours_ago(7.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "fresh"
        assert result.is_warning is False

    def test_weekend_invalid_threshold(self):
        # 土曜日 (5): warning threshold = 36h, invalid threshold = 72h
        # 40h old on Saturday → 40 >= 36 (warning) but 40 < 72 (not invalid) → warning
        now = _make_now(5)  # Saturday
        ts = _ts_hours_ago(40.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "warning"
        assert result.is_warning is True
        assert result.is_invalid is False

    def test_invalid_timestamp(self):
        now = _make_now(0)
        result = check_stale("not-a-timestamp", now=now)
        assert result.level == "invalid"
        assert result.is_invalid is True
        assert result.age_hours == float("inf")

    def test_age_hours_is_correct(self):
        now = _make_now(0)
        ts = _ts_hours_ago(3.0, now)
        result = check_stale(ts, now=now)
        assert result.age_hours == pytest.approx(3.0, abs=0.05)

    def test_timezone_naive_timestamp(self):
        """tzinfo なしタイムスタンプは JST として扱われること。"""
        now = _make_now(0, hour=12)
        # 1時間前の naive timestamp
        from datetime import timedelta
        naive_ts = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="seconds")
        result = check_stale(naive_ts, now=now)
        assert result.level == "fresh"
        assert result.age_hours == pytest.approx(1.0, abs=0.05)

    def test_boundary_exactly_at_warning(self):
        """WARNING_HOURS ちょうどは warning レベル。"""
        now = _make_now(0)
        from datetime import timedelta
        ts = (now - timedelta(hours=WARNING_HOURS)).isoformat(timespec="seconds")
        result = check_stale(ts, now=now)
        assert result.level == "warning"

    def test_boundary_exactly_at_invalid(self):
        """INVALID_HOURS ちょうどは invalid レベル。"""
        now = _make_now(0)
        from datetime import timedelta
        ts = (now - timedelta(hours=INVALID_HOURS)).isoformat(timespec="seconds")
        result = check_stale(ts, now=now)
        assert result.level == "invalid"
