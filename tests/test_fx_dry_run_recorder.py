"""Tests for src/fx/fx_dry_run_recorder.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from src.fx.fx_dry_run_recorder import (
    record_fx_dry_run_order,
    load_fx_dry_run_orders,
    DRY_RUN_APPROVAL_PHRASE,
)


def _make_proposal(**kwargs) -> dict:
    defaults = {
        "proposal_id": "fx_test_signal_buy_proposal",
        "source_signal_id": "test_signal_001",
        "symbol": "USD/JPY",
        "side": "BUY",
        "suggested_price": 145.50,
        "suggested_size": 1000.0,
        "stop_loss": 145.20,
        "take_profit": 146.00,
        "max_loss_jpy": 300.0,
        "send_to_exchange": False,
        "requires_manual_confirmation": True,
    }
    defaults.update(kwargs)
    return defaults


class TestRecordFxDryRunOrder:
    def test_correct_approval_records(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert reason == "dry-run注文記録済み"
        data = json.loads(path.read_text())
        assert len(data["orders"]) == 1

    def test_wrong_approval_rejected(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, "WRONG PHRASE", path=path)
        assert order is None
        assert "承認フレーズ不一致" in reason

    def test_empty_approval_rejected(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, "", path=path)
        assert order is None
        assert "承認フレーズ不一致" in reason

    def test_stop_trading_blocks(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        stop_file = tmp_path / "STOP_TRADING"
        stop_file.touch()
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(
            proposal, DRY_RUN_APPROVAL_PHRASE,
            stop_trading_path=stop_file,
            path=path,
        )
        assert order is None
        assert "STOP_TRADING" in reason

    def test_duplicate_skipped(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order1, _ = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        order2, reason2 = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order2 is not None  # returns existing
        assert "重複スキップ" in reason2
        data = json.loads(path.read_text())
        assert len(data["orders"]) == 1  # still 1

    def test_send_to_exchange_true_blocked(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal(send_to_exchange=True)
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is None
        assert "send_to_exchange=true" in reason

    def test_no_manual_confirmation_blocked(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal(requires_manual_confirmation=False)
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is None
        assert "requires_manual_confirmation=false" in reason

    def test_dry_run_false_blocked(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, dry_run=False, path=path)
        assert order is None
        assert "DRY_RUN=false" in reason

    def test_read_only_false_blocked(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, reason = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, read_only=False, path=path)
        assert order is None
        assert "READ_ONLY=false" in reason

    def test_recorded_order_has_asset_class_fx(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, _ = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert order["asset_class"] == "fx"

    def test_recorded_order_send_to_exchange_false(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, _ = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert order["send_to_exchange"] is False

    def test_recorded_order_dry_run_true(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, _ = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert order["dry_run"] is True

    def test_recorded_order_fields_correct(self, tmp_path):
        path = tmp_path / "fx_dry_run_orders.json"
        proposal = _make_proposal()
        order, _ = record_fx_dry_run_order(proposal, DRY_RUN_APPROVAL_PHRASE, path=path)
        assert order is not None
        assert order["symbol"] == "USD/JPY"
        assert order["side"] == "BUY"
        assert order["stop_loss"] == 145.20
        assert order["take_profit"] == 146.00
        assert order["source_proposal_id"] == proposal["proposal_id"]
        assert order["status"] == "dry_run_recorded"
        assert "recorded_at" in order
