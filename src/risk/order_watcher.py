"""
order_watcher.py — 未約定注文の監視・約定処理・タイムアウトキャンセル。

watch_once() を呼ぶたびに OPEN の注文を1件ずつチェックする。
- FILLED   → executions に保存、execution_state を更新、pending を FILLED に
- CANCELLED/EXPIRED → pending を更新してログ
- OPEN かつタイムアウト → キャンセル発行

定期実行する場合は scripts/ から threading.Timer や while ループで呼ぶ。
"""
from __future__ import annotations

import time
from typing import Optional

from src.risk.execution_state import ExecutionState, ExecutionStore, Execution
from src.risk.pending_orders import PendingOrderStore, STATUS_OPEN, STATUS_FILLED, STATUS_CANCELLED, STATUS_EXPIRED
from src.utils.logger import get_logger

log = get_logger(__name__)


class OrderWatcher:
    def __init__(
        self,
        adapter,                           # GMOPrivateAdapter
        execution_store: ExecutionStore,
        pending_store: PendingOrderStore,
        order_timeout_seconds: int = 60,
        dry_run: bool = True,
    ):
        self.adapter = adapter
        self.execution_store = execution_store
        self.pending_store = pending_store
        self.order_timeout_seconds = order_timeout_seconds
        self.dry_run = dry_run

    def watch_once(self, state: Optional[ExecutionState] = None) -> list[str]:
        """
        OPEN の注文を全件チェックし、処理した order_id のリストを返す。
        state が渡された場合、約定反映も行う。
        """
        open_orders = self.pending_store.load_open()
        processed = []

        for pending in open_orders:
            try:
                result = self._check_one(pending, state)
                if result:
                    processed.append(pending.order_id)
            except Exception as e:
                log.error(f"注文チェックエラー order_id={pending.order_id}: {e}")

        return processed

    def _check_one(self, pending, state: Optional[ExecutionState]) -> bool:
        """
        1件の注文をチェックする。状態が変化したら True を返す。
        """
        now = time.time()
        elapsed = now - pending.created_at

        # API から注文状態を取得
        order = self.adapter.get_order(pending.order_id)
        api_status = order.get("status", "OPEN")

        # --- FILLED ---
        if api_status == "FILLED":
            self._handle_filled(pending, order, state)
            return True

        # --- CANCELLED / EXPIRED ---
        if api_status in (STATUS_CANCELLED, STATUS_EXPIRED):
            self.pending_store.update_status(pending.order_id, api_status)
            log.info(f"注文{api_status}: order_id={pending.order_id}")
            # 仮ポジションの巻き戻し
            if state and pending.side == "BUY":
                state.btc_held = max(0.0, state.btc_held - pending.quantity)
                state.balance_jpy += pending.amount_jpy
                log.info(f"仮ポジション巻き戻し: btc_held={state.btc_held:.8f}")
            elif state and pending.side == "SELL":
                state.btc_held += pending.quantity
            return True

        # --- タイムアウト → キャンセル ---
        if elapsed >= self.order_timeout_seconds:
            log.warning(
                f"注文タイムアウト({elapsed:.0f}秒): order_id={pending.order_id} → キャンセル発行"
            )
            cancelled = self.adapter.cancel_order(pending.order_id, pending.symbol)
            new_status = STATUS_CANCELLED if cancelled else STATUS_OPEN
            self.pending_store.update_status(pending.order_id, new_status)
            if cancelled and state and pending.side == "BUY":
                state.btc_held = max(0.0, state.btc_held - pending.quantity)
                state.balance_jpy += pending.amount_jpy
            elif cancelled and state and pending.side == "SELL":
                state.btc_held += pending.quantity
            return cancelled

        # まだ OPEN（タイムアウト前）
        log.debug(f"注文OPEN中: order_id={pending.order_id} 経過{elapsed:.0f}秒")
        return False

    def _handle_filled(self, pending, order: dict, state: Optional[ExecutionState]):
        """約定処理: execution_state 更新 + 永続化。"""
        fill_price = order.get("price") or pending.price
        fill_qty = order.get("executed_quantity") or pending.quantity

        ex = Execution(
            symbol=pending.symbol,
            side=pending.side,
            price=fill_price,
            quantity=fill_qty,
            timestamp=time.time(),
            execution_id=f"fill_{pending.order_id}",
        )

        # pending → FILLED
        self.pending_store.update_status(pending.order_id, STATUS_FILLED)

        # 約定ログ永続化
        self.execution_store.save(ex, is_dry_run=self.dry_run)

        # ExecutionState を更新
        if state:
            # BUY: 仮ポジションで既に btc_held を増やしているので差分調整
            if ex.side == "BUY":
                # 仮ポジション分を一旦引いてから正確な値で適用
                state.btc_held = max(0.0, state.btc_held - pending.quantity)
                state.balance_jpy += pending.amount_jpy
            state.apply_execution(ex)

        log.info(
            f"約定確認: order_id={pending.order_id} "
            f"{ex.symbol} {ex.side} {ex.quantity:.8f}BTC @ ¥{ex.price:,.0f}"
        )
