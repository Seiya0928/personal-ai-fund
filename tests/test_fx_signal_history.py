"""Tests for src/fx/fx_signal_history.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from src.fx.fx_status import FXAssessment
from src.fx.fx_signal_history import (
    build_fx_signal_record,
    load_fx_signal_history,
    save_fx_signal_record,
    list_fx_signal_history,
)


def _make_assessment(**kwargs) -> FXAssessment:
    defaults = dict(
        signal_id="test_signal_001",
        symbol="USD/JPY",
        action="BUY",
        fx_status="FX_CANDIDATE",
        next_action="order proposalを確認",
        current_price=145.50,
        market_data_timestamp="2026-01-15T09:00:00+09:00",
        stale_level="fresh",
        stale_reason="データが新鮮（1.0h）",
        is_stale_invalid=False,
        stop_loss=145.20,
        take_profit=146.00,
        reasons=["RSI low", "price drop"],
        skip_reason=None,
    )
    defaults.update(kwargs)
    return FXAssessment(**defaults)


class TestBuildFxSignalRecord:
    def test_signal_id_format(self):
        """signal_id = usdjpy_{ts}_{fx_status.lower()}"""
        a = _make_assessment(
            market_data_timestamp="2026-01-15T09:00:00+09:00",
            fx_status="FX_CANDIDATE",
        )
        record = build_fx_signal_record(a, created_at="2026-01-15T09:00:00+09:00")
        assert record["signal_id"].startswith("usdjpy_")
        assert record["signal_id"].endswith("_fx_candidate")
        # ts key format: YYYYMMDD_HHMMSS
        parts = record["signal_id"].split("_")
        assert len(parts) >= 4  # usdjpy + date + time + fx_candidate

    def test_all_fields_present(self):
        a = _make_assessment()
        record = build_fx_signal_record(a, created_at="2026-01-15T09:00:00+09:00")
        required_fields = [
            "signal_id", "created_at", "symbol", "action", "fx_status",
            "next_action", "current_price", "market_data_timestamp",
            "stale_level", "stale_reason", "stop_loss", "take_profit",
            "reasons", "skip_reason", "order_proposal_id", "paper_trade_ids",
        ]
        for field in required_fields:
            assert field in record, f"Missing field: {field}"

    def test_reasons_is_copy(self):
        """reasons は参照コピーではなく独立したリストであること。"""
        a = _make_assessment(reasons=["r1", "r2"])
        record = build_fx_signal_record(a)
        record["reasons"].append("extra")
        assert "extra" not in a.reasons

    def test_created_at_fallback_to_market_ts(self):
        """created_at を指定しない場合は market_data_timestamp が使われること。"""
        a = _make_assessment(market_data_timestamp="2026-02-01T06:00:00+09:00")
        record = build_fx_signal_record(a)
        assert record["created_at"] == "2026-02-01T06:00:00+09:00"


class TestSaveFxSignalRecord:
    def test_saves_new_record(self, tmp_path):
        path = tmp_path / "fx_signal_history.json"
        a = _make_assessment()
        record = build_fx_signal_record(a, created_at="2026-01-15T09:00:00+09:00")
        stored, is_new = save_fx_signal_record(record, path=path)
        assert is_new is True
        assert stored["signal_id"] == record["signal_id"]
        data = json.loads(path.read_text())
        assert len(data["signals"]) == 1

    def test_duplicate_skipped(self, tmp_path):
        path = tmp_path / "fx_signal_history.json"
        a = _make_assessment()
        record = build_fx_signal_record(a, created_at="2026-01-15T09:00:00+09:00")
        save_fx_signal_record(record, path=path)
        stored2, is_new2 = save_fx_signal_record(record, path=path)
        assert is_new2 is False
        data = json.loads(path.read_text())
        assert len(data["signals"]) == 1  # still 1

    def test_creates_file_if_not_exists(self, tmp_path):
        path = tmp_path / "nonexistent" / "fx_signal_history.json"
        a = _make_assessment()
        record = build_fx_signal_record(a, created_at="2026-01-15T09:00:00+09:00")
        stored, is_new = save_fx_signal_record(record, path=path)
        assert path.exists()
        assert is_new is True


class TestLoadFxSignalHistory:
    def test_returns_empty_when_no_file(self, tmp_path):
        path = tmp_path / "fx_signal_history.json"
        result = load_fx_signal_history(path)
        assert result == {"signals": []}

    def test_raises_on_invalid_format(self, tmp_path):
        path = tmp_path / "fx_signal_history.json"
        path.write_text(json.dumps({"signals": "not-a-list"}), encoding="utf-8")
        with pytest.raises(ValueError, match="形式が不正"):
            load_fx_signal_history(path)

    def test_list_signal_history_returns_list(self, tmp_path):
        path = tmp_path / "fx_signal_history.json"
        result = list_fx_signal_history(path)
        assert isinstance(result, list)
        assert result == []
