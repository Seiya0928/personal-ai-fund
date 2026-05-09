"""
FX dry-run注文記録。実注文なし。
- manual approval required: "RECORD DRY RUN ORDER"
- STOP_TRADING check
- duplicate guard
- asset_class: "fx" for identification
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_FX_DRY_RUN_ORDERS_PATH = Path(__file__).resolve().parents[2] / "state" / "fx_dry_run_orders.json"
DRY_RUN_APPROVAL_PHRASE = "RECORD DRY RUN ORDER"
JST = ZoneInfo("Asia/Tokyo")


def load_fx_dry_run_orders(path: Path = DEFAULT_FX_DRY_RUN_ORDERS_PATH) -> dict:
    if not path.exists():
        return {"orders": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    orders = payload.get("orders")
    if not isinstance(orders, list):
        raise ValueError("fx_dry_run_orders.json の形式が不正です。")
    return {"orders": orders}


def save_fx_dry_run_orders(payload: dict, path: Path = DEFAULT_FX_DRY_RUN_ORDERS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_fx_dry_run_orders(path: Path = DEFAULT_FX_DRY_RUN_ORDERS_PATH) -> list[dict]:
    return load_fx_dry_run_orders(path)["orders"]


def record_fx_dry_run_order(
    proposal: dict,
    approval_input: str,
    stop_trading_path: Optional[Path] = None,
    path: Path = DEFAULT_FX_DRY_RUN_ORDERS_PATH,
    dry_run: bool = True,
    read_only: bool = True,
) -> tuple[Optional[dict], str]:
    """
    FX dry-run注文を記録する。
    Returns (order_dict, reason_str).
    order_dict is None if recording was skipped/rejected.
    """
    # 1. DRY_RUN / READ_ONLY check
    if not dry_run:
        return None, "DRY_RUN=false のため記録不可"
    if not read_only:
        return None, "READ_ONLY=false のため記録不可"
    # 2. STOP_TRADING
    root = stop_trading_path or Path(__file__).resolve().parents[2] / "STOP_TRADING"
    if root.exists():
        return None, "STOP_TRADING が有効のため記録しません"
    # 3. Approval phrase
    if approval_input.strip() != DRY_RUN_APPROVAL_PHRASE:
        return None, f"承認フレーズ不一致。'{DRY_RUN_APPROVAL_PHRASE}' を入力してください"
    # 4. Validate proposal
    if proposal.get("send_to_exchange", True):
        return None, "send_to_exchange=true の提案は記録できません"
    if not proposal.get("requires_manual_confirmation", False):
        return None, "requires_manual_confirmation=false の提案は記録できません"
    # 5. Duplicate guard by source_proposal_id
    payload = load_fx_dry_run_orders(path)
    proposal_id = proposal.get("proposal_id", "")
    for existing in payload["orders"]:
        if existing.get("source_proposal_id") == proposal_id:
            return existing, f"重複スキップ: {proposal_id}"
    # 6. Build and save
    now_jst = datetime.now(JST).isoformat(timespec="seconds")
    order = {
        "order_id": f"fx_dry_{proposal_id}_{now_jst[:10].replace('-', '')}",
        "asset_class": "fx",
        "source_proposal_id": proposal_id,
        "symbol": proposal.get("symbol", "USD/JPY"),
        "side": proposal.get("side"),
        "suggested_price": proposal.get("suggested_price"),
        "stop_loss": proposal.get("stop_loss"),
        "take_profit": proposal.get("take_profit"),
        "max_loss_jpy": proposal.get("max_loss_jpy"),
        "suggested_size": proposal.get("suggested_size"),
        "status": "dry_run_recorded",
        "send_to_exchange": False,
        "dry_run": True,
        "read_only": True,
        "recorded_at": now_jst,
        "note": "FX dry-run注文記録。実注文なし。",
    }
    payload["orders"].append(order)
    save_fx_dry_run_orders(payload, path)
    return order, "dry-run注文記録済み"
