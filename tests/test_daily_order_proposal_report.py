import importlib.util
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.reports.order_proposal_report import (
    collect_daily_order_proposals,
    render_daily_order_proposal_report,
    save_daily_order_proposal_report,
)

JST = ZoneInfo("Asia/Tokyo")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _state(tmp_path: Path):
    dry_orders = tmp_path / "dry_run_orders.json"
    btc_props = tmp_path / "order_proposals.json"
    fx_props = tmp_path / "fx_order_proposals.json"
    _write_json(
        dry_orders,
        {
            "dry_run_orders": [
                {
                    "dry_run_order_id": "dry_btc_jpy_20260508_001",
                    "created_at": "2026-05-08T09:00:00+09:00",
                    "source_order_proposal_id": "btc_proposal_001",
                    "symbol": "BTC_JPY",
                    "side": "BUY",
                    "price": 11_904_180,
                    "status": "dry_run_recorded",
                    "approval_phrase_confirmed": True,
                }
            ]
        },
    )
    _write_json(
        btc_props,
        {
            "proposals": [
                {
                    "proposal_id": "btc_proposal_001",
                    "stop_loss": 10_416_157,
                    "take_profit": 13_094_598,
                    "max_loss_jpy": 119.04,
                    "rationale": ["source_status=BUY_CANDIDATE"],
                    "invalidation_conditions": ["STOP_TRADING が有効"],
                }
            ]
        },
    )
    _write_json(
        fx_props,
        {
            "proposals": [
                {
                    "proposal_id": "fx_usdjpy_001",
                    "created_at": "2026-05-08T22:00:00+09:00",
                    "source_signal_id": "usdjpy_20260508_220000_buy",
                    "symbol": "USD/JPY",
                    "side": "BUY",
                    "status": "proposed",
                    "suggested_price": 155.12,
                    "stop_loss": 154.82,
                    "take_profit": 155.62,
                    "max_loss_jpy": 300.0,
                    "rationale": ["RSI=25.00 < 30"],
                    "invalidation_conditions": ["FX実注文アダプタが未実装"],
                }
            ]
        },
    )
    return dry_orders, btc_props, fx_props


def test_collects_btc_dry_run_and_fx_proposals_for_target_date(tmp_path: Path):
    dry_orders, btc_props, fx_props = _state(tmp_path)

    proposals = collect_daily_order_proposals(
        target_date=date(2026, 5, 8),
        dry_run_orders_path=dry_orders,
        btc_order_proposals_path=btc_props,
        fx_order_proposals_path=fx_props,
        stop_trading_active=False,
    )

    assert [p.source for p in proposals] == ["BTC", "FX"]
    assert proposals[0].category == "approved"
    assert proposals[1].category == "unapproved"
    assert sum(p.max_loss_jpy for p in proposals) == 419.04


def test_report_renders_categories_total_and_stop_trading(tmp_path: Path):
    dry_orders, btc_props, fx_props = _state(tmp_path)
    proposals = collect_daily_order_proposals(
        target_date=date(2026, 5, 8),
        dry_run_orders_path=dry_orders,
        btc_order_proposals_path=btc_props,
        fx_order_proposals_path=fx_props,
        stop_trading_active=True,
    )

    report = render_daily_order_proposal_report(
        proposals,
        target_date=date(2026, 5, 8),
        generated_at=datetime(2026, 5, 8, 22, 0, tzinfo=JST),
        stop_trading_active=True,
    )

    assert "STOP_TRADING: active - all proposals are execution prohibited" in report
    assert "Total max_loss_jpy: 419.04" in report
    assert "## 未承認" in report
    assert "## 承認済み" in report
    assert "BTC BTC_JPY BUY" in report
    assert "FX USD/JPY BUY" in report
    assert "blocked_by_stop_trading" in report


def test_save_daily_order_proposal_report_uses_expected_filename(tmp_path: Path):
    path = save_daily_order_proposal_report(
        "content",
        target_date=date(2026, 5, 8),
        reports_dir=tmp_path,
    )

    assert path.name == "daily_order_proposals_20260508.md"
    assert path.read_text(encoding="utf-8") == "content"


def test_list_all_order_proposals_cli_writes_report_and_requires_safe_env(tmp_path: Path, capsys, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "list_all_order_proposals.py"
    spec = importlib.util.spec_from_file_location("list_all_order_proposals_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    dry_orders, btc_props, fx_props = _state(tmp_path)
    reports_dir = tmp_path / "reports"
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("READ_ONLY", "true")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "date": date(2026, 5, 8),
                "dry_run_orders_path": dry_orders,
                "btc_order_proposals_path": btc_props,
                "fx_order_proposals_path": fx_props,
                "reports_dir": reports_dir,
                "stop_trading_file": tmp_path / "STOP_TRADING",
                "no_write": False,
            },
        )(),
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "Daily Order Proposals 2026-05-08" in output
    assert (reports_dir / "daily_order_proposals_20260508.md").exists()

    monkeypatch.setenv("DRY_RUN", "false")
    assert module.main() == 1


def test_daily_order_proposal_report_has_no_execution_route():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src" / "reports" / "order_proposal_report.py",
        root / "scripts" / "list_all_order_proposals.py",
    ]
    forbidden = ["broker_adapter", "/private/v1/order", "place_order", "live_order_once", "order_executor"]
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source
