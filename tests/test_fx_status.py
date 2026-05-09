"""Tests for src/fx/fx_status.py"""
from __future__ import annotations

import pytest
from src.fx.fx_status import (
    NEXT_ACTION,
    FXAssessment,
    get_next_action,
    signal_action_to_fx_status,
)


class TestSignalActionToFxStatus:
    def test_skip_gives_fx_skip(self):
        assert signal_action_to_fx_status("SKIP") == "FX_SKIP"

    def test_watch_gives_fx_watch(self):
        assert signal_action_to_fx_status("WATCH") == "FX_WATCH"

    def test_buy_gives_fx_candidate(self):
        assert signal_action_to_fx_status("BUY") == "FX_CANDIDATE"

    def test_sell_gives_fx_candidate(self):
        assert signal_action_to_fx_status("SELL") == "FX_CANDIDATE"

    def test_stale_invalid_gives_fx_stale_invalid(self):
        assert signal_action_to_fx_status("BUY", is_stale_invalid=True) == "FX_STALE_INVALID"

    def test_open_position_tp_gives_tp_candidate(self):
        assert signal_action_to_fx_status("WATCH", open_position_exit_reason="TAKE_PROFIT") == "FX_TAKE_PROFIT_CANDIDATE"

    def test_open_position_sl_gives_sl_candidate(self):
        assert signal_action_to_fx_status("WATCH", open_position_exit_reason="STOP_LOSS") == "FX_STOP_LOSS_CANDIDATE"

    def test_open_position_timeout_gives_timeout_candidate(self):
        assert signal_action_to_fx_status("WATCH", open_position_exit_reason="TIMEOUT") == "FX_TIMEOUT_EXIT_CANDIDATE"

    def test_stale_overrides_open_position(self):
        # stale_invalid=True should override open_position_exit_reason
        result = signal_action_to_fx_status(
            "BUY",
            is_stale_invalid=True,
            open_position_exit_reason="TAKE_PROFIT",
        )
        assert result == "FX_STALE_INVALID"

    def test_unknown_action_gives_fx_skip(self):
        assert signal_action_to_fx_status("UNKNOWN_ACTION") == "FX_SKIP"


class TestGetNextAction:
    def test_all_statuses_have_text(self):
        statuses = [
            "FX_SKIP",
            "FX_WATCH",
            "FX_CANDIDATE",
            "FX_TAKE_PROFIT_CANDIDATE",
            "FX_STOP_LOSS_CANDIDATE",
            "FX_TIMEOUT_EXIT_CANDIDATE",
            "FX_STALE_INVALID",
        ]
        for status in statuses:
            text = get_next_action(status)
            assert isinstance(text, str)
            assert len(text) > 0

    def test_unknown_status_returns_default(self):
        result = get_next_action("TOTALLY_UNKNOWN_STATUS")
        assert result == "不明なステータス。"

    def test_all_next_action_keys_match_statuses(self):
        """NEXT_ACTION dict のキーがすべて既知のステータスのみであること。"""
        known = {
            "FX_SKIP", "FX_WATCH", "FX_CANDIDATE",
            "FX_TAKE_PROFIT_CANDIDATE", "FX_STOP_LOSS_CANDIDATE",
            "FX_TIMEOUT_EXIT_CANDIDATE", "FX_STALE_INVALID",
        }
        for key in NEXT_ACTION:
            assert key in known


class TestFXAssessment:
    def test_default_lists_are_empty(self):
        assessment = FXAssessment(
            signal_id="test_id",
            symbol="USD/JPY",
            action="WATCH",
            fx_status="FX_WATCH",
            next_action="監視のみ。",
            current_price=145.0,
            market_data_timestamp="2026-01-01T00:00:00+09:00",
            stale_level="fresh",
            stale_reason="新鮮",
            is_stale_invalid=False,
            stop_loss=None,
            take_profit=None,
        )
        assert assessment.reasons == []
        assert assessment.paper_trade_ids == []
        assert assessment.skip_reason is None
        assert assessment.order_proposal_id is None
