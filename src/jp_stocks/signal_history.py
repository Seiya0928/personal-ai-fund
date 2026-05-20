# 実注文なし・研究用履歴保存のみ
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.jp_stocks.models import ScreeningResult

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = _PROJECT_ROOT / "state" / "jp_stock_screening_history.json"
MAX_HISTORY = 90  # 最大 90 エントリ（約 3 ヶ月分）保持


def load_history() -> list[dict]:
    """スクリーニング履歴 JSON を読み込む。ファイルがなければ空リストを返す。"""
    if not STATE_PATH.exists():
        return []
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"履歴ファイル読み込み失敗: {exc}")
        return []


def append_result(result: ScreeningResult) -> None:
    """スクリーニング結果を履歴 JSON に追記する。"""
    history = load_history()

    entry = {
        "run_at": result.run_at.isoformat(),
        "data_source": result.data_source,
        "data_date": result.data_date,
        "is_stale": result.is_stale,
        "universe_source": result.universe_source,
        "market_filter": result.market_filter,
        "limit": result.limit,
        "total": result.total_screened,
        "skip": result.skip_count,
        "watch": result.watch_count,
        "candidate": result.candidate_count,
        "candidates": [
            {
                "code": s.code,
                "name": s.name,
                "market": s.market,
                "sector": s.sector,
                "reasons": s.reasons,
                "change_pct": round(s.quote.change_pct, 2) if s.quote else None,
                "volume_ratio": round(s.quote.volume_ratio, 2) if s.quote else None,
                "turnover_jpy": int(s.quote.turnover_jpy) if s.quote else None,
            }
            for s in result.candidate_signals
        ],
        "watches": [
            {
                "code": s.code,
                "name": s.name,
                "reasons": s.reasons,
            }
            for s in result.watch_signals
        ],
        "error_count": len(result.errors),
        "errors": result.errors[:5],  # 最大 5 件
    }

    history.append(entry)
    history = history[-MAX_HISTORY:]  # 古いものを切り捨て

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"履歴保存: {STATE_PATH} (total entries={len(history)})")

    # エラー銘柄リストを別ファイルに保存（レビュー用）
    if result.errors:
        _save_fetch_errors(result)


def get_last_entry() -> Optional[dict]:
    """最新のスクリーニング結果エントリを返す。なければ None。"""
    history = load_history()
    return history[-1] if history else None


_ERRORS_PATH = _PROJECT_ROOT / "state" / "jp_stock_fetch_errors.json"


def _save_fetch_errors(result: ScreeningResult) -> None:
    """取得失敗銘柄リストを state/jp_stock_fetch_errors.json に保存する。"""
    record = {
        "run_at": result.run_at.isoformat(),
        "universe_source": result.universe_source,
        "total": result.total_screened,
        "error_count": len(result.errors),
        "errors": result.errors,
    }
    _ERRORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ERRORS_PATH.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"エラー銘柄保存: {_ERRORS_PATH} ({len(result.errors)} 件)")
