"""
FX市場データ鮮度チェック。
警告: 6時間以上古い。無効: 24時間以上古い。
週末は閾値を緩める（暫定実装）。
実注文なし・研究用のみ。
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
WARNING_HOURS = 6.0
INVALID_HOURS = 24.0
# 週末（土日）は Frankfurter が金曜レートを返すため閾値を緩める
# TODO: FXカレンダー（祝日・特殊休場）への対応は将来の改善事項
WEEKEND_WARNING_MULTIPLIER = 6.0   # → 36h
WEEKEND_INVALID_MULTIPLIER = 3.0   # → 72h


@dataclass
class StaleResult:
    level: str        # "fresh" | "warning" | "invalid"
    reason: str
    age_hours: float
    is_invalid: bool
    is_warning: bool


def check_stale(
    timestamp_str: str,
    now: Optional[datetime] = None,
) -> StaleResult:
    """
    タイムスタンプの鮮度を判定する。

    Frankfurter API は土日・祝日に前営業日のレートを返すため、
    週末は WARNING/INVALID 閾値を緩める（暫定対応）。

    TODO: FX市場の正確な休場時間（ニュージーランド月曜早朝〜金曜深夜JST）
    に基づいた stale 判定への改善が必要。
    """
    if now is None:
        now = datetime.now(JST)

    try:
        ts = datetime.fromisoformat(timestamp_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=JST)
        ts_utc = ts.astimezone(timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        age_hours = (now_utc - ts_utc).total_seconds() / 3600
    except (ValueError, TypeError):
        return StaleResult(
            level="invalid",
            reason="タイムスタンプのパース失敗",
            age_hours=float("inf"),
            is_invalid=True,
            is_warning=True,
        )

    now_jst = now.astimezone(JST)
    is_weekend = now_jst.weekday() >= 5  # 5=Saturday, 6=Sunday
    eff_warning = WARNING_HOURS * WEEKEND_WARNING_MULTIPLIER if is_weekend else WARNING_HOURS
    eff_invalid = INVALID_HOURS * WEEKEND_INVALID_MULTIPLIER if is_weekend else INVALID_HOURS

    if age_hours >= eff_invalid:
        return StaleResult(
            level="invalid",
            reason=f"データが{age_hours:.1f}h古い（無効閾値{eff_invalid:.0f}h超）",
            age_hours=round(age_hours, 2),
            is_invalid=True,
            is_warning=True,
        )
    if age_hours >= eff_warning:
        return StaleResult(
            level="warning",
            reason=f"データが{age_hours:.1f}h古い（警告閾値{eff_warning:.0f}h超）",
            age_hours=round(age_hours, 2),
            is_invalid=False,
            is_warning=True,
        )
    return StaleResult(
        level="fresh",
        reason=f"データが新鮮（{age_hours:.1f}h）",
        age_hours=round(age_hours, 2),
        is_invalid=False,
        is_warning=False,
    )
