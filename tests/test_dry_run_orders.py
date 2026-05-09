import importlib.util
import json
from pathlib import Path

from src.alerts.dry_run_orders import (
    DRY_RUN_ORDER_APPROVAL_PHRASE,
    build_order_body_from_proposal,
    list_dry_run_orders,
    record_dry_run_order_from_proposal,
)
from src.alerts.order_proposal import list_order_proposals, save_order_proposal


def _proposal(**overrides):
    data = {
        "proposal_id": "proposal_test_001",
        "source_signal_id": "btc_jpy_20260508_090000_buy_candidate",
        "created_at": "2026-05-08T09:00:00+09:00",
        "symbol": "BTC_JPY",
        "side": "BUY",
        "execution_type": "LIMIT",
        "suggested_price": 11_904_180.0,
        "suggested_size": 0.00008,
        "estimated_jpy": 952.33,
        "reason": "買い候補ライン到達または接近のため、手動確認用のBUY注文案を生成",
        "source_status": "BUY_CANDIDATE",
        "requires_manual_confirmation": True,
        "send_to_exchange": False,
        "status": "proposed",
        "risk_notes": [],
        "gmo_spot_symbol": "BTC",
        "position_id": None,
        "estimated_pnl_pct": None,
        "estimated_pnl_jpy": None,
        "note": None,
        "stop_loss": 10_416_157.0,
        "take_profit": 13_094_598.0,
        "max_loss_jpy": 119.04,
        "rationale": ["source_status=BUY_CANDIDATE"],
        "invalidation_conditions": ["STOP_TRADING が有効"],
    }
    data.update(overrides)
    return data


def _save(path: Path, proposal=None):
    proposal = proposal or _proposal()
    save_order_proposal(proposal, path)
    return proposal


def test_proposal_creates_dry_run_order_and_updates_status(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    proposal = _save(proposals_path)

    record, order_body = record_dry_run_order_from_proposal(
        proposal["proposal_id"],
        DRY_RUN_ORDER_APPROVAL_PHRASE,
        dry_run=True,
        read_only=True,
        order_proposals_path=proposals_path,
        dry_run_orders_path=orders_path,
        created_at="2026-05-08T09:00:00+09:00",
    )

    assert record["dry_run_order_id"] == "dry_btc_jpy_20260508_001"
    assert record["source_order_proposal_id"] == proposal["proposal_id"]
    assert record["gmo_spot_symbol"] == "BTC"
    assert record["price"] == 11_904_180
    assert record["entry_price"] == 11_904_180
    assert record["size"] == "0.00008000"
    assert record["notional_jpy"] == 952.33
    assert record["stop_loss"] == 10_416_157.0
    assert record["take_profit"] == 13_094_598.0
    assert record["max_loss_jpy"] == 119.04
    assert record["source_signal_id"] == "btc_jpy_20260508_090000_buy_candidate"
    assert record["approval_status"] == "confirmed"
    assert record["send_to_exchange"] is False
    assert record["read_only"] is True
    assert record["dry_run"] is True
    assert order_body["symbol"] == "BTC"
    updated = list_order_proposals(proposals_path)[0]
    assert updated["status"] == "dry_run_recorded"
    assert updated["note"] == "DRY_RUN order recorded. No exchange order sent."


def test_wrong_approval_phrase_does_not_record(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    proposal = _save(proposals_path)

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            "WRONG",
            dry_run=True,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=orders_path,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "approval phrase" in str(exc)

    assert list_dry_run_orders(orders_path) == []
    assert list_order_proposals(proposals_path)[0]["status"] == "proposed"


def test_duplicate_dry_run_order_from_same_proposal_is_not_saved_twice(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    proposal = _save(proposals_path)

    first, _ = record_dry_run_order_from_proposal(
        proposal["proposal_id"],
        DRY_RUN_ORDER_APPROVAL_PHRASE,
        dry_run=True,
        read_only=True,
        order_proposals_path=proposals_path,
        dry_run_orders_path=orders_path,
        created_at="2026-05-08T09:00:00+09:00",
    )
    second, _ = record_dry_run_order_from_proposal(
        proposal["proposal_id"],
        DRY_RUN_ORDER_APPROVAL_PHRASE,
        dry_run=True,
        read_only=True,
        order_proposals_path=proposals_path,
        dry_run_orders_path=orders_path,
        created_at="2026-05-08T15:00:00+09:00",
    )

    assert first["dry_run_order_id"] == second["dry_run_order_id"]
    assert len(list_dry_run_orders(orders_path)) == 1


def test_duplicate_dry_run_order_from_same_source_signal_is_not_saved_twice(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    first_proposal = _proposal(proposal_id="proposal_test_001")
    second_proposal = _proposal(proposal_id="proposal_test_002")
    proposals_path.write_text(
        json.dumps({"proposals": [first_proposal, second_proposal]}, ensure_ascii=False),
        encoding="utf-8",
    )

    first, _ = record_dry_run_order_from_proposal(
        first_proposal["proposal_id"],
        DRY_RUN_ORDER_APPROVAL_PHRASE,
        dry_run=True,
        read_only=True,
        order_proposals_path=proposals_path,
        dry_run_orders_path=orders_path,
        created_at="2026-05-08T09:00:00+09:00",
    )
    second, _ = record_dry_run_order_from_proposal(
        second_proposal["proposal_id"],
        DRY_RUN_ORDER_APPROVAL_PHRASE,
        dry_run=True,
        read_only=True,
        order_proposals_path=proposals_path,
        dry_run_orders_path=orders_path,
        created_at="2026-05-08T15:00:00+09:00",
    )

    assert first["dry_run_order_id"] == second["dry_run_order_id"]
    assert len(list_dry_run_orders(orders_path)) == 1


def test_stop_trading_file_blocks_dry_run_order_record(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    stop_file = tmp_path / "STOP_TRADING"
    stop_file.write_text("stop", encoding="utf-8")
    proposal = _save(proposals_path)

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=True,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=orders_path,
            stop_trading_file=stop_file,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "kill switch" in str(exc)

    assert list_dry_run_orders(orders_path) == []


def test_buy_watch_source_status_is_not_dry_run_order_eligible(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    proposal = _save(proposals_path, _proposal(source_status="BUY_WATCH"))

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=True,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=orders_path,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not dry-run order eligible" in str(exc)

    assert list_dry_run_orders(orders_path) == []


def test_dry_run_false_stops(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    proposal = _save(proposals_path)

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=False,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=tmp_path / "dry_run_orders.json",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "DRY_RUN" in str(exc)


def test_read_only_false_stops(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    proposal = _save(proposals_path)

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=True,
            read_only=False,
            order_proposals_path=proposals_path,
            dry_run_orders_path=tmp_path / "dry_run_orders.json",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "READ_ONLY" in str(exc)


def test_send_to_exchange_true_stops(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    proposal = _save(proposals_path, _proposal(send_to_exchange=True))

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=True,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=tmp_path / "dry_run_orders.json",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "send_to_exchange" in str(exc)


def test_requires_manual_confirmation_false_stops(tmp_path):
    proposals_path = tmp_path / "order_proposals.json"
    proposal = _save(proposals_path, _proposal(requires_manual_confirmation=False))

    try:
        record_dry_run_order_from_proposal(
            proposal["proposal_id"],
            DRY_RUN_ORDER_APPROVAL_PHRASE,
            dry_run=True,
            read_only=True,
            order_proposals_path=proposals_path,
            dry_run_orders_path=tmp_path / "dry_run_orders.json",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "requires_manual_confirmation" in str(exc)


def test_order_body_symbol_becomes_btc():
    body = build_order_body_from_proposal(_proposal())

    assert body["symbol"] == "BTC"
    assert body["side"] == "BUY"
    assert body["executionType"] == "LIMIT"


def test_dry_run_order_scripts_do_not_reference_execution_code_or_private_order_endpoint():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src" / "alerts" / "dry_run_orders.py",
        root / "scripts" / "dry_run_order_from_proposal.py",
    ]
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        assert "order_executor" not in source
        assert "live_order_once" not in source
        assert "/private/v1/order" not in source
        assert "place_order" not in source


def test_list_dry_run_orders_script_outputs_rows(tmp_path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "list_dry_run_orders.py"
    spec = importlib.util.spec_from_file_location("list_dry_run_orders_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    payload = {
        "dry_run_orders": [
            {
                "dry_run_order_id": "dry_btc_jpy_20260508_001",
                "created_at": "2026-05-08T09:00:00+09:00",
                "source_order_proposal_id": "proposal_test_001",
                "symbol": "BTC_JPY",
                "gmo_spot_symbol": "BTC",
                "side": "BUY",
                "execution_type": "LIMIT",
                "price": 11_904_180,
                "size": "0.00008000",
                "estimated_jpy": 952.33,
                "notional_jpy": 952.33,
                "entry_price": 11_904_180,
                "stop_loss": 10_416_157.0,
                "take_profit": 13_094_598.0,
                "max_loss_jpy": 119.04,
                "source_signal_id": "btc_jpy_20260508_090000_buy_candidate",
                "reason": "BUY_CANDIDATE",
                "status": "dry_run_recorded",
                "send_to_exchange": False,
                "requires_manual_confirmation": True,
                "approval_phrase_confirmed": True,
                "approval_status": "confirmed",
                "read_only": True,
                "dry_run": True,
            }
        ]
    }
    state_path = tmp_path / "dry_run_orders.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(module, "parse_args", lambda: type("Args", (), {"state_path": state_path})())

    module.main()
    output = capsys.readouterr().out

    assert "dry_btc_jpy_20260508_001" in output
    assert "proposal_test_001" in output
    assert "BTC_JPY | BTC | BUY" in output
    assert "max_loss=119.04" in output
    assert "source_signal=btc_jpy_20260508_090000_buy_candidate" in output
    assert "approval=confirmed" in output


def test_dry_run_order_from_proposal_cli_noninteractive_records(tmp_path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dry_run_order_from_proposal.py"
    spec = importlib.util.spec_from_file_location("dry_run_order_from_proposal_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    proposals_path = tmp_path / "order_proposals.json"
    orders_path = tmp_path / "dry_run_orders.json"
    proposal = _save(proposals_path)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("READ_ONLY", "true")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "proposal_id": proposal["proposal_id"],
                "order_proposals_path": proposals_path,
                "dry_run_orders_path": orders_path,
                "yes_i_understand_dry_run_only": True,
            },
        )(),
    )

    exit_code = module.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "DRY_RUN order recorded. No exchange order sent." in output
    assert "symbol: BTC" in output
    assert list_dry_run_orders(orders_path)[0]["source_order_proposal_id"] == proposal["proposal_id"]
