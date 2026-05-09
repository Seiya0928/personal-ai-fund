# FXのFXOrderProposalをCommonOrderProposalに変換するアダプタ。
# 元のFXOrderProposalは変更しない。実注文APIは呼ばない。
from __future__ import annotations

from typing import Optional

from src.fx.order_proposal import FXOrderProposal
from src.proposals.common_proposal import CommonOrderProposal

_FX_STATUS_MAP = {
    "proposed": "proposed",
    "dry_run_recorded": "dry_run_recorded",
    "rejected": "rejected",
    "approved": "approved",
    "expired": "expired",
}


def _map_fx_side(side: str) -> str:
    return "buy" if side.upper() == "BUY" else "sell"


def _compute_expected_rr(
    side: str,
    price: float,
    stop_loss: float,
    take_profit: float,
) -> Optional[float]:
    if side == "buy":
        risk = price - stop_loss
        reward = take_profit - price
    else:
        risk = stop_loss - price
        reward = price - take_profit
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def fx_proposal_to_common(proposal: FXOrderProposal) -> CommonOrderProposal:
    """FXOrderProposal → CommonOrderProposal。元のproposalは変更しない。"""
    mapped_side = _map_fx_side(proposal.side)
    mapped_status = _FX_STATUS_MAP.get(proposal.status, "proposed")
    expected_rr = _compute_expected_rr(
        mapped_side,
        proposal.suggested_price,
        proposal.stop_loss,
        proposal.take_profit,
    )
    risk_jpy = float(proposal.max_loss_jpy or 0.0)
    return CommonOrderProposal(
        proposal_id=proposal.proposal_id,
        asset_class="fx",
        instrument="USD_JPY",
        strategy_name="fx_ema_h1",
        side=mapped_side,
        status=mapped_status,
        risk_jpy=risk_jpy,
        max_loss_jpy=risk_jpy,
        expected_rr=expected_rr,
        confidence=None,
        reason=proposal.reason,
        created_at=proposal.created_at,
        expires_at=None,
        metadata={
            "source_signal_id": proposal.source_signal_id,
            "source_status": proposal.source_status,
            "suggested_price": proposal.suggested_price,
            "suggested_size": proposal.suggested_size,
            "estimated_jpy": proposal.estimated_jpy,
            "stop_loss": proposal.stop_loss,
            "take_profit": proposal.take_profit,
            "rationale": list(proposal.rationale),
            "invalidation_conditions": list(proposal.invalidation_conditions),
        },
    )
