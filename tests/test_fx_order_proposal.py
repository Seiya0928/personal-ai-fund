import importlib.util
from pathlib import Path

from src.fx.models import FXSignal
from src.fx.order_proposal import (
    generate_fx_order_proposal,
    list_fx_order_proposals,
    save_fx_order_proposal,
)


def _signal(action="BUY", **overrides):
    data = {
        "signal_id": f"usdjpy_20260508_220000_{action.lower()}",
        "symbol": "USD/JPY",
        "action": action,
        "price": 155.12,
        "ask": 155.13,
        "bid": 155.11,
        "spread_pips": 1.0,
        "timestamp": "2026-05-08T22:00:00+09:00",
        "reasons": ["RSI=25.00 < 30", "spread=1.00pips"],
        "stop_loss": 154.82 if action == "BUY" else 155.42,
        "take_profit": 155.62 if action == "BUY" else 154.62,
        "skip_reason": None,
    }
    data.update(overrides)
    return FXSignal(**data)


def test_fx_buy_signal_creates_manual_order_proposal():
    proposal, reason = generate_fx_order_proposal(_signal("BUY"))

    assert reason is None
    assert proposal["symbol"] == "USD/JPY"
    assert proposal["side"] == "BUY"
    assert proposal["execution_type"] == "LIMIT"
    assert proposal["send_to_exchange"] is False
    assert proposal["requires_manual_confirmation"] is True
    assert proposal["stop_loss"] == 154.82
    assert proposal["take_profit"] == 155.62
    assert proposal["max_loss_jpy"] > 0
    assert proposal["rationale"]
    assert proposal["invalidation_conditions"]


def test_fx_sell_signal_creates_manual_order_proposal():
    proposal, reason = generate_fx_order_proposal(_signal("SELL"))

    assert reason is None
    assert proposal["side"] == "SELL"
    assert proposal["stop_loss"] == 155.42
    assert proposal["take_profit"] == 154.62


def test_fx_watch_and_skip_do_not_create_proposal():
    watch, watch_reason = generate_fx_order_proposal(_signal("WATCH", stop_loss=None, take_profit=None))
    skip, skip_reason = generate_fx_order_proposal(_signal("SKIP", stop_loss=None, take_profit=None))

    assert watch is None
    assert skip is None
    assert "注文提案生成対象外" in watch_reason
    assert "注文提案生成対象外" in skip_reason


def test_fx_proposal_save_deduplicates_by_signal_id(tmp_path: Path):
    proposal, _ = generate_fx_order_proposal(_signal("BUY"))
    state_path = tmp_path / "fx_order_proposals.json"

    stored1, saved1 = save_fx_order_proposal(proposal, state_path)
    stored2, saved2 = save_fx_order_proposal(proposal, state_path)

    assert saved1 is True
    assert saved2 is False
    assert stored1["proposal_id"] == stored2["proposal_id"]
    assert len(list_fx_order_proposals(state_path)) == 1


def test_list_fx_order_proposals_script_outputs_rows(tmp_path: Path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "list_fx_order_proposals.py"
    spec = importlib.util.spec_from_file_location("list_fx_order_proposals_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    proposal, _ = generate_fx_order_proposal(_signal("BUY"))
    state_path = tmp_path / "fx_order_proposals.json"
    save_fx_order_proposal(proposal, state_path)
    monkeypatch.setattr(module, "parse_args", lambda: type("Args", (), {"state_path": state_path})())

    module.main()
    output = capsys.readouterr().out

    assert proposal["proposal_id"] in output
    assert "USD/JPY | BUY" in output


def test_fx_proposal_code_has_no_execution_route():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src" / "fx" / "order_proposal.py",
        root / "scripts" / "list_fx_order_proposals.py",
    ]
    forbidden = ["order_executor", "live_order_once", "/private/v1/order", "place_order"]
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source
