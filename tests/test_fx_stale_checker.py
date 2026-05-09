"""Tests for src/fx/fx_stale_checker.py"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.fx.fx_stale_checker import (
    WARNING_HOURS,
    INVALID_HOURS,
    MARKET_CLOSED_MAX_STALE_HOURS,
    MARKET_OPEN_HOUR_MONDAY_JST,
    _is_fx_market_closed,
    check_stale,
)

JST = ZoneInfo("Asia/Tokyo")


def _make_now(weekday: int, hour: int = 12) -> datetime:
    """指定の曜日・時間の JST datetime を作る。weekday: 0=Mon ... 6=Sun"""
    # 固定日付: 2026-01-05 (月) から曜日を計算
    base = datetime(2026, 1, 5, hour, 0, 0, tzinfo=JST)  # Monday
    delta_days = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta_days)


def _ts_hours_ago(hours: float, now: datetime) -> str:
    ts = now - timedelta(hours=hours)
    return ts.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# _is_fx_market_closed
# ---------------------------------------------------------------------------

class TestIsFxMarketClosed:
    def test_saturday_closed(self):
        now = _make_now(5, hour=12)  # Saturday noon
        assert _is_fx_market_closed(now) is True

    def test_sunday_closed(self):
        now = _make_now(6, hour=9)   # Sunday
        assert _is_fx_market_closed(now) is True

    def test_monday_before_open_closed(self):
        now = _make_now(0, hour=6)   # Monday 06:00 JST (before MARKET_OPEN_HOUR_MONDAY_JST=7)
        assert _is_fx_market_closed(now) is True

    def test_monday_exactly_at_open_is_open(self):
        now = _make_now(0, hour=MARKET_OPEN_HOUR_MONDAY_JST)  # Monday 07:00 JST
        assert _is_fx_market_closed(now) is False

    def test_monday_after_open_is_open(self):
        now = _make_now(0, hour=10)  # Monday 10:00 JST
        assert _is_fx_market_closed(now) is False

    def test_tuesday_is_open(self):
        now = _make_now(1, hour=9)
        assert _is_fx_market_closed(now) is False

    def test_friday_is_open(self):
        now = _make_now(4, hour=15)
        assert _is_fx_market_closed(now) is False


# ---------------------------------------------------------------------------
# check_stale — 平日（市場開場中）
# ---------------------------------------------------------------------------

class TestCheckStaleWeekday:
    def test_fresh_data(self):
        now = _make_now(0)  # Monday 12:00
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

    def test_weekday_49h_is_invalid(self):
        """平日に49h古いデータは invalid（今回の日曜ケースとの対比）"""
        now = _make_now(1, hour=10)  # Tuesday 10:00 (market open)
        ts = _ts_hours_ago(49.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "invalid"
        assert result.is_invalid is True

    def test_boundary_exactly_at_warning(self):
        """WARNING_HOURS ちょうどは warning レベル。"""
        now = _make_now(0)
        ts = (now - timedelta(hours=WARNING_HOURS)).isoformat(timespec="seconds")
        result = check_stale(ts, now=now)
        assert result.level == "warning"

    def test_boundary_exactly_at_invalid(self):
        """INVALID_HOURS ちょうどは invalid レベル。"""
        now = _make_now(0)
        ts = (now - timedelta(hours=INVALID_HOURS)).isoformat(timespec="seconds")
        result = check_stale(ts, now=now)
        assert result.level == "invalid"

    def test_monday_after_open_7h_warning(self):
        """月曜 07:00 以降は平日扱い → 7h は warning"""
        now = _make_now(0, hour=MARKET_OPEN_HOUR_MONDAY_JST)
        ts = _ts_hours_ago(7.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "warning"

    def test_monday_after_open_25h_invalid(self):
        """月曜 07:00 以降は平日扱い → 25h は invalid"""
        now = _make_now(0, hour=MARKET_OPEN_HOUR_MONDAY_JST + 1)
        ts = _ts_hours_ago(25.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "invalid"


# ---------------------------------------------------------------------------
# check_stale — 週末・月曜早朝（market_closed）
# ---------------------------------------------------------------------------

class TestCheckStaleMarketClosed:
    def test_sunday_49h_is_market_closed(self):
        """
        今回の実ケース: 日曜実行・49.8h古い → market_closed（warningではない）
        Frankfurter が金曜終値を返す想定内の古さ。
        """
        now = _make_now(6, hour=12)  # Sunday noon
        ts = _ts_hours_ago(49.8, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False
        assert result.is_warning is False
        assert "休場" in result.reason

    def test_saturday_7h_is_market_closed(self):
        """土曜 7h → market_closed（平日なら warning だが、土曜は休場想定内）"""
        now = _make_now(5, hour=10)
        ts = _ts_hours_ago(7.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False
        assert result.is_warning is False

    def test_saturday_40h_is_market_closed(self):
        """土曜 40h → market_closed（72h 未満）"""
        now = _make_now(5, hour=18)
        ts = _ts_hours_ago(40.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False

    def test_sunday_60h_is_market_closed(self):
        """日曜 60h < MARKET_CLOSED_MAX_STALE_HOURS(72) → market_closed"""
        now = _make_now(6, hour=20)
        ts = _ts_hours_ago(60.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False

    def test_weekend_73h_is_invalid(self):
        """週末でも 73h 超は invalid（異常）"""
        now = _make_now(6, hour=12)  # Sunday
        ts = _ts_hours_ago(73.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "invalid"
        assert result.is_invalid is True

    def test_weekend_exactly_at_closed_max_is_invalid(self):
        """MARKET_CLOSED_MAX_STALE_HOURS ちょうどは invalid"""
        now = _make_now(5, hour=12)
        ts = _ts_hours_ago(MARKET_CLOSED_MAX_STALE_HOURS, now)
        result = check_stale(ts, now=now)
        assert result.level == "invalid"
        assert result.is_invalid is True

    def test_monday_before_open_49h_is_market_closed(self):
        """月曜 06:00 JST（未開場）に 49h → market_closed"""
        now = _make_now(0, hour=6)  # Monday 06:00 (before open)
        ts = _ts_hours_ago(49.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False

    def test_market_closed_level_flags(self):
        """market_closed は is_invalid=False, is_warning=False"""
        now = _make_now(6, hour=9)  # Sunday
        ts = _ts_hours_ago(30.0, now)
        result = check_stale(ts, now=now)
        assert result.level == "market_closed"
        assert result.is_invalid is False
        assert result.is_warning is False

    def test_market_closed_does_not_block_fx_watch(self):
        """
        market_closed は is_invalid=False なので、
        signal_action_to_fx_status に渡しても FX_STALE_INVALID にならない。
        """
        from src.fx.fx_status import signal_action_to_fx_status
        now = _make_now(6)  # Sunday
        ts = _ts_hours_ago(49.0, now)
        result = check_stale(ts, now=now)
        assert result.is_invalid is False
        fx_status = signal_action_to_fx_status("WATCH", is_stale_invalid=result.is_invalid)
        assert fx_status == "FX_WATCH"

    def test_stale_invalid_true_gives_fx_stale_invalid(self):
        """平日 invalid → signal_action_to_fx_status で FX_STALE_INVALID になる"""
        from src.fx.fx_status import signal_action_to_fx_status
        now = _make_now(1, hour=10)  # Tuesday
        ts = _ts_hours_ago(25.0, now)
        result = check_stale(ts, now=now)
        assert result.is_invalid is True
        fx_status = signal_action_to_fx_status("WATCH", is_stale_invalid=result.is_invalid)
        assert fx_status == "FX_STALE_INVALID"


# ---------------------------------------------------------------------------
# check_stale — その他
# ---------------------------------------------------------------------------

class TestCheckStaleOther:
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

    def test_timezone_naive_timestamp_treated_as_jst(self):
        """tzinfo なしタイムスタンプは JST として扱われること。"""
        now = _make_now(0, hour=12)
        naive_ts = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="seconds")
        result = check_stale(naive_ts, now=now)
        assert result.level == "fresh"
        assert result.age_hours == pytest.approx(1.0, abs=0.05)

    def test_level_reason_contains_age(self):
        """理由文字列にデータ鮮度情報が含まれること。"""
        now = _make_now(0)
        ts = _ts_hours_ago(3.0, now)
        result = check_stale(ts, now=now)
        assert "3." in result.reason

    def test_market_closed_reason_contains_context(self):
        """market_closed の理由に休場コンテキストが含まれること。"""
        now = _make_now(6, hour=12)  # Sunday
        ts = _ts_hours_ago(49.0, now)
        result = check_stale(ts, now=now)
        assert "休場" in result.reason
        assert "想定内" in result.reason
