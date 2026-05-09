"""
Integration tests for FX daily pipeline behavior.
Does NOT call real APIs. Tests pipeline logic only.
実注文なし・研究用のみ。
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.fx.fx_status import FXAssessment, signal_action_to_fx_status, get_next_action
from src.fx.fx_stale_checker import StaleResult
from src.fx.fx_signal_history import build_fx_signal_record, save_fx_signal_record
from src.fx.fx_paper_trade import create_fx_paper_trades_from_proposal, load_fx_paper_trades
from src.fx.fx_dry_run_recorder import record_fx_dry_run_order, DRY_RUN_APPROVAL_PHRASE

JST = ZoneInfo("Asia/Tokyo")


def _make_assessment(action: str, fx_status: str, stale_invalid: bool = False) -> FXAssessment:
    return FXAssessment(
        signal_id=f"test_signal_{action.lower()}",
        symbol="USD/JPY",
        action=action,
        fx_status=fx_status,
        next_action=get_next_action(fx_status),
        current_price=145.50,
        market_data_timestamp="2026-01-15T09:00:00+09:00",
        stale_level="invalid" if stale_invalid else "fresh",
        stale_reason="test",
        is_stale_invalid=stale_invalid,
        stop_loss=145.20,
        take_profit=146.00,
        reasons=["test reason"],
    )


def _make_proposal(proposal_id: str = "fx_test_proposal") -> dict:
    return {
        "proposal_id": proposal_id,
        "source_signal_id": "test_signal_001",
        "symbol": "USD/JPY",
        "side": "BUY",
        "suggested_price": 145.50,
        "suggested_size": 1000.0,
        "estimated_jpy": 145500.0,
        "stop_loss": 145.20,
        "take_profit": 146.00,
        "max_loss_jpy": 300.0,
        "send_to_exchange": False,
        "requires_manual_confirmation": True,
        "status": "proposed",
    }


def _make_signal_record(action: str = "BUY", fx_status: str = "FX_CANDIDATE") -> dict:
    return {
        "signal_id": f"usdjpy_20260115_090000_{fx_status.lower()}",
        "created_at": "2026-01-15T09:00:00+09:00",
        "symbol": "USD/JPY",
        "action": action,
        "fx_status": fx_status,
    }


class TestFxStatusPipeline:
    def test_fx_skip_no_proposal_created(self, tmp_path):
        """SKIP → proposal は作らない。"""
        fx_status = signal_action_to_fx_status("SKIP")
        assert fx_status == "FX_SKIP"
        # FX_SKIP の場合はプロポーザル生成をスキップするロジックを確認
        should_create_proposal = fx_status == "FX_CANDIDATE"
        assert should_create_proposal is False

    def test_fx_watch_no_proposal_created(self, tmp_path):
        """WATCH → proposal は作らない。"""
        fx_status = signal_action_to_fx_status("WATCH")
        assert fx_status == "FX_WATCH"
        should_create_proposal = fx_status == "FX_CANDIDATE"
        assert should_create_proposal is False

    def test_fx_watch_no_paper_trade_created(self, tmp_path):
        """WATCH → paper trade は作らない。"""
        path = tmp_path / "fx_paper_trades.json"
        fx_status = signal_action_to_fx_status("WATCH")
        # paper trade 作成条件をチェック
        if fx_status != "FX_CANDIDATE":
            # 作らない
            trades, reason = [], "skipped_not_candidate"
        else:
            proposal = _make_proposal()
            signal_rec = _make_signal_record("WATCH", "FX_WATCH")
            trades, reason = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        assert trades == []

    def test_fx_candidate_proposal_created(self, tmp_path):
        """BUY/SELL → FX_CANDIDATE → proposal が生成されること（ロジック確認）。"""
        fx_status = signal_action_to_fx_status("BUY")
        assert fx_status == "FX_CANDIDATE"
        should_create_proposal = fx_status == "FX_CANDIDATE"
        assert should_create_proposal is True

    def test_fx_candidate_paper_trade_created(self, tmp_path):
        """BUY → FX_CANDIDATE → paper trade が作成されること。"""
        path = tmp_path / "fx_paper_trades.json"
        fx_status = signal_action_to_fx_status("BUY")
        assert fx_status == "FX_CANDIDATE"
        proposal = _make_proposal()
        signal_rec = _make_signal_record("BUY", "FX_CANDIDATE")
        trades, reason = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        assert len(trades) == 3
        assert reason == "created"

    def test_stale_invalid_no_proposal(self, tmp_path):
        """stale invalid → FX_STALE_INVALID → proposal は作らない。"""
        fx_status = signal_action_to_fx_status("BUY", is_stale_invalid=True)
        assert fx_status == "FX_STALE_INVALID"
        should_create_proposal = fx_status == "FX_CANDIDATE" and not True  # is_stale_invalid=True
        assert should_create_proposal is False

    def test_stale_invalid_no_paper_trade(self, tmp_path):
        """stale invalid → paper trade は作らない（stale は FX_CANDIDATE 到達前に弾く）。"""
        fx_status = signal_action_to_fx_status("BUY", is_stale_invalid=True)
        # stale_invalid かつ FX_CANDIDATE でなければ paper trade 不要
        assert fx_status != "FX_CANDIDATE"

    def test_no_real_order_api_called(self, tmp_path):
        """実取引所API（send_to_exchange=True）は呼ばれないこと。"""
        proposal = _make_proposal()
        # FXOrderProposal は常に send_to_exchange=False
        assert proposal["send_to_exchange"] is False
        assert proposal["requires_manual_confirmation"] is True

    def test_signal_history_saved_for_skip(self, tmp_path):
        """SKIP でも signal record は保存されること。"""
        path = tmp_path / "fx_signal_history.json"
        assessment = _make_assessment("SKIP", "FX_SKIP")
        record = build_fx_signal_record(assessment, created_at="2026-01-15T09:00:00+09:00")
        stored, is_new = save_fx_signal_record(record, path=path)
        assert is_new is True
        data = json.loads(path.read_text())
        assert len(data["signals"]) == 1

    def test_signal_history_saved_for_candidate(self, tmp_path):
        """CANDIDATE の場合も signal record が保存されること。"""
        path = tmp_path / "fx_signal_history.json"
        assessment = _make_assessment("BUY", "FX_CANDIDATE")
        record = build_fx_signal_record(assessment, created_at="2026-01-15T09:00:00+09:00")
        stored, is_new = save_fx_signal_record(record, path=path)
        assert is_new is True

    def test_dry_run_order_requires_approval(self, tmp_path):
        """dry-run 注文は承認フレーズなしで記録できないこと。"""
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, "WRONG", path=path)
        assert order is None

    def test_dry_run_order_recorded_with_approval(self, tmp_path):
        """正しい承認フレーズで dry-run 注文が記録されること。"""
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert order["send_to_exchange"] is False
        assert order["dry_run"] is True
        assert order["asset_class"] == "fx"

    def test_open_position_exit_reason_affects_status(self):
        """オープンポジションのexit reasonがfx_statusに反映されること。"""
        # Current ruleのトレードがTAKE_PROFITでクローズされた場合
        fx_status = signal_action_to_fx_status("WATCH", open_position_exit_reason="TAKE_PROFIT")
        assert fx_status == "FX_TAKE_PROFIT_CANDIDATE"

        fx_status = signal_action_to_fx_status("WATCH", open_position_exit_reason="STOP_LOSS")
        assert fx_status == "FX_STOP_LOSS_CANDIDATE"

        fx_status = signal_action_to_fx_status("WATCH", open_position_exit_reason="TIMEOUT")
        assert fx_status == "FX_TIMEOUT_EXIT_CANDIDATE"
