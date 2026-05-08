"""
注文フロー統合テスト。
pre_trade_sync → check_order_allowed → place_order → watch_orders の流れを検証。
"""
import time
import pytest
from pathlib import Path
from src.risk.risk_config import RiskConfig
from src.risk.risk_manager import RiskManager
from src.risk.execution_state import Execution
from src.brokers.gmo_private_adapter import GMOPrivateAdapter

BASE = dict(symbol="BTC_JPY", side="BUY", order_type="LIMIT", amount_jpy=1_000.0)
PRICE = 12_000_000.0
QTY = 1_000.0 / PRICE


def make_rm(tmp_path: Path, **overrides) -> RiskManager:
    cfg = RiskConfig(
        dry_run=True,
        stop_trading_file=tmp_path / "STOP_TRADING",
        duplicate_guard_seconds=60,
        max_order_amount_jpy=1_000.0,
        max_daily_orders=2,  # テスト用に緩める
        max_daily_loss_jpy=300.0,
        max_position_value_jpy=3_000.0,
        order_timeout_seconds=1,   # タイムアウトを短くしてテスト
        polling_interval_seconds=1,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(config=cfg, db_path=tmp_path / "test.db")


# ------------------------------------------------------------------
# adapter 正規化テスト
# ------------------------------------------------------------------

def test_normalize_balance():
    raw = {"status": 0, "data": [
        {"symbol": "JPY", "amount": "500000", "available": "480000"},
        {"symbol": "BTC", "amount": "0.001",  "available": "0.001"},
    ]}
    from src.brokers.gmo_private_adapter import _normalize_balance
    result = _normalize_balance(raw)
    assert result["jpy"] == 500_000.0
    assert result["btc"] == 0.001
    assert result["btc_available"] == 0.001


def test_normalize_order_status_mapping():
    from src.brokers.gmo_private_adapter import _normalize_order
    for raw_status, expected in [
        ("ORDERED", "OPEN"),
        ("EXECUTED", "FILLED"),
        ("CANCELED", "CANCELLED"),
        ("EXPIRED", "EXPIRED"),
    ]:
        result = _normalize_order({"orderId": "1", "status": raw_status, "symbol": "BTC_JPY",
                                   "side": "BUY", "executionType": "LIMIT", "price": "5000000",
                                   "size": "0.001", "executedSize": "0.001", "timestamp": ""})
        assert result["status"] == expected, f"{raw_status} should map to {expected}"


# ------------------------------------------------------------------
# DRY_RUN モック発注フロー
# ------------------------------------------------------------------

def test_place_order_dry_run(tmp_path):
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**BASE, current_price_jpy=PRICE, state=state)
    assert result.allowed

    pending = rm.place_order("BTC_JPY", "BUY", "LIMIT", PRICE, QTY, 1_000.0)
    assert pending.order_id.startswith("dry_")
    assert pending.status == "OPEN"

    # 仮ポジション反映確認
    assert rm._state.btc_held > 0


def test_watch_orders_fills(tmp_path):
    """DRY_RUN では adapter.get_order() が FILLED を返すので watch_once で約定処理される"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    pending = rm.place_order("BTC_JPY", "BUY", "LIMIT", PRICE, QTY, 1_000.0)

    processed = rm.watch_orders()
    assert pending.order_id in processed

    # 約定後ステータス確認
    updated = rm.pending_store.load_by_id(pending.order_id)
    assert updated.status == "FILLED"


def test_watch_orders_timeout_cancel(tmp_path):
    """タイムアウト後にキャンセルされる（DRY_RUN モックはキャンセルを即成功させる）"""
    rm = make_rm(tmp_path, order_timeout_seconds=0)  # 即タイムアウト

    # adapter の get_order が OPEN を返すようにモック
    class StuckAdapter(GMOPrivateAdapter):
        def get_order(self, order_id):
            return {"order_id": order_id, "status": "OPEN", "price": PRICE,
                    "executed_quantity": 0.0, "quantity": QTY}

    rm.adapter = StuckAdapter("", "", dry_run=True, read_only=False)
    rm.watcher.adapter = rm.adapter
    rm.executor.adapter = rm.adapter

    state = rm.pre_trade_sync("BTC_JPY")
    pending = rm.place_order("BTC_JPY", "BUY", "LIMIT", PRICE, QTY, 1_000.0)

    processed = rm.watch_orders()
    assert pending.order_id in processed

    updated = rm.pending_store.load_by_id(pending.order_id)
    assert updated.status == "CANCELLED"


# ------------------------------------------------------------------
# pre_trade_sync API モード（NotImplementedError ではないことを確認）
# ------------------------------------------------------------------

def test_pre_trade_sync_dry_run(tmp_path):
    """DRY_RUN=true の sync は DB から状態を返す"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    assert state is not None
    assert state.btc_held == 0.0


def test_pre_trade_sync_api_raises_without_adapter(tmp_path):
    """DRY_RUN=false かつ adapter=None は RuntimeError"""
    from src.risk.pre_trade_sync import PreTradeSync
    from src.risk.execution_state import ExecutionStore
    from src.risk.pending_orders import PendingOrderStore
    syncer = PreTradeSync(
        execution_store=ExecutionStore(db_path=tmp_path / "t.db"),
        pending_store=PendingOrderStore(db_path=tmp_path / "t.db"),
        dry_run=False,
        adapter=None,
    )
    with pytest.raises(RuntimeError, match="GMOPrivateAdapter"):
        syncer.sync("BTC_JPY")


# ------------------------------------------------------------------
# simulate_fill 後方互換テスト
# ------------------------------------------------------------------

def test_simulate_fill_backward_compat(tmp_path):
    """旧 simulate_fill も引き続き動作する"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    order = rm.submit_dry_run_order("BTC_JPY", "BUY", "LIMIT", PRICE, QTY, 1_000.0)
    ex = rm.simulate_fill(order, fill_price=PRICE)

    assert abs(rm._state.btc_held - QTY) < 1e-10
    assert rm._state.daily_execution_count() == 1
