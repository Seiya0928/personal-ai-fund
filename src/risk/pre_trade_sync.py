"""
pre_trade_sync.py — 注文前の状態同期。

注文前に必ず呼ぶ。
DRY_RUN=true  : DBから本日の仮約定を読み込んで状態を復元する
DRY_RUN=false : GMO Private API から残高・ポジション・本日約定を取得して上書き
"""
from __future__ import annotations

import time
from typing import Optional

from src.risk.execution_state import ExecutionState, ExecutionStore, Execution
from src.risk.pending_orders import PendingOrderStore
from src.utils.logger import get_logger

log = get_logger(__name__)


class PreTradeSync:
    def __init__(
        self,
        execution_store: ExecutionStore,
        pending_store: PendingOrderStore,
        dry_run: bool = True,
        adapter=None,  # GMOPrivateAdapter | None
    ):
        self.execution_store = execution_store
        self.pending_store = pending_store
        self.dry_run = dry_run
        self.adapter = adapter  # DRY_RUN=false のときに必須

    def sync(self, symbol: str = "BTC_JPY") -> ExecutionState:
        """
        注文前に呼ぶ同期処理。ExecutionState を返す。
        DRY_RUN=true  → _sync_from_db()（モック）
        DRY_RUN=false → _sync_from_api()（実口座）
        """
        if self.dry_run:
            return self._sync_from_db(symbol)
        else:
            return self._sync_from_api(symbol)

    # ------------------------------------------------------------------
    # DRY_RUN モード: DB から状態復元
    # ------------------------------------------------------------------

    def _sync_from_db(self, symbol: str) -> ExecutionState:
        """DBに保存済みの本日約定から状態を復元する（モック用）。"""
        state = ExecutionState()
        executions = self.execution_store.load_today(symbol)
        for ex in executions:
            state.apply_execution(ex)
        state.last_synced_at = time.time()
        log.info(
            f"[DRY_RUN] 状態同期完了: "
            f"本日約定={state.daily_execution_count()}回 "
            f"保有BTC={state.btc_held:.8f} "
            f"平均取得単価=¥{state.avg_entry_price:,.0f}"
        )
        return state

    # ------------------------------------------------------------------
    # 実口座モード: Private API から状態上書き
    # ------------------------------------------------------------------

    def _sync_from_api(self, symbol: str) -> ExecutionState:
        """
        GMO Private API から残高・ポジション・本日約定を取得して ExecutionState を構築する。
        ローカルDBの状態ではなく API の値で必ず上書きする（不整合防止）。
        """
        if self.adapter is None:
            raise RuntimeError(
                "DRY_RUN=false で動作するには GMOPrivateAdapter を渡してください。"
            )

        # 1. 残高取得（円・BTC）
        balance = self.adapter.get_balance()

        # 2. ポジション取得（現物はbalanceのBTC量と同じ）
        position = self.adapter.get_positions(symbol)

        # 3. 本日約定履歴取得
        raw_executions = self.adapter.get_executions_today(symbol)

        # 4. ExecutionState を API の値で構築（ローカル値は使わない）
        state = ExecutionState(
            balance_jpy=balance["jpy"],
            btc_held=position["btc_held"],
            avg_entry_price=position.get("avg_price", 0.0),
        )

        # 5. 本日約定をリプレイして損益・約定回数を復元
        #    （avg_entry_price は API 値を優先するため apply_execution ではなく直接追加）
        for raw_ex in raw_executions:
            ex = Execution(
                symbol=raw_ex["symbol"],
                side=raw_ex["side"],
                price=raw_ex["price"],
                quantity=raw_ex["quantity"],
                timestamp=_parse_timestamp(raw_ex["timestamp"]),
                execution_id=raw_ex["execution_id"],
            )
            state.executions_today.append(ex)

        state.last_synced_at = time.time()
        log.info(
            f"[API] 状態同期完了: "
            f"JPY=¥{state.balance_jpy:,.0f} "
            f"BTC={state.btc_held:.8f} "
            f"本日約定={state.daily_execution_count()}回"
        )

        # 6. 未約定注文（OPEN）の pending をログ出力（参考情報）
        open_orders = self.pending_store.load_open(symbol)
        if open_orders:
            log.info(f"未約定注文: {len(open_orders)}件（API同期後も pending_orders に残存）")

        return state


def _parse_timestamp(ts_str: str) -> float:
    """GMO の ISO8601 タイムスタンプを unix time に変換する。失敗したら現在時刻を返す。"""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return time.time()
