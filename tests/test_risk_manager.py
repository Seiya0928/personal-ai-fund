import pytest
import time
from pathlib import Path
from src.risk.risk_config import RiskConfig
from src.risk.risk_manager import RiskManager
from src.risk.execution_state import ExecutionState, Execution


def make_rm(tmp_path: Path, **overrides) -> RiskManager:
    """テスト用RiskManagerを生成。全DBはtmp_pathに向ける。"""
    cfg = RiskConfig(
        dry_run=True,
        stop_trading_file=tmp_path / "STOP_TRADING",
        duplicate_guard_seconds=60,
        max_order_amount_jpy=1_000.0,
        max_daily_orders=1,
        max_daily_loss_jpy=300.0,
        max_position_value_jpy=3_000.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    db = tmp_path / "test.db"
    rm = RiskManager(config=cfg, db_path=db)
    return rm


def fresh_state() -> ExecutionState:
    return ExecutionState()


BASE = dict(symbol="BTC_JPY", side="BUY", order_type="LIMIT", amount_jpy=1_000.0)


def test_normal_order_allowed(tmp_path):
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state)
    assert result.allowed, result.reason


def test_sync_required(tmp_path):
    """pre_trade_sync() なしで check_order_allowed() を呼ぶとブロック"""
    rm = make_rm(tmp_path)
    result = rm.check_order_allowed(**BASE)
    assert not result.allowed
    assert "pre_trade_sync" in result.reason


def test_kill_switch_blocks(tmp_path):
    rm = make_rm(tmp_path)
    rm.kill_switch.activate("テスト停止")
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**BASE, state=state)
    assert not result.allowed
    assert "KILL SWITCH" in result.reason


def test_amount_over_blocks(tmp_path):
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**{**BASE, "amount_jpy": 1_001.0}, state=state)
    assert not result.allowed
    assert "注文額超過" in result.reason


def test_market_order_blocks(tmp_path):
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**{**BASE, "order_type": "MARKET"}, state=state)
    assert not result.allowed
    assert "禁止注文タイプ" in result.reason


def test_wrong_symbol_blocks(tmp_path):
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    result = rm.check_order_allowed(**{**BASE, "symbol": "ETH_JPY"}, state=state)
    assert not result.allowed
    assert "禁止シンボル" in result.reason


def test_daily_execution_limit_blocks(tmp_path):
    """約定が1回記録された後は2回目をブロック"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    r1 = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state)
    assert r1.allowed

    # 仮注文→仮約定で状態を進める
    order = rm.submit_dry_run_order("BTC_JPY", "BUY", "LIMIT", 12_000_000.0, 1_000.0 / 12_000_000.0, 1_000.0)
    rm.simulate_fill(order, fill_price=12_000_000.0)

    # 再同期して2回目チェック
    state2 = rm.pre_trade_sync("BTC_JPY")
    r2 = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state2)
    assert not r2.allowed
    assert "注文回数上限" in r2.reason


def test_duplicate_order_blocks(tmp_path):
    """同一内容を連続で送るとブロック（max_daily_ordersは緩める）"""
    rm = make_rm(tmp_path, max_daily_orders=99)
    state = rm.pre_trade_sync("BTC_JPY")
    r1 = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state)
    assert r1.allowed

    order = rm.submit_dry_run_order("BTC_JPY", "BUY", "LIMIT", 12_000_000.0, 1_000.0 / 12_000_000.0, 1_000.0)
    rm.simulate_fill(order, fill_price=12_000_000.0)

    state2 = rm.pre_trade_sync("BTC_JPY")
    r2 = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state2)
    assert not r2.allowed
    assert "重複注文" in r2.reason


def test_dry_run_flag_still_checks(tmp_path):
    """DRY_RUN=false でも安全装置は全て有効（Private API未実装のためstateを直接渡す）"""
    rm = make_rm(tmp_path, dry_run=False)
    state = fresh_state()  # モックstate
    result = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state)
    assert result.allowed


def test_daily_loss_limit_blocks(tmp_path):
    """本日損失がSELL約定から計算されブロックされる"""
    rm = make_rm(tmp_path, max_daily_orders=99)
    state = rm.pre_trade_sync("BTC_JPY")

    # BUY約定で平均取得単価を設定（apply_executionが avg_entry_price を更新する）
    buy_ex = Execution("BTC_JPY", "BUY", price=12_000_000.0, quantity=0.001, timestamp=time.time())
    state.apply_execution(buy_ex)

    # 大幅安値でSELL → apply_execution内で avg_entry_price_at_trade が記録され損失計算に使われる
    sell_ex = Execution("BTC_JPY", "SELL", price=10_000_000.0, quantity=0.001, timestamp=time.time())
    state.apply_execution(sell_ex)

    # 損失: (10_000_000 - 12_000_000) * 0.001 = -2_000円 → 上限¥300を超える
    assert state.daily_loss_jpy() >= 300.0

    result = rm.check_order_allowed(**BASE, current_price_jpy=10_000_000.0, state=state)
    assert not result.allowed
    assert "損失上限" in result.reason


def test_position_limit_blocks(tmp_path):
    """BTC保有量 × 現在価格が上限を超えるとブロック"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    state.btc_held = 1.0  # 1BTC保有
    result = rm.check_order_allowed(**BASE, current_price_jpy=12_000_000.0, state=state)
    assert not result.allowed
    assert "ポジション上限超過" in result.reason


def test_simulate_fill_updates_state(tmp_path):
    """仮約定後にbtc_held・avg_entry_priceが正しく更新される"""
    rm = make_rm(tmp_path)
    state = rm.pre_trade_sync("BTC_JPY")
    price = 12_000_000.0
    qty = AMOUNT_JPY = 1_000.0 / price

    order = rm.submit_dry_run_order("BTC_JPY", "BUY", "LIMIT", price, qty, 1_000.0)
    ex = rm.simulate_fill(order, fill_price=price)

    s = rm._state
    assert abs(s.btc_held - qty) < 1e-10
    assert abs(s.avg_entry_price - price) < 1.0
    assert s.daily_execution_count() == 1
