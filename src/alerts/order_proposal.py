from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Optional

from src.alerts.btc_dip_alert import AlertAssessment, BTC_JPY_ALERT_CONFIG
from src.execution.gmo_symbols import to_gmo_spot_symbol
from src.risk.order_sizing import BTC_JPY_MIN_QUANTITY, BTC_JPY_QUANTITY_STEP, size_btc_jpy_limit_buy

DEFAULT_ORDER_PROPOSALS_PATH = Path(__file__).resolve().parents[2] / "state" / "order_proposals.json"
ALLOWED_PROPOSAL_STATUSES = {"proposed", "ignored", "manually_executed", "rejected", "dry_run_recorded"}


@dataclass
class OrderProposal:
    proposal_id: str
    created_at: str
    symbol: str
    side: str
    execution_type: str
    suggested_price: float
    suggested_size: float
    estimated_jpy: float
    reason: str
    source_status: str
    requires_manual_confirmation: bool
    send_to_exchange: bool
    status: str = "proposed"
    risk_notes: Optional[list[str]] = None
    gmo_spot_symbol: Optional[str] = None
    position_id: Optional[str] = None
    estimated_pnl_pct: Optional[float] = None
    estimated_pnl_jpy: Optional[float] = None
    note: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_loss_jpy: Optional[float] = None
    rationale: Optional[list[str]] = None
    invalidation_conditions: Optional[list[str]] = None
    source_signal_id: Optional[str] = None


def _floor_quantity(quantity: float) -> Decimal:
    raw = Decimal(str(quantity))
    return (raw / BTC_JPY_QUANTITY_STEP).to_integral_value(rounding=ROUND_DOWN) * BTC_JPY_QUANTITY_STEP


def _proposal_date_key(created_at: str) -> str:
    return datetime.fromisoformat(created_at).date().isoformat()


def _build_proposal_id(symbol: str, side: str, source_status: str, suggested_price: float, created_at: str) -> str:
    symbol_key = symbol.lower()
    source_key = source_status.lower()
    date_key = _proposal_date_key(created_at).replace("-", "")
    return f"{symbol_key}_{date_key}_{side.lower()}_{source_key}_{int(suggested_price)}"


def load_order_proposals(path: Path = DEFAULT_ORDER_PROPOSALS_PATH) -> dict:
    if not path.exists():
        return {"proposals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("order_proposals.json の形式が不正です。")
    return {"proposals": proposals}


def save_order_proposals(payload: dict, path: Path = DEFAULT_ORDER_PROPOSALS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_order_proposals(path: Path = DEFAULT_ORDER_PROPOSALS_PATH) -> list[dict]:
    return load_order_proposals(path)["proposals"]


def mark_order_proposal(
    proposal_id: str,
    status: str,
    note: str = "",
    path: Path = DEFAULT_ORDER_PROPOSALS_PATH,
) -> dict:
    if status not in ALLOWED_PROPOSAL_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_PROPOSAL_STATUSES))}")
    payload = load_order_proposals(path)
    for proposal in payload["proposals"]:
        if proposal["proposal_id"] == proposal_id:
            proposal["status"] = status
            proposal["note"] = note
            save_order_proposals(payload, path)
            return proposal
    raise ValueError(f"proposal not found: {proposal_id}")


def _duplicate_of(existing: dict, proposal: OrderProposal) -> bool:
    return (
        existing.get("symbol") == proposal.symbol
        and existing.get("side") == proposal.side
        and existing.get("source_status") == proposal.source_status
        and float(existing.get("suggested_price", 0.0)) == float(proposal.suggested_price)
        and existing.get("position_id") == proposal.position_id
        and existing.get("created_at", "")[:10] == proposal.created_at[:10]
    )


def _buy_risk_fields(assessment: AlertAssessment, suggested_price: float, suggested_size: float, source_status: str) -> dict:
    params = BTC_JPY_ALERT_CONFIG.params
    stop_loss = round(suggested_price * (1 - params["stop_loss_pct"] / 100), 0)
    take_profit = round(suggested_price * (1 + params["take_profit_pct"] / 100), 0)
    max_loss_jpy = round(max(suggested_price - stop_loss, 0) * suggested_size, 2)
    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "max_loss_jpy": max_loss_jpy,
        "rationale": [
            f"source_status={source_status}",
            f"buy_candidate_line={assessment.next_price_lines.get('buy_candidate_line')}",
            f"current_price={assessment.market.current_price}",
            *assessment.reasons[:3],
        ],
        "invalidation_conditions": [
            "手動確認時に価格が注文案から大きく乖離している",
            "STOP_TRADING が有効",
            "DRY_RUN/READ_ONLY または手動承認ゲートを満たさない",
            "重要イベント、価格データ不足、スプレッド異常など安全確認に反する",
        ],
    }


def _sell_risk_fields(assessment: AlertAssessment, position: dict, suggested_price: float, suggested_size: float, source_status: str) -> dict:
    stop_loss = float(position.get("stop_loss_line") or suggested_price)
    take_profit = float(position.get("take_profit_line") or suggested_price)
    estimated_pnl_jpy = position.get("unrealized_pnl_jpy")
    max_loss_jpy = round(max(0.0, -float(estimated_pnl_jpy or 0.0)), 2)
    if max_loss_jpy == 0.0:
        entry_price = float(position.get("entry_price") or suggested_price)
        max_loss_jpy = round(max(entry_price - stop_loss, 0) * suggested_size, 2)
    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "max_loss_jpy": max_loss_jpy,
        "rationale": [
            f"source_status={source_status}",
            f"position_id={position.get('id')}",
            f"current_price={assessment.market.current_price}",
            *assessment.action_reasons[:3],
        ],
        "invalidation_conditions": [
            "対象ポジションが存在しない、または手動で解消済み",
            "手動確認時に価格が注文案から大きく乖離している",
            "STOP_TRADING が有効",
            "DRY_RUN/READ_ONLY または手動承認ゲートを満たさない",
        ],
    }


def save_order_proposal(proposal: OrderProposal | dict, path: Path = DEFAULT_ORDER_PROPOSALS_PATH) -> tuple[dict, bool]:
    payload = load_order_proposals(path)
    proposal_payload = asdict(proposal) if isinstance(proposal, OrderProposal) else dict(proposal)
    proposal_obj = OrderProposal(**proposal_payload)
    for existing in payload["proposals"]:
        if _duplicate_of(existing, proposal_obj):
            return existing, False
    stored = asdict(proposal_obj)
    payload["proposals"].append(stored)
    save_order_proposals(payload, path)
    return stored, True


def generate_order_proposal(
    assessment: AlertAssessment,
    proposal_jpy: float,
    source_status: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    source_status = source_status or (assessment.hold_status or assessment.buy_status)
    created_at = assessment.market.as_of_jst
    if source_status == "BUY_CANDIDATE":
        suggested_price = int(assessment.next_price_lines.get("buy_candidate_line", 0) or 0)
        if suggested_price <= 0:
            return None, "buy_candidate_line がないため BUY proposal を生成できません。"
        try:
            sized = size_btc_jpy_limit_buy(proposal_jpy, suggested_price)
        except ValueError as exc:
            return None, str(exc)
        proposal = OrderProposal(
            proposal_id=_build_proposal_id(assessment.symbol, "BUY", source_status, sized.price, created_at),
            created_at=created_at,
            symbol=assessment.symbol,
            side="BUY",
            execution_type="LIMIT",
            suggested_price=sized.price,
            suggested_size=sized.quantity,
            estimated_jpy=round(sized.amount_jpy, 2),
            reason="買い条件に一致したため、手動確認用のBUY注文案を生成",
            source_status=source_status,
            risk_notes=[
                "実発注は行っていません。",
                "手動確認用の注文案です。",
                "send_to_exchange は常に false です。",
            ],
            gmo_spot_symbol=to_gmo_spot_symbol(assessment.symbol),
            requires_manual_confirmation=True,
            send_to_exchange=False,
            **_buy_risk_fields(assessment, sized.price, sized.quantity, source_status),
        )
        return asdict(proposal), None

    if source_status in {"TAKE_PROFIT_CANDIDATE", "STOP_LOSS_CANDIDATE", "TIMEOUT_EXIT_CANDIDATE"}:
        position = assessment.position or {}
        raw_size = position.get("position_size")
        if raw_size is None:
            return None, "position_size がないため SELL proposal を生成できません。"
        rounded_size = _floor_quantity(float(raw_size))
        if rounded_size < BTC_JPY_MIN_QUANTITY:
            return None, "position_size is below GMO BTC_JPY minimum quantity"
        if source_status == "TAKE_PROFIT_CANDIDATE":
            suggested_price = int(position["take_profit_line"])
            reason = "利確条件に到達したため、手動確認用のSELL注文案を生成"
        elif source_status == "STOP_LOSS_CANDIDATE":
            suggested_price = int(position["stop_loss_line"])
            reason = "損切り条件に到達したため、手動確認用のSELL注文案を生成"
        else:
            suggested_price = int(assessment.market.current_price)
            reason = "最大保有日数に到達したため、手動確認用のSELL注文案を生成"
        estimated_jpy = round(float(rounded_size) * suggested_price, 2)
        proposal = OrderProposal(
            proposal_id=_build_proposal_id(assessment.symbol, "SELL", source_status, suggested_price, created_at),
            created_at=created_at,
            symbol=assessment.symbol,
            side="SELL",
            execution_type="LIMIT",
            suggested_price=float(suggested_price),
            suggested_size=float(rounded_size),
            estimated_jpy=estimated_jpy,
            estimated_pnl_pct=position.get("unrealized_pnl_pct"),
            estimated_pnl_jpy=position.get("unrealized_pnl_jpy"),
            reason=reason,
            source_status=source_status,
            gmo_spot_symbol=to_gmo_spot_symbol(assessment.symbol),
            position_id=position.get("id"),
            requires_manual_confirmation=True,
            send_to_exchange=False,
            **_sell_risk_fields(assessment, position, float(suggested_price), float(rounded_size), source_status),
        )
        return asdict(proposal), None

    return None, f"source_status={source_status} は注文案生成対象外です。"


def format_order_proposal_for_message(proposal: Optional[dict]) -> str:
    if not proposal:
        return ""
    lines = [
        "",
        "注文案:",
        f"- side: {proposal['side']}",
        f"- execution_type: {proposal['execution_type']}",
        f"- suggested_price: ¥{proposal['suggested_price']:,.0f}",
        f"- suggested_size: {proposal['suggested_size']}",
        f"- estimated_jpy: ¥{proposal['estimated_jpy']:,.2f}",
        f"- stop_loss: ¥{proposal.get('stop_loss', 0):,.0f}",
        f"- take_profit: ¥{proposal.get('take_profit', 0):,.0f}",
        f"- max_loss_jpy: ¥{proposal.get('max_loss_jpy', 0):,.2f}",
        "- 実発注は行っていません。手動確認用です。",
    ]
    return "\n".join(lines)
