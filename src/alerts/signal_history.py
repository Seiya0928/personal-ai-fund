from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.alerts.btc_dip_alert import AlertAssessment

DEFAULT_SIGNAL_HISTORY_PATH = Path(__file__).resolve().parents[2] / "state" / "signal_history.json"
JST = ZoneInfo("Asia/Tokyo")


def load_signal_history(path: Path = DEFAULT_SIGNAL_HISTORY_PATH) -> dict:
    if not path.exists():
        return {"signals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    signals = payload.get("signals")
    if not isinstance(signals, list):
        raise ValueError("signal_history.json の形式が不正です。")
    return {"signals": signals}


def save_signal_history(payload: dict, path: Path = DEFAULT_SIGNAL_HISTORY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_signal_history(path: Path = DEFAULT_SIGNAL_HISTORY_PATH) -> list[dict]:
    return load_signal_history(path)["signals"]


def _format_signal_timestamp(created_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return (
            created_at[:19]
            .replace("-", "")
            .replace(":", "")
            .replace("T", "_")
        )


def build_signal_record(assessment: AlertAssessment, created_at: Optional[str] = None) -> dict:
    created_at = created_at or assessment.market.as_of_jst
    buy_status = assessment.buy_status
    hold_status = assessment.hold_status
    status_key = hold_status or buy_status
    timestamp_key = _format_signal_timestamp(created_at)
    signal_id = f"{assessment.symbol.lower()}_{timestamp_key}_{status_key.lower()}"
    notification = assessment.notification or {}
    order_proposal = assessment.order_proposal or {}
    return {
        "signal_id": signal_id,
        "created_at": created_at,
        "symbol": assessment.symbol,
        "current_price": assessment.market.current_price,
        "buy_status": buy_status,
        "hold_status": hold_status,
        "should_notify": notification.get("should_notify"),
        "notification_type": notification.get("notification_type"),
        "buy_candidate_line": assessment.next_price_lines.get("buy_candidate_line"),
        "recent_high": assessment.market.recent_high,
        "drop_from_recent_high_pct": assessment.market.drop_from_recent_high_pct,
        "sma200": assessment.market.sma200,
        "above_sma200": assessment.market.above_sma200,
        "reasons": list(assessment.reasons) + list(assessment.action_reasons),
        "order_proposal_id": order_proposal.get("proposal_id"),
    }


def _duplicate_of(existing: dict, record: dict) -> bool:
    return existing.get("signal_id") == record["signal_id"]


def save_signal_record(record: dict, path: Path = DEFAULT_SIGNAL_HISTORY_PATH) -> tuple[dict, bool]:
    payload = load_signal_history(path)
    for existing in payload["signals"]:
        if _duplicate_of(existing, record):
            return existing, False
    payload["signals"].append(record)
    save_signal_history(payload, path)
    return record, True
