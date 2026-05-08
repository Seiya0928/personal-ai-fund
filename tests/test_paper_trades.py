from datetime import date
import importlib.util
from pathlib import Path

from src.alerts.btc_dip_alert import BTC_JPY_ALERT_CONFIG, PositionInput, build_alert_assessment
from src.alerts.order_proposal import generate_order_proposal
from src.alerts.paper_trades import (
    create_paper_trades_from_buy_proposal,
    list_paper_trades,
    save_paper_trade_records,
    summarize_paper_performance,
    update_open_paper_trades,
)
from src.alerts.signal_history import build_signal_record


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


def test_buy_proposal_creates_three_rule_paper_trades():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.notification = {"should_notify": True, "notification_type": "BUY_CANDIDATE"}
    signal = build_signal_record(assessment)
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")

    records, reason = create_paper_trades_from_buy_proposal(signal, proposal)

    assert reason == "created"
    assert len(records) == 3
    assert {record["rule_id"] for record in records} == {"Conservative", "Current", "Wide"}


def test_update_open_paper_trades_closes_for_take_profit_stop_loss_and_timeout(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.notification = {"should_notify": True, "notification_type": "BUY_CANDIDATE"}
    signal = build_signal_record(assessment)
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    records, _ = create_paper_trades_from_buy_proposal(signal, proposal)
    save_paper_trade_records(records, tmp_path / "paper_trades.json")

    updated, changed = update_open_paper_trades(assessment.next_price_lines["buy_candidate_line"] * 1.16, "2026-04-30T09:00:00+09:00", tmp_path / "paper_trades.json")
    assert changed == 3
    assert all(trade["status"] == "closed" for trade in updated)
    assert all(trade["exit_reason"] == "TAKE_PROFIT" for trade in updated)

    records, _ = create_paper_trades_from_buy_proposal(signal, proposal)
    records[0]["paper_trade_id"] += "_sl"
    records[0]["rule_id"] = "Conservative"
    records[1]["paper_trade_id"] += "_sl"
    records[1]["rule_id"] = "Current"
    records[2]["paper_trade_id"] += "_sl"
    records[2]["rule_id"] = "Wide"
    save_paper_trade_records(records, tmp_path / "paper_trades.json")
    updated, _ = update_open_paper_trades(assessment.next_price_lines["buy_candidate_line"] * 0.80, "2026-05-01T09:00:00+09:00", tmp_path / "paper_trades.json")
    assert any(trade["exit_reason"] == "STOP_LOSS" for trade in updated)

    records, _ = create_paper_trades_from_buy_proposal(signal, proposal)
    for idx, record in enumerate(records):
        record["paper_trade_id"] += f"_to_{idx}"
        record["entry_date"] = "2026-01-01"
        record["max_holding_deadline"] = "2026-02-01"
    save_paper_trade_records(records, tmp_path / "paper_trades.json")
    updated, _ = update_open_paper_trades(assessment.next_price_lines["buy_candidate_line"], "2026-07-01T09:00:00+09:00", tmp_path / "paper_trades.json")
    assert any(trade["exit_reason"] == "TIMEOUT" for trade in updated)


def test_open_paper_trade_updates_unrealized_metrics(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.notification = {"should_notify": True, "notification_type": "BUY_CANDIDATE"}
    signal = build_signal_record(assessment)
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    records, _ = create_paper_trades_from_buy_proposal(signal, proposal)
    save_paper_trade_records(records, tmp_path / "paper_trades.json")

    updated, _ = update_open_paper_trades(assessment.next_price_lines["buy_candidate_line"] * 1.02, "2026-04-30T09:00:00+09:00", tmp_path / "paper_trades.json")

    assert all(trade["holding_days"] == 1 for trade in updated)
    assert all(trade["max_unrealized_pnl_pct"] >= 2.0 for trade in updated)


def test_report_paper_performance_script_outputs_rule_summaries(tmp_path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "report_paper_performance.py"
    spec = importlib.util.spec_from_file_location("paper_performance_test", script_path)
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
    assessment.notification = {"should_notify": True, "notification_type": "BUY_CANDIDATE"}
    signal = build_signal_record(assessment)
    proposal, _ = generate_order_proposal(assessment, proposal_jpy=1_000.0, source_status="BUY_CANDIDATE")
    records, _ = create_paper_trades_from_buy_proposal(signal, proposal)
    save_paper_trade_records(records, tmp_path / "paper_trades.json")

    monkeypatch.setattr(module, "parse_args", lambda: type("Args", (), {"state_path": tmp_path / "paper_trades.json"})())
    module.main()
    output = capsys.readouterr().out

    assert "Conservative" in output
    assert "Current" in output
    assert "Wide" in output


def test_paper_trade_module_does_not_reference_execution_code():
    source = (Path(__file__).resolve().parents[1] / "src" / "alerts" / "paper_trades.py").read_text(encoding="utf-8")
    assert "order_executor" not in source
    assert "live_order_once" not in source
