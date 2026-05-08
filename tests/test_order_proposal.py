from datetime import date
import importlib.util
from pathlib import Path

from src.alerts.btc_dip_alert import BTC_JPY_ALERT_CONFIG, PositionInput, build_alert_assessment
from src.alerts.order_proposal import (
    generate_order_proposal,
    list_order_proposals,
    mark_order_proposal,
    save_order_proposal,
)


def _make_rows(prices, step_ms=86_400_000):
    rows = []
    for i, price in enumerate(prices):
        rows.append({
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1.0,
            "timestamp": str(i * step_ms),
        })
    return rows


def test_buy_candidate_generates_buy_proposal():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )

    proposal, reason = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")

    assert reason is None
    assert proposal["side"] == "BUY"
    assert proposal["symbol"] == "BTC_JPY"
    assert proposal["gmo_spot_symbol"] == "BTC"
    assert proposal["send_to_exchange"] is False
    assert proposal["requires_manual_confirmation"] is True
    assert proposal["stop_loss"] > 0
    assert proposal["take_profit"] > proposal["suggested_price"]
    assert proposal["max_loss_jpy"] > 0
    assert proposal["rationale"]
    assert proposal["invalidation_conditions"]


def test_buy_proposal_rounds_quantity_down_to_0_00001():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.next_price_lines["buy_candidate_line"] = 12_173_952.0

    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")

    assert proposal["suggested_size"] == 0.00008


def test_buy_proposal_is_not_generated_below_min_quantity():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.next_price_lines["buy_candidate_line"] = 200_000_000.0

    proposal, reason = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")

    assert proposal is None
    assert "minimum quantity" in reason


def test_sell_proposal_is_generated_for_take_profit_stop_loss_and_timeout():
    rows = _make_rows([100] * 220)
    position = PositionInput(
        entry_price=100.0,
        entry_date=date(2026, 4, 1),
        position_size=0.00123,
        position_id="btc_20260429_001",
    )

    tp_assessment = build_alert_assessment(rows, {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}, position, BTC_JPY_ALERT_CONFIG)
    sl_assessment = build_alert_assessment(rows, {"last": 87.0, "timestamp": "2026-04-29T00:00:00Z"}, position, BTC_JPY_ALERT_CONFIG)
    to_assessment = build_alert_assessment(rows, {"last": 101.0, "timestamp": "2026-07-10T00:00:00Z"}, position, BTC_JPY_ALERT_CONFIG)

    tp, _ = generate_order_proposal(tp_assessment, proposal_jpy=1_000.0, source_status="TAKE_PROFIT_CANDIDATE")
    sl, _ = generate_order_proposal(sl_assessment, proposal_jpy=1_000.0, source_status="STOP_LOSS_CANDIDATE")
    to, _ = generate_order_proposal(to_assessment, proposal_jpy=1_000.0, source_status="TIMEOUT_EXIT_CANDIDATE")

    assert tp["side"] == "SELL"
    assert sl["side"] == "SELL"
    assert to["side"] == "SELL"
    assert tp["suggested_size"] == 0.00123
    assert tp["stop_loss"] > 0
    assert tp["take_profit"] > 0
    assert tp["max_loss_jpy"] >= 0
    assert tp["rationale"]
    assert tp["invalidation_conditions"]


def test_duplicate_proposals_are_not_saved_twice(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")

    stored1, saved1 = save_order_proposal(proposal, tmp_path / "order_proposals.json")
    stored2, saved2 = save_order_proposal(proposal, tmp_path / "order_proposals.json")

    assert saved1 is True
    assert saved2 is False
    assert stored1["proposal_id"] == stored2["proposal_id"]
    assert len(list_order_proposals(tmp_path / "order_proposals.json")) == 1


def test_mark_order_proposal_updates_status(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    save_order_proposal(proposal, tmp_path / "order_proposals.json")

    updated = mark_order_proposal(
        proposal_id=proposal["proposal_id"],
        status="ignored",
        note="見送り",
        path=tmp_path / "order_proposals.json",
    )

    assert updated["status"] == "ignored"
    assert updated["note"] == "見送り"


def test_list_order_proposals_script_outputs_rows(tmp_path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "list_order_proposals.py"
    spec = importlib.util.spec_from_file_location("list_order_proposals_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    save_order_proposal(proposal, tmp_path / "order_proposals.json")

    monkeypatch.setattr(module, "parse_args", lambda: type("Args", (), {"state_path": tmp_path / "order_proposals.json"})())

    module.main()
    output = capsys.readouterr().out
    assert proposal["proposal_id"] in output


def test_mark_order_proposal_script_updates_rows(tmp_path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "mark_order_proposal.py"
    spec = importlib.util.spec_from_file_location("mark_order_proposals_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    save_order_proposal(proposal, tmp_path / "order_proposals.json")

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {"id": proposal["proposal_id"], "status": "ignored", "note": "見送り", "state_path": tmp_path / "order_proposals.json"},
        )(),
    )
    module.main()
    output = capsys.readouterr().out
    assert "updated:" in output
    assert mark_order_proposal(proposal["proposal_id"], "ignored", "見送り", tmp_path / "order_proposals.json")["status"] == "ignored"


def test_order_proposal_module_does_not_reference_execution_code():
    source = (Path(__file__).resolve().parents[1] / "src" / "alerts" / "order_proposal.py").read_text(encoding="utf-8")
    assert "order_executor" not in source
    assert "live_order_once" not in source
