# 実注文なし・研究用リスクモジュールのテスト

from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.fx.risk import EventCalendar, EventEntry

JST = ZoneInfo("Asia/Tokyo")


class TestNearEventSkip:
    def test_near_event_skip(self):
        """イベント日から3時間後は is_near_event=True"""
        calendar = EventCalendar()
        # ハードコードされたFOMCイベントの1つを使う: 2025-01-29 正午JST
        fomc_date = datetime(2025, 1, 29, 12, 0, 0, tzinfo=JST)
        # 3時間後
        check_dt = fomc_date + timedelta(hours=3)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is True
        assert len(reason) > 0
        assert "FOMC" in reason

    def test_near_event_skip_before(self):
        """イベント日の2時間前も is_near_event=True"""
        calendar = EventCalendar()
        fomc_date = datetime(2025, 3, 19, 12, 0, 0, tzinfo=JST)
        check_dt = fomc_date - timedelta(hours=2)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is True

    def test_near_event_at_event_time(self):
        """イベント時刻ちょうど（差=0）は True"""
        calendar = EventCalendar()
        nfp_date = datetime(2025, 1, 10, 12, 0, 0, tzinfo=JST)
        near, reason = calendar.is_near_event(nfp_date, window_hours=6)
        assert near is True


class TestFarFromEvent:
    def test_far_from_event(self):
        """イベント日から48時間後は is_near_event=False"""
        calendar = EventCalendar()
        # 2025-01-29 FOMC の 48時間後
        fomc_date = datetime(2025, 1, 29, 12, 0, 0, tzinfo=JST)
        check_dt = fomc_date + timedelta(hours=48)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is False
        assert reason == ""

    def test_far_enough_before(self):
        """イベント日の24時間前は is_near_event=False"""
        calendar = EventCalendar()
        fomc_date = datetime(2025, 1, 29, 12, 0, 0, tzinfo=JST)
        check_dt = fomc_date - timedelta(hours=24)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is False

    def test_middle_of_nowhere(self):
        """どのイベントにも近くない日時は False"""
        calendar = EventCalendar()
        # イベントから遠い日時を選ぶ（2025-01-17 は中立的な日）
        dt = datetime(2025, 1, 17, 15, 0, 0, tzinfo=JST)
        near, reason = calendar.is_near_event(dt, window_hours=6)
        assert near is False


class TestCustomEvents:
    def test_custom_events(self, tmp_path: Path):
        """カスタムイベントJSONを読み込んで検出できる"""
        custom_path = tmp_path / "custom_events.json"
        custom_data = [
            {"name": "MY_CUSTOM_EVENT", "date": "2025-08-15"},
        ]
        custom_path.write_text(json.dumps(custom_data), encoding="utf-8")

        extra = EventCalendar.load_custom_events(custom_path)
        calendar = EventCalendar(extra_events=extra)

        # カスタムイベント日から1時間後
        ev_date = datetime(2025, 8, 15, 12, 0, 0, tzinfo=JST)
        check_dt = ev_date + timedelta(hours=1)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is True
        assert "MY_CUSTOM_EVENT" in reason

    def test_custom_events_not_near(self, tmp_path: Path):
        """カスタムイベントに近くない日時は False"""
        custom_path = tmp_path / "custom_events.json"
        custom_data = [{"name": "MY_EVENT", "date": "2025-08-15"}]
        custom_path.write_text(json.dumps(custom_data), encoding="utf-8")

        extra = EventCalendar.load_custom_events(custom_path)
        calendar = EventCalendar(extra_events=extra)

        ev_date = datetime(2025, 8, 15, 12, 0, 0, tzinfo=JST)
        check_dt = ev_date + timedelta(hours=12)
        near, reason = calendar.is_near_event(check_dt, window_hours=6)
        assert near is False

    def test_custom_events_missing_file(self, tmp_path: Path):
        """存在しないファイルは空リストを返す"""
        events = EventCalendar.load_custom_events(tmp_path / "nonexistent.json")
        assert events == []

    def test_custom_events_multiple(self, tmp_path: Path):
        """複数のカスタムイベントを読み込める"""
        custom_path = tmp_path / "multi.json"
        custom_data = [
            {"name": "EVENT_A", "date": "2025-09-01"},
            {"name": "EVENT_B", "date": "2025-10-01"},
        ]
        custom_path.write_text(json.dumps(custom_data), encoding="utf-8")
        events = EventCalendar.load_custom_events(custom_path)
        assert len(events) == 2
        names = [e.name for e in events]
        assert "EVENT_A" in names
        assert "EVENT_B" in names
