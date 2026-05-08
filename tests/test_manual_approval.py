"""
test_manual_approval.py — 手動承認ゲートのテスト。

テスト対象:
  - 承認フレーズが違うと place_order は呼ばれない
  - 非対話環境では place_order は呼ばれない
  - DRY_RUN=true では manual_approval は不要
  - DRY_RUN=false READ_ONLY=false では manual_approval が必須
  - 承認フレーズはログに残らない
  - 正しいフレーズを入力すると place_order が呼ばれる
"""
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.risk.manual_approval import require_manual_approval, OrderPlan, _APPROVAL_PHRASE
from src.risk.order_executor import OrderExecutor, ManualApprovalDeniedError
from src.risk.execution_state import ExecutionStore, ExecutionState
from src.risk.pending_orders import PendingOrderStore
from src.risk.duplicate_order_guard import DuplicateOrderGuard
from src.brokers.gmo_private_adapter import GMOPrivateAdapter


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_executor(tmp_path: Path, dry_run: bool, read_only: bool) -> OrderExecutor:
    adapter = GMOPrivateAdapter("key", "secret", dry_run=dry_run, read_only=read_only)
    return OrderExecutor(
        adapter=adapter,
        execution_store=ExecutionStore(db_path=tmp_path / "t.db"),
        pending_store=PendingOrderStore(db_path=tmp_path / "t.db"),
        guard=DuplicateOrderGuard(db_path=tmp_path / "t.db"),
        dry_run=dry_run,
    )


PLAN = OrderPlan(
    symbol="BTC_JPY",
    side="BUY",
    order_type="LIMIT",
    price=10_000_000.0,
    quantity=0.0001,
    amount_jpy=1_000.0,
)


# ---------------------------------------------------------------------------
# require_manual_approval 単体テスト
# ---------------------------------------------------------------------------

class TestRequireManualApproval:
    def test_correct_phrase_returns_true(self):
        """正しい承認フレーズを入力すると True を返す。"""
        with patch("src.risk.manual_approval._is_interactive", return_value=True), \
             patch("src.risk.manual_approval.input", return_value=_APPROVAL_PHRASE):
            assert require_manual_approval(PLAN) is True

    def test_wrong_phrase_returns_false(self):
        """間違ったフレーズは False を返す。"""
        with patch("src.risk.manual_approval._is_interactive", return_value=True), \
             patch("src.risk.manual_approval.input", return_value="wrong phrase"):
            assert require_manual_approval(PLAN) is False

    def test_empty_input_returns_false(self):
        """空入力は False を返す。"""
        with patch("src.risk.manual_approval._is_interactive", return_value=True), \
             patch("src.risk.manual_approval.input", return_value=""):
            assert require_manual_approval(PLAN) is False

    def test_non_interactive_returns_false(self):
        """非対話環境は False を返す（input を呼ばない）。"""
        with patch("src.risk.manual_approval._is_interactive", return_value=False):
            result = require_manual_approval(PLAN)
        assert result is False

    def test_phrase_not_in_logs_on_approval(self, caplog):
        """承認フレーズがログに出力されないこと。"""
        with patch("src.risk.manual_approval._is_interactive", return_value=True), \
             patch("src.risk.manual_approval.input", return_value=_APPROVAL_PHRASE), \
             caplog.at_level(logging.DEBUG):
            require_manual_approval(PLAN)

        full_log = "\n".join(caplog.messages)
        assert _APPROVAL_PHRASE not in full_log, \
            f"承認フレーズがログに露出しています: {full_log}"

    def test_phrase_not_in_logs_on_rejection(self, caplog):
        """拒否時も承認フレーズはログに出力されない。"""
        wrong = "wrong answer here"
        with patch("src.risk.manual_approval._is_interactive", return_value=True), \
             patch("src.risk.manual_approval.input", return_value=wrong), \
             caplog.at_level(logging.DEBUG):
            require_manual_approval(PLAN)

        full_log = "\n".join(caplog.messages)
        assert wrong not in full_log, f"入力内容がログに露出しています"
        assert _APPROVAL_PHRASE not in full_log


# ---------------------------------------------------------------------------
# OrderExecutor 統合テスト
# ---------------------------------------------------------------------------

class TestOrderExecutorApproval:
    def test_dry_run_does_not_require_approval(self, tmp_path):
        """DRY_RUN=true では承認関数を呼ばない。"""
        executor = _make_executor(tmp_path, dry_run=True, read_only=False)
        approval_called = []
        executor._approval_fn = lambda plan: approval_called.append(True) or True

        executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

        assert approval_called == [], "DRY_RUN=true で承認関数が呼ばれました"

    def test_live_mode_requires_approval(self, tmp_path):
        """DRY_RUN=false READ_ONLY=false では承認関数を必ず呼ぶ。"""
        executor = _make_executor(tmp_path, dry_run=False, read_only=False)
        approval_called = []

        def mock_approval(plan):
            approval_called.append(plan)
            return True  # 承認する

        executor._approval_fn = mock_approval

        # adapter.place_order も差し替え（HTTP送信しない）
        mock_resp = {
            "order_id": "live_001",
            "symbol": "BTC_JPY",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 10_000_000.0,
            "quantity": 0.0001,
            "executed_quantity": 0.0,
            "status": "OPEN",
            "timestamp": "",
        }
        executor.adapter.place_order = lambda **kwargs: mock_resp

        executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

        assert len(approval_called) == 1, "承認関数が呼ばれませんでした"
        assert approval_called[0].symbol == "BTC_JPY"

    def test_wrong_phrase_raises_error(self, tmp_path):
        """承認拒否なら ManualApprovalDeniedError が送出され place_order は呼ばれない。"""
        executor = _make_executor(tmp_path, dry_run=False, read_only=False)
        executor._approval_fn = lambda plan: False  # 常に拒否

        place_order_called = []
        original = executor.adapter.place_order

        def track_place_order(**kwargs):
            place_order_called.append(True)
            return original(**kwargs)

        executor.adapter.place_order = track_place_order

        with pytest.raises(ManualApprovalDeniedError):
            executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

        assert place_order_called == [], "拒否されたのに place_order が呼ばれました"

    def test_non_interactive_blocks_live_order(self, tmp_path):
        """非対話環境では live モードの発注がブロックされる。"""
        executor = _make_executor(tmp_path, dry_run=False, read_only=False)

        with patch("src.risk.manual_approval._is_interactive", return_value=False):
            with pytest.raises(ManualApprovalDeniedError):
                executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

    def test_read_only_true_does_not_require_approval(self, tmp_path):
        """READ_ONLY=true（発注禁止）では承認関数は呼ばれない（_guard_write が先に止める）。"""
        executor = _make_executor(tmp_path, dry_run=False, read_only=True)
        approval_called = []
        executor._approval_fn = lambda plan: approval_called.append(True) or True

        from src.brokers.gmo_private_adapter import ReadOnlyViolationError
        with pytest.raises(ReadOnlyViolationError):
            executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

        # 承認関数は呼ばれていない（READ_ONLY の時点でブロックされる）
        assert approval_called == []

    def test_approval_result_in_logs_not_phrase(self, tmp_path, caplog):
        """ログに承認結果（承認/拒否）は記録されるが、フレーズは記録されない。"""
        executor = _make_executor(tmp_path, dry_run=False, read_only=False)
        executor._approval_fn = lambda plan: True

        mock_resp = {
            "order_id": "live_002",
            "symbol": "BTC_JPY",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 10_000_000.0,
            "quantity": 0.0001,
            "executed_quantity": 0.0,
            "status": "OPEN",
            "timestamp": "",
        }
        executor.adapter.place_order = lambda **kwargs: mock_resp

        with caplog.at_level(logging.DEBUG):
            executor.place_order("BTC_JPY", "BUY", "LIMIT", 10_000_000.0, 0.0001, 1_000.0)

        full_log = "\n".join(caplog.messages)
        assert _APPROVAL_PHRASE not in full_log
        assert "承認" in full_log  # 承認された事実はログに残る
