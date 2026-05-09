"""FX ステータス定数とNext Action定義。実注文なし・研究用のみ。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional

FXStatusType = Literal[
    "FX_SKIP",
    "FX_WATCH",
    "FX_CANDIDATE",
    "FX_TAKE_PROFIT_CANDIDATE",
    "FX_STOP_LOSS_CANDIDATE",
    "FX_TIMEOUT_EXIT_CANDIDATE",
    "FX_STALE_INVALID",
]

NEXT_ACTION: dict[str, str] = {
    "FX_SKIP":                   "何もしない。記録のみ。",
    "FX_WATCH":                  "監視のみ。手動エントリーしない。注文案は作らない。",
    "FX_CANDIDATE":              "order proposalを確認し、必要ならdry-run注文記録を作る。実注文はまだしない。",
    "FX_TAKE_PROFIT_CANDIDATE":  "決済proposalを確認し、dry-run決済記録を作る。実注文はまだしない。",
    "FX_STOP_LOSS_CANDIDATE":    "損切りproposalを確認し、損切りリハーサルを優先する。実注文はまだしない。",
    "FX_TIMEOUT_EXIT_CANDIDATE": "保有期限切れ候補として決済proposalを確認する。実注文はまだしない。",
    "FX_STALE_INVALID":          "市場データが古いため判断無効。fetch/health checkを確認。",
}


def get_next_action(status: str) -> str:
    return NEXT_ACTION.get(status, "不明なステータス。")


def signal_action_to_fx_status(
    action: str,  # BUY/SELL/WATCH/SKIP from SignalEngine
    is_stale_invalid: bool = False,
    open_position_exit_reason: Optional[str] = None,  # TAKE_PROFIT/STOP_LOSS/TIMEOUT when has open position
) -> str:
    """
    SignalEngine のアクション → FX ステータス変換。
    open_position_exit_reason が指定された場合は決済系ステータスを優先する。
    実注文なし・研究用のみ。
    """
    if is_stale_invalid:
        return "FX_STALE_INVALID"
    if open_position_exit_reason == "TAKE_PROFIT":
        return "FX_TAKE_PROFIT_CANDIDATE"
    if open_position_exit_reason == "STOP_LOSS":
        return "FX_STOP_LOSS_CANDIDATE"
    if open_position_exit_reason == "TIMEOUT":
        return "FX_TIMEOUT_EXIT_CANDIDATE"
    if action == "SKIP":
        return "FX_SKIP"
    if action == "WATCH":
        return "FX_WATCH"
    if action in ("BUY", "SELL"):
        return "FX_CANDIDATE"
    return "FX_SKIP"


@dataclass
class FXAssessment:
    """
    FX シグナル総合評価。
    実注文なし・研究用のみ。
    """
    signal_id: str
    symbol: str
    action: str               # BUY/SELL/WATCH/SKIP from SignalEngine
    fx_status: str            # FX_SKIP/FX_WATCH/FX_CANDIDATE/...
    next_action: str          # 日本語 next action テキスト
    current_price: float
    market_data_timestamp: str
    stale_level: str          # "fresh" | "warning" | "invalid"
    stale_reason: str
    is_stale_invalid: bool
    stop_loss: Optional[float]
    take_profit: Optional[float]
    reasons: list[str] = field(default_factory=list)
    skip_reason: Optional[str] = None
    open_position_exit_reason: Optional[str] = None
    order_proposal_id: Optional[str] = None
    paper_trade_ids: list[str] = field(default_factory=list)
