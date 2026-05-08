import importlib.util
from pathlib import Path

from src.alerts.btc_dip_alert import BTC_JPY_ALERT_CONFIG, build_alert_assessment
from src.alerts.manual_positions import (
    add_manual_position,
    close_manual_position,
    list_manual_positions,
    parse_position_input,
    select_active_position,
)
from src.alerts.notification_decision import NotificationState, notify_decision


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


def test_add_and_list_manual_position(tmp_path):
    path = tmp_path / "manual_positions.json"
    position = add_manual_position(
        symbol="BTC_JPY",
        entry_price=12000000,
        entry_date="2026-04-29",
        position_size=0.001,
        note="test position",
        path=path,
    )

    positions = list_manual_positions(path)

    assert position["id"] == "btc_20260429_001"
    assert len(positions) == 1
    assert positions[0]["status"] == "open"


def test_close_manual_position(tmp_path):
    path = tmp_path / "manual_positions.json"
    position = add_manual_position(
        symbol="BTC_JPY",
        entry_price=12000000,
        entry_date="2026-04-29",
        position_size=0.001,
        note="test position",
        path=path,
    )

    closed = close_manual_position(
        position_id=position["id"],
        exit_price=13200000,
        exit_date="2026-05-10",
        reason="TAKE_PROFIT",
        path=path,
    )

    assert closed["status"] == "closed"
    assert closed["realized_pnl_pct"] == 10.0
    assert closed["realized_pnl_jpy"] == 1200.0


def test_select_active_position_warns_and_uses_latest(tmp_path):
    path = tmp_path / "manual_positions.json"
    add_manual_position("BTC_JPY", 12000000, "2026-04-28", 0.001, "older", path)
    latest = add_manual_position("BTC_JPY", 12100000, "2026-04-29", 0.001, "latest", path)

    selected, warnings, positions = select_active_position("BTC_JPY", path)

    assert selected["id"] == latest["id"]
    assert len(positions) == 2
    assert warnings


def test_hold_status_take_profit_stop_loss_timeout_and_hold(tmp_path):
    path = tmp_path / "manual_positions.json"
    base = add_manual_position("BTC_JPY", 100.0, "2026-04-01", 1.0, "test", path)
    manual_input = parse_position_input(base)
    rows = _make_rows([100] * 220)

    take_profit = build_alert_assessment(rows, {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}, manual_input, BTC_JPY_ALERT_CONFIG)
    stop_loss = build_alert_assessment(rows, {"last": 87.0, "timestamp": "2026-04-29T00:00:00Z"}, manual_input, BTC_JPY_ALERT_CONFIG)
    timeout = build_alert_assessment(rows, {"last": 101.0, "timestamp": "2026-07-10T00:00:00Z"}, manual_input, BTC_JPY_ALERT_CONFIG)
    hold = build_alert_assessment(rows, {"last": 105.0, "timestamp": "2026-04-29T00:00:00Z"}, manual_input, BTC_JPY_ALERT_CONFIG)

    assert take_profit.hold_status == "TAKE_PROFIT_CANDIDATE"
    assert stop_loss.hold_status == "STOP_LOSS_CANDIDATE"
    assert timeout.hold_status == "TIMEOUT_EXIT_CANDIDATE"
    assert hold.hold_status == "HOLD"


def test_hold_continuation_does_not_notify_but_hold_to_take_profit_does():
    assessment = build_alert_assessment(
        _make_rows([100] * 220),
        {"last": 105.0, "timestamp": "2026-04-29T00:00:00Z"},
        parse_position_input({
            "id": "btc_20260429_001",
            "symbol": "BTC_JPY",
            "entry_date": "2026-04-01",
            "entry_price": 100.0,
            "position_size": 1.0,
            "note": "test",
            "status": "open",
        }),
        BTC_JPY_ALERT_CONFIG,
    )
    decision = notify_decision(assessment, previous_state=NotificationState(effective_status="HOLD"))
    assert decision.should_notify is False

    assessment_tp = build_alert_assessment(
        _make_rows([100] * 220),
        {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"},
        parse_position_input({
            "id": "btc_20260429_001",
            "symbol": "BTC_JPY",
            "entry_date": "2026-04-01",
            "entry_price": 100.0,
            "position_size": 1.0,
            "note": "test",
            "status": "open",
        }),
        BTC_JPY_ALERT_CONFIG,
    )
    decision_tp = notify_decision(assessment_tp, previous_state=NotificationState(effective_status="HOLD"))
    assert decision_tp.should_notify is True
    assert decision_tp.notification_type == "TAKE_PROFIT_CANDIDATE"


def test_run_script_uses_latest_manual_position(tmp_path, monkeypatch, capsys):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_btc_dip_alert.py"
    spec = importlib.util.spec_from_file_location("run_btc_dip_alert_manual_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    state_path = tmp_path / "alert_state.json"
    positions_path = tmp_path / "manual_positions.json"
    add_manual_position("BTC_JPY", 12000000, "2026-04-28", 0.001, "older", positions_path)
    add_manual_position("BTC_JPY", 12100000, "2026-04-29", 0.001, "latest", positions_path)

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type("Args", (), {
            "entry_price": None,
            "entry_date": None,
            "position_size": None,
            "json_output": False,
            "markdown": False,
                "notify_preview": True,
                "state_path": state_path,
                "manual_positions_path": positions_path,
                "order_proposals_path": tmp_path / "order_proposals.json",
                "signal_history_path": tmp_path / "signal_history.json",
                "paper_trades_path": tmp_path / "paper_trades.json",
                "force_notify": False,
                "send_discord": False,
                "send_email": False,
            "dry_run_notify": False,
            "test_discord": False,
            "test_email": False,
            "proposal_jpy": 1000.0,
            "debug": False,
        })(),
    )

    exit_code = module.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Warnings:" in output
    assert "open position" in output
    assert "Hold status:" in output
