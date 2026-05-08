"""
risk_manager.py — 注文前の全リスクチェックを束ねる。

check_order_allowed() を呼ぶ前に必ず pre_trade_sync() を実行すること。
チェックは注文ベースではなく約定ベースで行う。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.risk.risk_config import RiskConfig, load_config
from src.risk.kill_switch import KillSwitch
from src.risk.duplicate_order_guard import DuplicateOrderGuard
from src.risk.position_limit import PositionLimitChecker
from src.risk.execution_state import ExecutionState, ExecutionStore, Execution
from src.risk.pending_orders import PendingOrderStore, PendingOrder, STATUS_OPEN
from src.risk.pre_trade_sync import PreTradeSync
from src.risk.order_executor import OrderExecutor
from src.risk.order_watcher import OrderWatcher
from src.utils.logger import get_logger
import time

log = get_logger(__name__)


@dataclass
class OrderCheckResult:
    allowed: bool
    reason: str

    def __str__(self) -> str:
        status = "✅ ALLOWED" if self.allowed else "❌ BLOCKED"
        return f"{status}: {self.reason}"


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None, db_path=None, adapter=None):
        self.config = config or load_config()
        self.kill_switch = KillSwitch(self.config.stop_trading_file)
        self.guard = DuplicateOrderGuard(
            **({"db_path": db_path} if db_path else {}),
            guard_seconds=self.config.duplicate_guard_seconds,
        )
        self.position_checker = PositionLimitChecker(self.config.max_position_value_jpy)
        self.execution_store = ExecutionStore(**({"db_path": db_path} if db_path else {}))
        self.pending_store = PendingOrderStore(**({"db_path": db_path} if db_path else {}))
        # DRY_RUN=true かつ adapter 未指定の場合はモックアダプターを使う
        # read_only=False: DRY_RUN モードでは HTTP 送信しないため READ_ONLY ガード不要
        if adapter is None and self.config.dry_run:
            from src.brokers.gmo_private_adapter import GMOPrivateAdapter
            adapter = GMOPrivateAdapter("", "", dry_run=True, read_only=False)
        self.adapter = adapter
        self.syncer = PreTradeSync(
            execution_store=self.execution_store,
            pending_store=self.pending_store,
            dry_run=self.config.dry_run,
            adapter=adapter,
        )
        self.executor = OrderExecutor(
            adapter=adapter,
            execution_store=self.execution_store,
            pending_store=self.pending_store,
            guard=self.guard,
            dry_run=self.config.dry_run,
        )
        self.watcher = OrderWatcher(
            adapter=adapter,
            execution_store=self.execution_store,
            pending_store=self.pending_store,
            order_timeout_seconds=self.config.order_timeout_seconds,
            dry_run=self.config.dry_run,
        )
        self._state: Optional[ExecutionState] = None

    # ------------------------------------------------------------------
    # Step 1: 注文前の状態同期（必須）
    # ------------------------------------------------------------------

    def pre_trade_sync(self, symbol: str = "BTC_JPY") -> ExecutionState:
        """注文前に必ず呼ぶ。約定ベースの最新状態を返す。"""
        self._state = self.syncer.sync(symbol)
        return self._state

    # ------------------------------------------------------------------
    # Step 2: リスクチェック
    # ------------------------------------------------------------------

    def check_order_allowed(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount_jpy: float,
        current_price_jpy: float = 0.0,
        state: Optional[ExecutionState] = None,
    ) -> OrderCheckResult:
        """
        注文を実行してよいか全チェックを行い結果を返す。
        state は pre_trade_sync() の戻り値を渡す。省略時は直前の同期結果を使う。
        """
        s = state or self._state
        if s is None:
            return OrderCheckResult(False, "pre_trade_sync() が未実行です。注文前に必ず呼んでください。")

        # 1. DRY_RUN確認（チェックは通す、発注だけしない）
        if self.config.dry_run:
            log.info("DRY_RUN=true のため実発注はしません（シミュレーションのみ）")

        # 2. KILL SWITCH
        if self.kill_switch.is_active():
            return OrderCheckResult(False, "KILL SWITCH: STOP_TRADINGファイルが存在します")

        # 3. symbolチェック
        if symbol not in self.config.allowed_symbols:
            return OrderCheckResult(False, f"禁止シンボル: {symbol}（許可: {self.config.allowed_symbols}）")

        # 4. order_typeチェック（成行禁止）
        if order_type.upper() not in [t.upper() for t in self.config.allowed_order_types]:
            return OrderCheckResult(False, f"禁止注文タイプ: {order_type}（許可: {self.config.allowed_order_types}）。成行注文は禁止。")

        # 5. 注文額チェック
        if amount_jpy > self.config.max_order_amount_jpy:
            return OrderCheckResult(False, f"注文額超過: ¥{amount_jpy:,.0f} > 上限 ¥{self.config.max_order_amount_jpy:,.0f}")

        # 6. 本日約定回数チェック（約定ベース）
        today_count = s.daily_execution_count()
        if today_count >= self.config.max_daily_orders:
            return OrderCheckResult(False, f"本日注文回数上限: {today_count}/{self.config.max_daily_orders}回")

        # 7. 本日損失チェック（約定ベース）
        daily_loss = s.daily_loss_jpy(current_price_jpy)
        if daily_loss >= self.config.max_daily_loss_jpy:
            return OrderCheckResult(False, f"本日損失上限: ¥{daily_loss:,.0f} >= 上限 ¥{self.config.max_daily_loss_jpy:,.0f}")

        # 8. ポジション上限チェック
        if current_price_jpy > 0:
            ok, reason = self.position_checker.check(s.btc_held, current_price_jpy)
            if not ok:
                return OrderCheckResult(False, reason)

        # 9. 重複注文チェック
        if self.guard.is_duplicate(symbol, side, order_type, amount_jpy):
            return OrderCheckResult(False, f"重複注文: 直近{self.config.duplicate_guard_seconds}秒以内に同一注文が存在します")

        return OrderCheckResult(True, "全チェック通過")

    # ------------------------------------------------------------------
    # Step 3: 注文発行（DRY_RUN / 実口座 両対応）
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        amount_jpy: float,
    ) -> PendingOrder:
        """
        注文を発行して PendingOrder を返す。
        DRY_RUN=true  : モック発注 → pending_orders に登録
        DRY_RUN=false : GMO Private API に送信 → pending_orders に登録
        """
        if self.executor is None:
            raise RuntimeError("OrderExecutor が未初期化です。adapter を渡してください。")
        return self.executor.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            amount_jpy=amount_jpy,
            state=self._state,
        )

    # ------------------------------------------------------------------
    # Step 4: 約定監視（1回分）
    # ------------------------------------------------------------------

    def watch_orders(self) -> list[str]:
        """
        OPEN の注文を全件チェックし、処理した order_id のリストを返す。
        定期的に呼ぶことで約定を検知してポジションを更新する。
        """
        if self.watcher is None:
            raise RuntimeError("OrderWatcher が未初期化です。adapter を渡してください。")
        return self.watcher.watch_once(state=self._state)

    # ------------------------------------------------------------------
    # 後方互換: DRY_RUN 専用の旧メソッド（simulate_order.py から呼ばれる）
    # ------------------------------------------------------------------

    def submit_dry_run_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        amount_jpy: float,
    ) -> PendingOrder:
        """後方互換メソッド。place_order() に委譲する。"""
        return self.place_order(symbol, side, order_type, price, quantity, amount_jpy)

    def simulate_fill(self, order: PendingOrder, fill_price: float) -> Execution:
        """
        DRY_RUN用の仮約定を処理する。
        OrderWatcher.watch_once() の内部処理を直接呼ぶ形で統一。
        """
        ex = Execution(
            symbol=order.symbol,
            side=order.side,
            price=fill_price,
            quantity=order.quantity,
            timestamp=time.time(),
            execution_id=f"fill_{order.order_id}",
        )
        self.pending_store.update_status(order.order_id, "FILLED")
        self.execution_store.save(ex, is_dry_run=True)
        if self._state:
            # place_order で仮ポジション(BUY分)を先行計上済みのため巻き戻してから適用
            if ex.side == "BUY":
                self._state.btc_held = max(0.0, self._state.btc_held - order.quantity)
                self._state.balance_jpy += order.amount_jpy
            self._state.apply_execution(ex)
        log.info(f"仮約定完了: {ex.symbol} {ex.side} {ex.quantity:.8f}BTC @ ¥{ex.price:,.0f}")
        return ex
