from pathlib import Path

import pytest

from src.risk.execution_gate import (
    require_approval_phrase,
    validate_manual_execution_proposal,
)


def _proposal(**overrides):
    data = {
        "proposal_id": "proposal_gate_001",
        "symbol": "BTC_JPY",
        "side": "BUY",
        "execution_type": "LIMIT",
        "estimated_jpy": 1_000.0,
        "status": "proposed",
        "send_to_exchange": False,
        "requires_manual_confirmation": True,
        "stop_loss": 10_000_000.0,
        "take_profit": 12_000_000.0,
        "max_loss_jpy": 100.0,
        "rationale": ["test rationale"],
        "invalidation_conditions": ["test invalidation"],
    }
    data.update(overrides)
    return data


def test_common_gate_accepts_safe_manual_proposal(tmp_path: Path):
    result = validate_manual_execution_proposal(
        _proposal(),
        dry_run=True,
        read_only=True,
        stop_trading_file=tmp_path / "STOP_TRADING",
    )

    assert result.ok is True
    assert "proposal_risk_fields" in result.checked


def test_common_gate_blocks_kill_switch(tmp_path: Path):
    stop_file = tmp_path / "STOP_TRADING"
    stop_file.write_text("stop", encoding="utf-8")

    with pytest.raises(ValueError, match="kill switch"):
        validate_manual_execution_proposal(
            _proposal(),
            dry_run=True,
            read_only=True,
            stop_trading_file=stop_file,
        )


def test_common_gate_requires_risk_fields(tmp_path: Path):
    with pytest.raises(ValueError, match="max_loss_jpy"):
        validate_manual_execution_proposal(
            _proposal(max_loss_jpy=None),
            dry_run=True,
            read_only=True,
            stop_trading_file=tmp_path / "STOP_TRADING",
        )


def test_common_gate_blocks_duplicate_guard(tmp_path: Path):
    class Guard:
        def is_duplicate(self, symbol, side, order_type, amount_jpy):
            return True

    with pytest.raises(ValueError, match="duplicate"):
        validate_manual_execution_proposal(
            _proposal(),
            dry_run=True,
            read_only=True,
            stop_trading_file=tmp_path / "STOP_TRADING",
            duplicate_guard=Guard(),
        )


def test_approval_phrase_must_match():
    require_approval_phrase("APPROVE", "APPROVE")
    with pytest.raises(ValueError, match="approval phrase"):
        require_approval_phrase("WRONG", "APPROVE")
