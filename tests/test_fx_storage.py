# 実注文なし・研究用ストレージのテスト

from __future__ import annotations

import pytest
from pathlib import Path

from src.fx.models import FXSignal
from src.fx.storage import FXSignalStorage


def _make_signal(
    signal_id: str = "usdjpy_20250101_120000_watch",
    action: str = "WATCH",
    price: float = 145.0,
) -> FXSignal:
    """テスト用シグナルを生成する"""
    return FXSignal(
        signal_id=signal_id,
        symbol="USD/JPY",
        action=action,
        price=price,
        ask=price + 0.001,
        bid=price - 0.001,
        spread_pips=0.2,
        timestamp="2025-01-01T12:00:00+09:00",
        reasons=[f"RSI=50.0 (中立域)", f"spread=0.2pips"],
        stop_loss=None,
        take_profit=None,
        skip_reason=None,
    )


@pytest.fixture()
def storage(tmp_path: Path) -> FXSignalStorage:
    """テスト用の一時DBを使うストレージを返す"""
    db_path = tmp_path / "test_fund.db"
    return FXSignalStorage(db_path=db_path)


class TestSaveAndLoad:
    def test_save_and_load(self, storage: FXSignalStorage):
        """シグナルを保存して読み込める"""
        sig = _make_signal()
        result = storage.save(sig)
        assert result is True

        loaded = storage.get_latest(n=1)
        assert len(loaded) == 1
        assert loaded[0].signal_id == sig.signal_id
        assert loaded[0].action == sig.action
        assert loaded[0].price == sig.price

    def test_save_returns_true_on_success(self, storage: FXSignalStorage):
        sig = _make_signal(signal_id="usdjpy_test_001")
        assert storage.save(sig) is True

    def test_loaded_signal_has_reasons(self, storage: FXSignalStorage):
        sig = _make_signal()
        storage.save(sig)
        loaded = storage.get_latest(n=1)
        assert len(loaded[0].reasons) > 0


class TestDuplicateSkip:
    def test_duplicate_skip(self, storage: FXSignalStorage):
        """同じ signal_id は2回保存されない（2回目はFalseを返す）"""
        sig = _make_signal()
        first = storage.save(sig)
        second = storage.save(sig)
        assert first is True
        assert second is False

    def test_duplicate_does_not_create_extra_row(self, storage: FXSignalStorage):
        """重複保存しても件数が増えない"""
        sig = _make_signal()
        storage.save(sig)
        storage.save(sig)  # 重複
        signals = storage.list_signals()
        assert len(signals) == 1


class TestListSignals:
    def test_list_signals(self, storage: FXSignalStorage):
        """複数保存して list_signals() で取得できる"""
        sigs = [
            _make_signal(signal_id=f"usdjpy_2025010{i}_watch", action="WATCH")
            for i in range(3)
        ]
        for s in sigs:
            storage.save(s)

        listed = storage.list_signals()
        assert len(listed) == 3

    def test_list_signals_respects_limit(self, storage: FXSignalStorage):
        """limit パラメータが機能する"""
        for i in range(10):
            storage.save(_make_signal(signal_id=f"usdjpy_test_{i:03d}"))
        listed = storage.list_signals(limit=5)
        assert len(listed) == 5

    def test_list_signals_empty(self, storage: FXSignalStorage):
        """データがない場合は空リスト"""
        assert storage.list_signals() == []

    def test_get_latest_returns_n(self, storage: FXSignalStorage):
        """get_latest(n) が n 件を返す"""
        for i in range(5):
            storage.save(_make_signal(signal_id=f"usdjpy_latest_{i:03d}"))
        latest = storage.get_latest(n=3)
        assert len(latest) == 3


class TestActionFilter:
    def test_action_filter_buy(self, storage: FXSignalStorage):
        """action_filter='BUY' で絞り込める"""
        storage.save(_make_signal("usdjpy_buy_001", action="BUY", price=142.0))
        storage.save(_make_signal("usdjpy_sell_001", action="SELL", price=148.0))
        storage.save(_make_signal("usdjpy_watch_001", action="WATCH", price=145.0))
        storage.save(_make_signal("usdjpy_buy_002", action="BUY", price=141.0))

        buys = storage.list_signals(action_filter="BUY")
        assert len(buys) == 2
        assert all(s.action == "BUY" for s in buys)

    def test_action_filter_sell(self, storage: FXSignalStorage):
        """action_filter='SELL' で絞り込める"""
        storage.save(_make_signal("usdjpy_buy_001", action="BUY"))
        storage.save(_make_signal("usdjpy_sell_001", action="SELL"))
        sells = storage.list_signals(action_filter="SELL")
        assert len(sells) == 1
        assert sells[0].action == "SELL"

    def test_action_filter_skip(self, storage: FXSignalStorage):
        """action_filter='SKIP' で絞り込める"""
        storage.save(_make_signal("usdjpy_skip_001", action="SKIP"))
        storage.save(_make_signal("usdjpy_watch_001", action="WATCH"))
        skips = storage.list_signals(action_filter="SKIP")
        assert len(skips) == 1

    def test_action_filter_no_match(self, storage: FXSignalStorage):
        """マッチしない action_filter は空リスト"""
        storage.save(_make_signal("usdjpy_watch_001", action="WATCH"))
        result = storage.list_signals(action_filter="BUY")
        assert result == []

    def test_no_filter_returns_all(self, storage: FXSignalStorage):
        """フィルタなしは全件返す"""
        for action in ("BUY", "SELL", "WATCH", "SKIP"):
            storage.save(_make_signal(f"usdjpy_{action.lower()}_001", action=action))
        all_signals = storage.list_signals()
        assert len(all_signals) == 4
