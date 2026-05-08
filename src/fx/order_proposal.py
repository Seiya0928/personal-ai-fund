# 実注文なし・研究用シグナルから注文提案だけを作る。
# このモジュールは取引所・ブローカーAPIを一切呼びません。

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from src.fx.models import FXSignal
from src.risk.execution_gate import validate_manual_execution_proposal

DEFAULT_FX_ORDER_PROPOSALS_PATH = Path(__file__).resolve().parents[2] / "state" / "fx_order_proposals.json"
FX_MIN_USD_UNITS = 1_000


@dataclass
class FXOrderProposal:
    proposal_id: str
    created_at: str
    source_signal_id: str
    symbol: str
    side: str
    execution_type: str
    suggested_price: float
    suggested_size: float
    estimated_jpy: float
    reason: str
    source_status: str
    requires_manual_confirmation: bool = True
    send_to_exchange: bool = False
    status: str = "proposed"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    max_loss_jpy: float = 0.0
    rationale: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    note: Optional[str] = None


def load_fx_order_proposals(path: Path = DEFAULT_FX_ORDER_PROPOSALS_PATH) -> dict:
    if not path.exists():
        return {"proposals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("fx_order_proposals.json の形式が不正です。")
    return {"proposals": proposals}


def save_fx_order_proposals(payload: dict, path: Path = DEFAULT_FX_ORDER_PROPOSALS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_fx_order_proposals(path: Path = DEFAULT_FX_ORDER_PROPOSALS_PATH) -> list[dict]:
    return load_fx_order_proposals(path)["proposals"]


def _proposal_id(signal: FXSignal) -> str:
    return f"fx_{signal.signal_id}_{signal.action.lower()}_proposal"


def generate_fx_order_proposal(signal: FXSignal, usd_units: int = FX_MIN_USD_UNITS) -> tuple[Optional[dict], Optional[str]]:
    if signal.symbol != "USD/JPY":
        return None, "USD/JPY 以外はFX注文提案の対象外です。"
    if signal.action not in {"BUY", "SELL"}:
        return None, f"action={signal.action} は注文提案生成対象外です。"
    if signal.stop_loss is None or signal.take_profit is None:
        return None, "stop_loss/take_profit がないため注文提案を生成できません。"
    if usd_units < FX_MIN_USD_UNITS:
        return None, "suggested_size is below FX minimum research lot"

    max_loss_jpy = round(abs(signal.price - signal.stop_loss) * usd_units, 2)
    proposal = FXOrderProposal(
        proposal_id=_proposal_id(signal),
        created_at=signal.timestamp,
        source_signal_id=signal.signal_id,
        symbol=signal.symbol,
        side=signal.action,
        execution_type="LIMIT",
        suggested_price=round(signal.price, 4),
        suggested_size=float(usd_units),
        estimated_jpy=round(signal.price * usd_units, 2),
        reason=f"{signal.action} signal from USD/JPY research module",
        source_status=signal.action,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        max_loss_jpy=max_loss_jpy,
        rationale=list(signal.reasons),
        invalidation_conditions=[
            "FX実注文アダプタが未実装のため、現段階では実行対象にしない",
            "手動確認時に価格、スプレッド、重要指標条件が変化している",
            "STOP_TRADING が有効",
            "DRY_RUN/READ_ONLY または手動承認ゲートを満たさない",
        ],
    )

    payload = asdict(proposal)
    validate_manual_execution_proposal(payload, dry_run=True, read_only=True)
    return payload, None


def save_fx_order_proposal(
    proposal: FXOrderProposal | dict,
    path: Path = DEFAULT_FX_ORDER_PROPOSALS_PATH,
) -> tuple[dict, bool]:
    payload = load_fx_order_proposals(path)
    proposal_payload = asdict(proposal) if isinstance(proposal, FXOrderProposal) else dict(proposal)
    for existing in payload["proposals"]:
        if existing.get("source_signal_id") == proposal_payload["source_signal_id"]:
            return existing, False
    payload["proposals"].append(proposal_payload)
    save_fx_order_proposals(payload, path)
    return proposal_payload, True
