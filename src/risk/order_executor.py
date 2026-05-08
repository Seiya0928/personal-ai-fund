"""
order_executor.py — 注文発行と pending_orders 登録を一体管理する。

place_order() を呼ぶと:
  1. RiskManager.check_order_allowed() が通っていることを前提とする
  2. DRY_RUN=false かつ READ_ONLY=false の場合、手動承認ゲートを通過する必要がある
  3. GMOPrivateAdapter.place_order() で発注（DRY_RUN=true はモック）
  4. pending_orders に OPEN として登録
  5. 仮ポジション（pending分）を ExecutionState に反映

呼び出し元は RiskManager.pre_trade_sync() → check_order_allowed() →
OrderExecutor.place_order() の順で使う。
"""
from __future__ import annotations

import time
from typing import Optional

from src.risk.execution_state import ExecutionState, ExecutionStore
from src.risk.pending_orders import PendingOrderStore, PendingOrder, STATUS_OPEN
from src.risk.duplicate_order_guard import DuplicateOrderGuard
from src.risk.manual_approval import require_manual_approval, OrderPlan
from src.utils.logger import get_logger

log = get_logger(__name__)


class ManualApprovalDeniedError(Exception):
    """手動承認が得られなかったときに送出する。"""


class OrderExecutor:
    def __init__(
        self,
        adapter,                           # GMOPrivateAdapter
        execution_store: ExecutionStore,
        pending_store: PendingOrderStore,
        guard: DuplicateOrderGuard,
        dry_run: bool = True,
    ):
        self.adapter = adapter
        self.execution_store = execution_store
        self.pending_store = pending_store
        self.guard = guard
        self.dry_run = dry_run
        # テストで差し替え可能な承認関数（デフォルトは本物の端末入力）
        self._approval_fn = require_manual_approval

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        amount_jpy: float,
        state: Optional[ExecutionState] = None,
    ) -> PendingOrder:
        """
        発注して PendingOrder を返す。

        DRY_RUN=true  : adapter がモック応答を返す（実際には送信しない）
        DRY_RUN=false : adapter が実際に GMO API へ送信する

        state が渡された場合、pending 分を仮ポジションとして反映する。
        """
        # 1. 手動承認ゲート（DRY_RUN=false かつ adapter.read_only=false のとき必須）
        is_live = (
            not self.dry_run
            and hasattr(self.adapter, "read_only")
            and not self.adapter.read_only
        )
        if is_live:
            plan = OrderPlan(
                symbol=symbol,
                side=side,
                order_type=order_type,
                price=price,
                quantity=quantity,
                amount_jpy=amount_jpy,
            )
            approved = self._approval_fn(plan)
            # 承認結果のみログに残す（フレーズ自体は記録しない）
            log.info(f"手動承認結果: {'承認' if approved else '拒否'} ({symbol} {side} ¥{amount_jpy:,.0f})")
            if not approved:
                raise ManualApprovalDeniedError(
                    "手動承認が得られませんでした。発注を中止します。"
                )

        # 2. 発注（DRY_RUN の場合はモック）
        order_resp = self.adapter.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
        )
        order_id = order_resp["order_id"]

        # 3. pending_orders に登録
        pending = PendingOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            amount_jpy=amount_jpy,
            status=STATUS_OPEN,
            is_dry_run=self.dry_run,
            created_at=time.time(),
        )
        self.pending_store.save(pending)

        # 4. 重複ガードに記録
        self.guard.record(symbol, side, order_type, amount_jpy,
                          is_dry_run=self.dry_run, status="pending")

        log.info(
            f"注文登録: order_id={order_id} {symbol} {side} "
            f"{quantity:.8f}BTC @ ¥{price:,.0f} dry_run={self.dry_run}"
        )

        # 5. 仮ポジション反映（pending 分を先行して state に足す）
        #    実口座との乖離を最小化するため、約定前でも BTC を仮確保する
        if state and side == "BUY":
            state.btc_held += quantity
            state.balance_jpy -= amount_jpy
            log.info(
                f"仮ポジション反映(BUY pending): btc_held={state.btc_held:.8f} "
                f"balance_jpy=¥{state.balance_jpy:,.0f}"
            )
        elif state and side == "SELL":
            state.btc_held = max(0.0, state.btc_held - quantity)
            log.info(
                f"仮ポジション反映(SELL pending): btc_held={state.btc_held:.8f}"
            )

        return pending
