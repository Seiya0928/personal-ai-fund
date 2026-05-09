# BTCのOrderProposalをCommonOrderProposalに変換するアダプタ。
# 元のOrderProposalは変更しない。実注文APIは呼ばない。
from __future__ import annotations

from typing import Optional

from src.alerts.order_proposal import OrderProposal
from src.proposals.common_proposal import CommonOrderProposal

_BTC_STATUS_MAP = {
    "proposed": "proposed",
    "dry_run_recorded": "dry_run_recorded",
    "rejected": "rejected",
    "ignored": "rejected",
    "manually_executed": "approved",
}


def _map_btc_side(side: str, source_status: str) -> str:
    if side.upper() == "BUY":
        return "buy"
    # SELL: 詳細な終了理由をsource_statusから判断
    source = source_status.upper()
    if source == "TAKE_PROFIT_CANDIDATE":
        return "take_profit"
    if source == "STOP_LOSS_CANDIDATE":
        return "stop_loss"
    if source == "TIMEOUT_EXIT_CANDIDATE":
        return "timeout_exit"
    return "sell"


def _compute_expected_rr(
    side: str,
    price: Optional[float],
    stop_loss: Optional[float],
    take_profit: Optional[float],
) -> Optional[float]:
    if None in (price, stop_loss, take_profit):
        return None
    assert price is not None and stop_loss is not None and take_profit is not None
    if side == "buy":
        risk = price - stop_loss
        reward = take_profit - price
    else:
        risk = stop_loss - price
        reward = price - take_profit
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def btc_proposal_to_common(proposal: OrderProposal) -> CommonOrderProposal:
    """BTC OrderProposal → CommonOrderProposal。元のproposalは変更しない。"""
    mapped_side = _map_btc_side(proposal.side, proposal.source_status)
    mapped_status = _BTC_STATUS_MAP.get(proposal.status, "proposed")
    expected_rr = _compute_expected_rr(
        mapped_side,
        proposal.suggested_price,
        proposal.stop_loss,
        proposal.take_profit,
    )
    risk_jpy = float(proposal.max_loss_jpy or 0.0)
    return CommonOrderProposal(
        proposal_id=proposal.proposal_id,
        asset_class="crypto",
        instrument="BTC_JPY",
        strategy_name="btc_dip_alert",
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
            "source_status": proposal.source_status,
            "suggested_price": proposal.suggested_price,
            "suggested_size": proposal.suggested_size,
            "estimated_jpy": proposal.estimated_jpy,
            "stop_loss": proposal.stop_loss,
            "take_profit": proposal.take_profit,
            "position_id": proposal.position_id,
            "gmo_spot_symbol": proposal.gmo_spot_symbol,
            "rationale": proposal.rationale or [],
            "invalidation_conditions": proposal.invalidation_conditions or [],
        },
    )
