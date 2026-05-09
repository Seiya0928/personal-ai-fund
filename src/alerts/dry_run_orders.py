from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.alerts.order_proposal import (
    DEFAULT_ORDER_PROPOSALS_PATH,
    list_order_proposals,
    mark_order_proposal,
)
from src.execution.gmo_symbols import to_gmo_spot_symbol
from src.risk.execution_gate import (
    DEFAULT_STOP_TRADING_FILE,
    require_approval_phrase,
    validate_limit_order_shape,
    validate_manual_execution_proposal,
)
from src.risk.kill_switch import KillSwitch
from src.risk.order_sizing import BTC_JPY_MIN_QUANTITY

DEFAULT_DRY_RUN_ORDERS_PATH = Path(__file__).resolve().parents[2] / "state" / "dry_run_orders.json"
DRY_RUN_ORDER_APPROVAL_PHRASE = "RECORD DRY RUN ORDER"
DRY_RUN_ORDER_RECORDED_NOTE = "DRY_RUN order recorded. No exchange order sent."
DRY_RUN_ALLOWED_SOURCE_STATUSES = {
    "BUY_CANDIDATE",
    "TAKE_PROFIT_CANDIDATE",
    "STOP_LOSS_CANDIDATE",
    "TIMEOUT_EXIT_CANDIDATE",
}
JST = ZoneInfo("Asia/Tokyo")


def load_dry_run_orders(path: Path = DEFAULT_DRY_RUN_ORDERS_PATH) -> dict:
    if not path.exists():
        return {"dry_run_orders": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    orders = payload.get("dry_run_orders")
    if not isinstance(orders, list):
        raise ValueError("dry_run_orders.json の形式が不正です。")
    return {"dry_run_orders": orders}


def save_dry_run_orders(payload: dict, path: Path = DEFAULT_DRY_RUN_ORDERS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_dry_run_orders(path: Path = DEFAULT_DRY_RUN_ORDERS_PATH) -> list[dict]:
    return load_dry_run_orders(path)["dry_run_orders"]


def find_order_proposal(proposal_id: str, path: Path = DEFAULT_ORDER_PROPOSALS_PATH) -> dict:
    for proposal in list_order_proposals(path):
        if proposal.get("proposal_id") == proposal_id:
            return proposal
    raise ValueError(f"proposal not found: {proposal_id}")


def build_order_body_from_proposal(proposal: dict) -> dict:
    price = float(proposal.get("suggested_price", 0.0))
    quantity = float(proposal.get("suggested_size", 0.0))
    return {
        "symbol": to_gmo_spot_symbol(proposal["symbol"]),
        "side": proposal["side"],
        "executionType": proposal["execution_type"],
        "price": str(int(price)),
        "size": f"{quantity:.8f}",
    }


def _env_true(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def validate_dry_run_safety(
    proposal: dict,
    order_body: dict,
    dry_run: bool,
    read_only: bool,
    stop_trading_file: Path = DEFAULT_STOP_TRADING_FILE,
) -> None:
    if proposal.get("source_status") not in DRY_RUN_ALLOWED_SOURCE_STATUSES:
        raise ValueError("proposal.source_status is not dry-run order eligible")
    validate_manual_execution_proposal(
        proposal,
        dry_run=dry_run,
        read_only=read_only,
        stop_trading_file=stop_trading_file,
    )
    validate_limit_order_shape(
        order_body=order_body,
        expected_exchange_symbol=str(proposal.get("gmo_spot_symbol")),
        minimum_size=BTC_JPY_MIN_QUANTITY,
    )


def _next_dry_run_order_id(symbol: str, created_at: str, existing_orders: list[dict]) -> str:
    date_key = datetime.fromisoformat(created_at).astimezone(JST).strftime("%Y%m%d")
    prefix = f"dry_{symbol.lower()}_{date_key}_"
    current = [
        int(order["dry_run_order_id"].rsplit("_", 1)[1])
        for order in existing_orders
        if str(order.get("dry_run_order_id", "")).startswith(prefix)
    ]
    return f"{prefix}{max(current, default=0) + 1:03d}"


def build_dry_run_order_record(
    proposal: dict,
    order_body: dict,
    created_at: str,
    existing_orders: list[dict],
    read_only: bool,
    dry_run: bool,
) -> dict:
    source_signal_id = proposal.get("source_signal_id") or proposal.get("signal_id")
    price = int(order_body["price"])
    size = order_body["size"]
    return {
        "dry_run_order_id": _next_dry_run_order_id(proposal["symbol"], created_at, existing_orders),
        "created_at": created_at,
        "source_order_proposal_id": proposal["proposal_id"],
        "source_signal_id": source_signal_id,
        "symbol": proposal["symbol"],
        "gmo_spot_symbol": order_body["symbol"],
        "side": order_body["side"],
        "execution_type": order_body["executionType"],
        "price": price,
        "entry_price": price,
        "size": size,
        "estimated_jpy": proposal["estimated_jpy"],
        "notional_jpy": proposal["estimated_jpy"],
        "stop_loss": proposal.get("stop_loss"),
        "take_profit": proposal.get("take_profit"),
        "max_loss_jpy": proposal.get("max_loss_jpy"),
        "reason": proposal["source_status"],
        "status": "dry_run_recorded",
        "send_to_exchange": False,
        "requires_manual_confirmation": True,
        "approval_phrase_confirmed": True,
        "approval_status": "confirmed",
        "read_only": read_only,
        "dry_run": dry_run,
    }


def _same_source_signal_order(existing: dict, record: dict) -> bool:
    source_signal_id = record.get("source_signal_id")
    return (
        source_signal_id not in {None, ""}
        and existing.get("source_signal_id") == source_signal_id
        and existing.get("symbol") == record.get("symbol")
        and existing.get("side") == record.get("side")
        and int(existing.get("price", 0)) == int(record.get("price", 0))
    )


def save_dry_run_order_record(record: dict, path: Path = DEFAULT_DRY_RUN_ORDERS_PATH) -> tuple[dict, bool]:
    payload = load_dry_run_orders(path)
    for existing in payload["dry_run_orders"]:
        if existing.get("source_order_proposal_id") == record["source_order_proposal_id"] or _same_source_signal_order(existing, record):
            return existing, False
    payload["dry_run_orders"].append(record)
    save_dry_run_orders(payload, path)
    return record, True


def _find_existing_dry_run_order_for_proposal(proposal_id: str, path: Path) -> Optional[dict]:
    for order in list_dry_run_orders(path):
        if order.get("source_order_proposal_id") == proposal_id:
            return order
    return None


def _validate_runtime_safety(dry_run: bool, read_only: bool, stop_trading_file: Path) -> None:
    if not dry_run:
        raise ValueError("DRY_RUN must be true")
    if not read_only:
        raise ValueError("READ_ONLY must be true")
    if KillSwitch(stop_trading_file).is_active():
        raise ValueError("kill switch is active")


def record_dry_run_order_from_proposal(
    proposal_id: str,
    approval_phrase: str,
    dry_run: bool,
    read_only: bool,
    order_proposals_path: Path = DEFAULT_ORDER_PROPOSALS_PATH,
    dry_run_orders_path: Path = DEFAULT_DRY_RUN_ORDERS_PATH,
    created_at: Optional[str] = None,
    stop_trading_file: Path = DEFAULT_STOP_TRADING_FILE,
) -> tuple[dict, dict]:
    require_approval_phrase(approval_phrase, DRY_RUN_ORDER_APPROVAL_PHRASE)
    proposal = find_order_proposal(proposal_id, order_proposals_path)
    order_body = build_order_body_from_proposal(proposal)
    _validate_runtime_safety(dry_run, read_only, stop_trading_file)
    existing_order = _find_existing_dry_run_order_for_proposal(proposal_id, dry_run_orders_path)
    if existing_order is not None:
        return existing_order, order_body
    validate_dry_run_safety(
        proposal,
        order_body,
        dry_run=dry_run,
        read_only=read_only,
        stop_trading_file=stop_trading_file,
    )
    created_at = created_at or datetime.now(JST).replace(microsecond=0).isoformat()
    existing_orders = list_dry_run_orders(dry_run_orders_path)
    record = build_dry_run_order_record(proposal, order_body, created_at, existing_orders, read_only, dry_run)
    stored, _ = save_dry_run_order_record(record, dry_run_orders_path)
    mark_order_proposal(
        proposal_id=proposal_id,
        status="dry_run_recorded",
        note=DRY_RUN_ORDER_RECORDED_NOTE,
        path=order_proposals_path,
    )
    return stored, order_body
