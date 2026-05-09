"""
FX市場データ鮮度チェック。

市場開場中（平日）:
    警告: 6時間以上古い。
    無効: 24時間以上古い。

市場休場中（土・日・月曜07:00 JST前）:
    Frankfurter は金曜終値を返す。72時間以内なら market_closed（想定内）。
    72時間超は invalid（異常）。

実注文なし・研究用のみ。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

# 平日・市場開場中の閾値
WARNING_HOURS = 6.0
INVALID_HOURS = 24.0

# 市場休場中でも、これを超えると異常とみなす（金曜終値 → 月曜朝は最大約62h）
MARKET_CLOSED_MAX_STALE_HOURS = 72.0

# NZ/Sydney市場が開くのは月曜 07:00 JST 前後（暫定）
# TODO: サマータイム・FXカレンダー（クリスマス等の特殊閉場）への正確な対応は将来の改善事項
MARKET_OPEN_HOUR_MONDAY_JST = 7


def _is_fx_market_closed(now_jst: datetime) -> bool:
    """
    FX主要市場が閉場中かどうかを判定する（JST基準）。

    閉場とみなす時間帯:
    - 土曜終日 (weekday=5)
    - 日曜終日 (weekday=6)
    - 月曜 07:00 JST 前 (weekday=0, hour < 7)

    FX主要市場の開閉:
    - 週末は土曜早朝 JST（NY クローズ）から月曜早朝 JST（NZ/Sydney オープン）まで閉場
    - Frankfurter API は土日に金曜終値を返すため、古さは想定内
    """
    weekday = now_jst.weekday()  # 0=Mon ... 6=Sun
    if weekday == 5:  # Saturday
        return True
    if weekday == 6:  # Sunday
        return True
    if weekday == 0 and now_jst.hour < MARKET_OPEN_HOUR_MONDAY_JST:  # Monday before open
        return True
    return False


@dataclass
class StaleResult:
    level: str        # "fresh" | "warning" | "invalid" | "market_closed"
    reason: str
    age_hours: float
    is_invalid: bool
    is_warning: bool


def check_stale(
    timestamp_str: str,
    now: Optional[datetime] = None,
) -> StaleResult:
    """
    タイムスタンプの鮮度を市場状態込みで判定する。

    Returns:
        StaleResult.level:
            "fresh"         — 市場開場中、データ十分に新鮮（< 6h）
            "warning"       — 市場開場中、データがやや古い（6h〜24h）
            "invalid"       — 市場開場中かつ 24h 超、または休場中でも 72h 超
            "market_closed" — FX市場休場中（土日・月曜早朝）でデータ鮮度は想定内（< 72h）
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
    market_closed = _is_fx_market_closed(now_jst)

    if market_closed:
        # 市場休場中: データが古くても一定範囲内なら想定内
        if age_hours >= MARKET_CLOSED_MAX_STALE_HOURS:
            return StaleResult(
                level="invalid",
                reason=(
                    f"データが{age_hours:.1f}h古い"
                    f"（市場休場中だが閾値{MARKET_CLOSED_MAX_STALE_HOURS:.0f}h超で無効）"
                ),
                age_hours=round(age_hours, 2),
                is_invalid=True,
                is_warning=True,
            )
        return StaleResult(
            level="market_closed",
            reason=(
                f"FX市場休場中（週末・月曜早朝）。"
                f"データが{age_hours:.1f}h古いが想定内（閾値{MARKET_CLOSED_MAX_STALE_HOURS:.0f}h）"
            ),
            age_hours=round(age_hours, 2),
            is_invalid=False,
            is_warning=False,
        )

    # 平日・市場開場中
    if age_hours >= INVALID_HOURS:
        return StaleResult(
            level="invalid",
            reason=f"データが{age_hours:.1f}h古い（無効閾値{INVALID_HOURS:.0f}h超）",
            age_hours=round(age_hours, 2),
            is_invalid=True,
            is_warning=True,
        )
    if age_hours >= WARNING_HOURS:
        return StaleResult(
            level="warning",
            reason=f"データが{age_hours:.1f}h古い（警告閾値{WARNING_HOURS:.0f}h超）",
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
