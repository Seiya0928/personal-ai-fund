# 実注文なし・研究用シグナルのみ
# このモジュールは実注文APIを一切呼びません。

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.utils.logger import get_logger

log = get_logger(__name__)

JST = ZoneInfo("Asia/Tokyo")


@dataclass
class EventEntry:
    name: str
    date: datetime  # tzaware (JST)


# ハードコードされた2025-2026年の主要イベント日付（代表的な日付）
_HARDCODED_EVENTS: list[tuple[str, str]] = [
    # FOMC（米連邦公開市場委員会）
    ("FOMC", "2025-01-29"),
    ("FOMC", "2025-03-19"),
    ("FOMC", "2025-05-07"),
    ("FOMC", "2025-06-18"),
    ("FOMC", "2025-07-30"),
    ("FOMC", "2025-09-17"),
    ("FOMC", "2025-11-05"),
    ("FOMC", "2025-12-17"),
    ("FOMC", "2026-01-28"),
    ("FOMC", "2026-03-18"),
    ("FOMC", "2026-05-06"),
    ("FOMC", "2026-06-17"),
    # 雇用統計（NFP）: 毎月第1金曜
    ("NFP", "2025-01-10"),
    ("NFP", "2025-02-07"),
    ("NFP", "2025-03-07"),
    ("NFP", "2025-04-04"),
    ("NFP", "2025-05-02"),
    ("NFP", "2025-06-06"),
    ("NFP", "2025-07-03"),
    ("NFP", "2025-08-01"),
    ("NFP", "2025-09-05"),
    ("NFP", "2025-10-03"),
    ("NFP", "2025-11-07"),
    ("NFP", "2025-12-05"),
    ("NFP", "2026-01-09"),
    ("NFP", "2026-02-06"),
    ("NFP", "2026-03-06"),
    ("NFP", "2026-04-03"),
    ("NFP", "2026-05-01"),
    # 日銀会合（BOJ）
    ("BOJ", "2025-01-24"),
    ("BOJ", "2025-03-19"),
    ("BOJ", "2025-04-30"),
    ("BOJ", "2025-06-17"),
    ("BOJ", "2025-07-31"),
    ("BOJ", "2025-09-22"),
    ("BOJ", "2025-10-29"),
    ("BOJ", "2025-12-19"),
    ("BOJ", "2026-01-24"),
    ("BOJ", "2026-03-19"),
    ("BOJ", "2026-04-28"),
    ("BOJ", "2026-06-17"),
    # 米CPI（消費者物価指数）: 毎月中旬
    ("US_CPI", "2025-01-15"),
    ("US_CPI", "2025-02-12"),
    ("US_CPI", "2025-03-12"),
    ("US_CPI", "2025-04-10"),
    ("US_CPI", "2025-05-13"),
    ("US_CPI", "2025-06-11"),
    ("US_CPI", "2025-07-15"),
    ("US_CPI", "2025-08-13"),
    ("US_CPI", "2025-09-10"),
    ("US_CPI", "2025-10-15"),
    ("US_CPI", "2025-11-12"),
    ("US_CPI", "2025-12-10"),
    ("US_CPI", "2026-01-14"),
    ("US_CPI", "2026-02-11"),
    ("US_CPI", "2026-03-11"),
    ("US_CPI", "2026-04-09"),
    ("US_CPI", "2026-05-13"),
    # 米PPI（生産者物価指数）
    ("US_PPI", "2025-01-16"),
    ("US_PPI", "2025-02-13"),
    ("US_PPI", "2025-03-13"),
    ("US_PPI", "2025-04-11"),
    ("US_PPI", "2025-05-15"),
    ("US_PPI", "2025-06-12"),
    ("US_PPI", "2025-07-16"),
    ("US_PPI", "2025-08-14"),
    ("US_PPI", "2025-09-11"),
    ("US_PPI", "2025-10-16"),
    ("US_PPI", "2025-11-13"),
    ("US_PPI", "2025-12-11"),
    ("US_PPI", "2026-01-15"),
    ("US_PPI", "2026-02-12"),
    ("US_PPI", "2026-03-12"),
    ("US_PPI", "2026-04-10"),
    ("US_PPI", "2026-05-14"),
]


def _parse_event_date(date_str: str) -> datetime:
    """YYYY-MM-DD を JST 正午の datetime に変換"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.replace(hour=12, minute=0, second=0, tzinfo=JST)


class EventCalendar:
    """重要指標イベントのカレンダー（実注文なし・研究用）"""

    def __init__(self, extra_events: Optional[list[EventEntry]] = None):
        self._events: list[EventEntry] = [
            EventEntry(name=name, date=_parse_event_date(date_str))
            for name, date_str in _HARDCODED_EVENTS
        ]
        if extra_events:
            self._events.extend(extra_events)
        log.debug(f"EventCalendar: {len(self._events)}件のイベントをロード")

    def is_near_event(
        self, dt: datetime, window_hours: int = 6
    ) -> tuple[bool, str]:
        """
        dt がいずれかのイベントの前後 window_hours 時間以内なら (True, 理由) を返す。
        そうでなければ (False, "") を返す。
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        window = timedelta(hours=window_hours)
        for ev in self._events:
            diff = abs(dt - ev.date)
            if diff <= window:
                hours_diff = diff.total_seconds() / 3600
                reason = (
                    f"重要イベント '{ev.name}' ({ev.date.strftime('%Y-%m-%d')}) "
                    f"の {hours_diff:.1f}時間以内 (window={window_hours}h)"
                )
                return True, reason
        return False, ""

    @classmethod
    def load_custom_events(cls, path: Path) -> list[EventEntry]:
        """
        JSONファイルからカスタムイベントを読み込む。
        形式: [{"name": "MY_EVENT", "date": "2025-06-01"}, ...]
        """
        if not path.exists():
            log.warning(f"カスタムイベントファイルが見つかりません: {path}")
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            events = []
            for item in data:
                ev = EventEntry(
                    name=item["name"],
                    date=_parse_event_date(item["date"]),
                )
                events.append(ev)
            log.info(f"カスタムイベント {len(events)}件 をロード: {path}")
            return events
        except Exception as e:
            log.error(f"カスタムイベントのロードに失敗: {e}")
            return []
