"""FX シグナル履歴（BTCのsignal_historyと同じ思想）。実注文なし・研究用のみ。"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.fx.fx_status import FXAssessment

DEFAULT_FX_SIGNAL_HISTORY_PATH = Path(__file__).resolve().parents[2] / "state" / "fx_signal_history.json"
JST = ZoneInfo("Asia/Tokyo")


def load_fx_signal_history(path: Path = DEFAULT_FX_SIGNAL_HISTORY_PATH) -> dict:
    if not path.exists():
        return {"signals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("signals"), list):
        raise ValueError("fx_signal_history.json の形式が不正です。")
    return payload


def save_fx_signal_history(payload: dict, path: Path = DEFAULT_FX_SIGNAL_HISTORY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_fx_signal_history(path: Path = DEFAULT_FX_SIGNAL_HISTORY_PATH) -> list[dict]:
    return load_fx_signal_history(path)["signals"]


def build_fx_signal_record(
    assessment: FXAssessment,
    created_at: Optional[str] = None,
) -> dict:
    """FXAssessment → signal_history レコード dict を生成する。"""
    ts = created_at or assessment.market_data_timestamp
    ts_key = _format_ts(ts)
    signal_id = f"usdjpy_{ts_key}_{assessment.fx_status.lower()}"
    return {
        "signal_id": signal_id,
        "created_at": ts,
        "symbol": assessment.symbol,
        "action": assessment.action,
        "fx_status": assessment.fx_status,
        "next_action": assessment.next_action,
        "current_price": assessment.current_price,
        "market_data_timestamp": assessment.market_data_timestamp,
        "stale_level": assessment.stale_level,
        "stale_reason": assessment.stale_reason,
        "stop_loss": assessment.stop_loss,
        "take_profit": assessment.take_profit,
        "reasons": list(assessment.reasons),
        "skip_reason": assessment.skip_reason,
        "order_proposal_id": assessment.order_proposal_id,
        "paper_trade_ids": list(assessment.paper_trade_ids),
    }


def save_fx_signal_record(
    record: dict,
    path: Path = DEFAULT_FX_SIGNAL_HISTORY_PATH,
) -> tuple[dict, bool]:
    """重複（同じsignal_id）はスキップ。(stored, is_new)を返す。"""
    payload = load_fx_signal_history(path)
    for existing in payload["signals"]:
        if existing.get("signal_id") == record["signal_id"]:
            return existing, False
    payload["signals"].append(record)
    save_fx_signal_history(payload, path)
    return record, True


def _format_ts(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST).strftime("%Y%m%d_%H%M%S")
    except (ValueError, TypeError):
        return ts_str[:19].replace("-", "").replace(":", "").replace("T", "_")
