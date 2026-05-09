"""Tests for src/fx/fx_paper_trade.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from src.fx.fx_paper_trade import (
    create_fx_paper_trades_from_proposal,
    update_open_fx_paper_trades,
    summarize_fx_paper_performance,
    load_fx_paper_trades,
    save_fx_paper_trades,
    FX_PAPER_TRADE_RULES,
)

JST = ZoneInfo("Asia/Tokyo")


def _make_proposal(side: str = "BUY", **kwargs) -> dict:
    defaults = {
        "proposal_id": "fx_test_signal_buy_proposal",
        "source_signal_id": "test_signal_001",
        "symbol": "USD/JPY",
        "side": side,
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
    defaults.update(kwargs)
    return defaults


def _make_signal_record(created_at: str = "2026-01-15T09:00:00+09:00") -> dict:
    return {
        "signal_id": "usdjpy_20260115_090000_fx_candidate",
        "created_at": created_at,
        "symbol": "USD/JPY",
    }


class TestCreateFxPaperTrades:
    def test_creates_three_rules_from_buy_proposal(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="BUY")
        signal_rec = _make_signal_record()
        trades, reason = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        assert reason == "created"
        assert len(trades) == 3
        rule_ids = [t["rule_id"] for t in trades]
        assert "Conservative" in rule_ids
        assert "Current" in rule_ids
        assert "Wide" in rule_ids
        for t in trades:
            assert t["side"] == "BUY"

    def test_creates_three_rules_from_sell_proposal(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="SELL")
        signal_rec = _make_signal_record()
        trades, reason = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        assert reason == "created"
        assert len(trades) == 3
        for t in trades:
            assert t["side"] == "SELL"

    def test_returns_empty_without_proposal(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        signal_rec = _make_signal_record()
        trades, reason = create_fx_paper_trades_from_proposal(signal_rec, None, path=path)
        assert trades == []
        assert reason == "order_proposal_not_found"

    def test_returns_empty_without_sl_tp(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="BUY", stop_loss=None, take_profit=None)
        signal_rec = _make_signal_record()
        trades, reason = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        assert trades == []
        assert "stop_loss" in reason or "take_profit" in reason

    def test_duplicate_not_saved(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="BUY")
        signal_rec = _make_signal_record()
        trades1, _ = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        trades2, _ = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        # Both return 3, but file should still have 3 (not 6)
        data = json.loads(path.read_text())
        assert len(data["paper_trades"]) == 3

    def test_trade_ids_use_fx_prefix(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="BUY")
        signal_rec = _make_signal_record()
        trades, _ = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        for t in trades:
            assert t["paper_trade_id"].startswith("fx_")

    def test_holding_deadline_is_iso_string(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        proposal = _make_proposal(side="BUY")
        signal_rec = _make_signal_record()
        trades, _ = create_fx_paper_trades_from_proposal(signal_rec, proposal, path=path)
        for t in trades:
            dt = datetime.fromisoformat(t["max_holding_deadline"])
            assert dt is not None


class TestUpdateOpenFxPaperTrades:
    def _setup_open_trade(self, tmp_path: Path, side: str, entry: float, sl: float, tp: float,
                          opened_at: str = "2026-01-15T09:00:00+09:00",
                          max_holding_hours: int = 48) -> Path:
        from datetime import timedelta
        from src.fx.fx_paper_trade import _add_hours
        path = tmp_path / "fx_paper_trades.json"
        deadline = _add_hours(opened_at, max_holding_hours)
        trade = {
            "paper_trade_id": f"fx_test_{side.lower()}_current",
            "source_signal_id": "test",
            "source_order_proposal_id": "prop_test",
            "rule_id": "Current",
            "symbol": "USD/JPY",
            "side": side,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "usd_units": 1000.0,
            "max_loss_jpy": 300.0,
            "opened_at": opened_at,
            "max_holding_hours": max_holding_hours,
            "max_holding_deadline": deadline,
            "status": "open",
            "exit_price": None,
            "exit_reason": None,
            "closed_at": None,
            "pnl_jpy": 0.0,
            "holding_hours": 0.0,
            "max_favorable_pips": 0.0,
            "max_adverse_pips": 0.0,
        }
        path.write_text(json.dumps({"paper_trades": [trade]}), encoding="utf-8")
        return path

    def test_buy_tp_hit(self, tmp_path):
        # BUY: current >= take_profit → TAKE_PROFIT
        path = self._setup_open_trade(tmp_path, "BUY", entry=145.50, sl=145.20, tp=146.00)
        updated, count = update_open_fx_paper_trades(146.10, "2026-01-15T10:00:00+09:00", path=path)
        assert len(updated) == 1
        assert updated[0]["exit_reason"] == "TAKE_PROFIT"
        assert updated[0]["status"] == "closed"

    def test_buy_sl_hit(self, tmp_path):
        # BUY: current <= stop_loss → STOP_LOSS
        path = self._setup_open_trade(tmp_path, "BUY", entry=145.50, sl=145.20, tp=146.00)
        updated, count = update_open_fx_paper_trades(145.10, "2026-01-15T10:00:00+09:00", path=path)
        assert updated[0]["exit_reason"] == "STOP_LOSS"
        assert updated[0]["status"] == "closed"

    def test_sell_tp_hit(self, tmp_path):
        # SELL: current <= take_profit → TAKE_PROFIT
        path = self._setup_open_trade(tmp_path, "SELL", entry=145.50, sl=145.80, tp=145.00)
        updated, count = update_open_fx_paper_trades(144.90, "2026-01-15T10:00:00+09:00", path=path)
        assert updated[0]["exit_reason"] == "TAKE_PROFIT"
        assert updated[0]["status"] == "closed"

    def test_sell_sl_hit(self, tmp_path):
        # SELL: current >= stop_loss → STOP_LOSS
        path = self._setup_open_trade(tmp_path, "SELL", entry=145.50, sl=145.80, tp=145.00)
        updated, count = update_open_fx_paper_trades(145.90, "2026-01-15T10:00:00+09:00", path=path)
        assert updated[0]["exit_reason"] == "STOP_LOSS"
        assert updated[0]["status"] == "closed"

    def test_timeout(self, tmp_path):
        # as_of >= deadline → TIMEOUT
        path = self._setup_open_trade(
            tmp_path, "BUY", entry=145.50, sl=145.20, tp=146.00,
            opened_at="2026-01-15T09:00:00+09:00",
            max_holding_hours=1,
        )
        # 2h later, past the 1h deadline
        updated, count = update_open_fx_paper_trades(145.55, "2026-01-15T11:00:00+09:00", path=path)
        assert updated[0]["exit_reason"] == "TIMEOUT"
        assert updated[0]["status"] == "closed"

    def test_pnl_buy_positive(self, tmp_path):
        path = self._setup_open_trade(tmp_path, "BUY", entry=145.00, sl=144.50, tp=146.00)
        updated, _ = update_open_fx_paper_trades(145.50, "2026-01-15T10:00:00+09:00", path=path)
        # pnl = (145.50 - 145.00) * 1000 = 500
        assert updated[0]["pnl_jpy"] == pytest.approx(500.0, abs=1.0)

    def test_pnl_sell_positive(self, tmp_path):
        path = self._setup_open_trade(tmp_path, "SELL", entry=145.50, sl=146.00, tp=145.00)
        updated, _ = update_open_fx_paper_trades(145.00, "2026-01-15T10:00:00+09:00", path=path)
        # pnl = (145.50 - 145.00) * 1000 = 500
        assert updated[0]["pnl_jpy"] == pytest.approx(500.0, abs=1.0)

    def test_open_trade_unchanged_when_no_exit(self, tmp_path):
        path = self._setup_open_trade(tmp_path, "BUY", entry=145.50, sl=145.20, tp=146.00)
        updated, count = update_open_fx_paper_trades(145.55, "2026-01-15T10:00:00+09:00", path=path)
        assert updated[0]["status"] == "open"
        assert updated[0]["exit_reason"] is None


class TestSummarizeFxPaperPerformance:
    def test_empty_returns_three_rules(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        summaries = summarize_fx_paper_performance(path=path)
        assert len(summaries) == 3
        rule_ids = [s["rule_id"] for s in summaries]
        assert "Conservative" in rule_ids
        assert "Current" in rule_ids
        assert "Wide" in rule_ids

    def test_win_rate_calculation(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        trades = [
            {
                "paper_trade_id": "fx_t1",
                "rule_id": "Current",
                "status": "closed",
                "pnl_jpy": 500.0,
                "holding_hours": 24.0,
                "exit_reason": "TAKE_PROFIT",
            },
            {
                "paper_trade_id": "fx_t2",
                "rule_id": "Current",
                "status": "closed",
                "pnl_jpy": -300.0,
                "holding_hours": 12.0,
                "exit_reason": "STOP_LOSS",
            },
        ]
        save_fx_paper_trades({"paper_trades": trades}, path=path)
        summaries = summarize_fx_paper_performance(path=path)
        current = next(s for s in summaries if s["rule_id"] == "Current")
        assert current["trades"] == 2
        assert current["closed"] == 2
        assert current["win_rate"] == pytest.approx(50.0)
        assert current["total_pnl_jpy"] == pytest.approx(200.0)
        assert current["tp_count"] == 1
        assert current["sl_count"] == 1

    def test_all_summary_fields_present(self, tmp_path):
        path = tmp_path / "fx_paper_trades.json"
        summaries = summarize_fx_paper_performance(path=path)
        required = ["rule_id", "trades", "open", "closed", "win_rate", "total_pnl_jpy",
                    "avg_holding_hours", "tp_count", "sl_count", "timeout_count"]
        for s in summaries:
            for field in required:
                assert field in s, f"Missing field {field} in {s['rule_id']}"
