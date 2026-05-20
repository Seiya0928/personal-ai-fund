# 実注文なし・研究用ヘルスチェックのみ
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.jp_stocks.signal_history import get_last_entry

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
STALE_RUN_HOURS = 48   # 最終実行から何時間以上で WARNING にするか
MAX_ACCEPTABLE_ERRORS = 20   # エラー件数がこれを超えると WARNING（固定閾値）
MAX_ERROR_RATE = 0.20        # エラー率がこれを超えると WARNING（割合）


@dataclass
class HealthResult:
    status: str          # "OK" / "WARNING" / "NG"
    message: str
    details: list[str] = field(default_factory=list)
    last_entry: Optional[dict] = None

    @property
    def ok(self) -> bool:
        return self.status in ("OK", "WARNING")


def check_health() -> HealthResult:
    """スクリーニング bot のヘルス状態を確認する。

    Returns
    -------
    HealthResult
        status = "OK"      : 正常（直近実行成功・データ fresh）
        status = "WARNING"  : 軽度の問題（未実行・stale・エラー多数）
        status = "NG"       : 重大な問題（想定外の状態）
    """
    last = get_last_entry()

    if last is None:
        return HealthResult(
            status="WARNING",
            message="スクリーニング未実行",
            details=["state/jp_stock_screening_history.json が空です。"],
            last_entry=None,
        )

    details: list[str] = []

    # 実行時刻の解析
    try:
        run_at = datetime.fromisoformat(last["run_at"])
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=JST)
        now = datetime.now(JST)
        age_hours = (now - run_at).total_seconds() / 3600
        details.append(f"最終実行: {run_at.strftime('%Y-%m-%d %H:%M JST')}")
        details.append(f"経過時間: {age_hours:.1f} 時間")
    except Exception:
        return HealthResult(
            status="NG",
            message="run_at の解析に失敗",
            details=["履歴データが破損している可能性があります。"],
            last_entry=last,
        )

    total = last.get("total", 0)
    universe_source = last.get("universe_source", "fixed")
    market_filter = last.get("market_filter", "all")

    details.append(
        f"スクリーニング: {total} 銘柄 / "
        f"CANDIDATE={last.get('candidate', 0)} / "
        f"WATCH={last.get('watch', 0)}"
    )
    details.append(f"ユニバース: {universe_source} / 市場: {market_filter}")

    # 警告判定
    warnings: list[str] = []

    if last.get("is_stale"):
        warnings.append("データが stale 状態です")

    if age_hours > STALE_RUN_HOURS:
        warnings.append(f"最終実行から {age_hours:.0f} 時間経過（閾値 {STALE_RUN_HOURS}h）")

    error_count = last.get("error_count", 0)
    error_rate = error_count / max(total, 1)
    if error_count > MAX_ACCEPTABLE_ERRORS or error_rate > MAX_ERROR_RATE:
        warnings.append(
            f"データ取得エラーが {error_count} 件 "
            f"({error_rate * 100:.1f}%) あります"
        )

    if warnings:
        return HealthResult(
            status="WARNING",
            message=" / ".join(warnings),
            details=details,
            last_entry=last,
        )

    return HealthResult(
        status="OK",
        message="正常",
        details=details,
        last_entry=last,
    )


def render_health(result: HealthResult) -> str:
    """HealthResult をターミナル表示用の文字列にフォーマットする。"""
    icon = {"OK": "✅", "WARNING": "⚠️", "NG": "❌"}.get(result.status, "?")
    lines = [
        "[JP Stock Screener Health]",
        f"  Status : {icon} {result.status}",
        f"  Message: {result.message}",
    ]
    for d in result.details:
        lines.append(f"  {d}")
    return "\n".join(lines)
