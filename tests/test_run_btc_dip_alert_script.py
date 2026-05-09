from argparse import Namespace
from datetime import datetime
import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_btc_dip_alert.py"
SPEC = importlib.util.spec_from_file_location("run_btc_dip_alert_module", SCRIPT_PATH)
run_btc_dip_alert = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_btc_dip_alert)


def _base_args(tmp_path, **overrides):
    values = {
        "entry_price": None,
        "entry_date": None,
        "position_size": None,
        "json_output": False,
        "markdown": False,
        "notify_preview": False,
        "state_path": tmp_path / "state.json",
        "manual_positions_path": tmp_path / "manual_positions.json",
        "order_proposals_path": tmp_path / "order_proposals.json",
        "signal_history_path": tmp_path / "signal_history.json",
        "paper_trades_path": tmp_path / "paper_trades.json",
        "daily_summary_state_path": tmp_path / "daily_summary_state.json",
        "force_notify": False,
        "send_discord": False,
        "send_email": False,
        "send_daily_summary": False,
        "force_daily_summary": False,
        "dry_run_notify": False,
        "test_discord": False,
        "test_email": False,
        "proposal_jpy": 1000.0,
        "debug": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _buy_skip_assessment(as_of_jst="2026-05-02T00:00:00+09:00"):
    snapshot = run_btc_dip_alert.MarketSnapshot(
        as_of_utc="2026-05-01T15:00:00+00:00",
        as_of_jst=as_of_jst,
        current_price=100.0,
        previous_close=100.0,
        day_change_pct=0.0,
        recent_high=110.0,
        drop_from_recent_high_pct=-9.09,
        sma200=90.0,
        above_sma200=True,
        last_entry_date_jst=None,
        days_since_last_entry=None,
        has_position=False,
    )
    return run_btc_dip_alert.AlertAssessment(
        symbol="BTC_JPY",
        display_symbol="BTC/JPY",
        report_slug="btc_jpy_dip_alert",
        market=snapshot,
        buy_status="BUY_SKIP",
        hold_status=None,
        checklists={"buy": {}, "hold": {}},
        reasons=["skip"],
        action_reasons=[],
        next_price_lines={"buy_candidate_line": 97.0},
        position=None,
        positions=[],
        warnings=[],
        reference_backtest=run_btc_dip_alert.BTC_BACKTEST_REFERENCE,
        note="test",
    )


def _buy_candidate_assessment(as_of_jst="2026-05-05T22:00:05+09:00"):
    assessment = _buy_skip_assessment(as_of_jst)
    assessment.buy_status = "BUY_CANDIDATE"
    assessment.market.current_price = 94.0
    assessment.market.previous_close = 100.0
    assessment.market.day_change_pct = -6.0
    assessment.market.above_sma200 = True
    assessment.next_price_lines = {"buy_candidate_line": 97.0}
    return assessment


def _buy_watch_assessment(as_of_jst="2026-05-05T15:00:05+09:00"):
    assessment = _buy_skip_assessment(as_of_jst)
    assessment.buy_status = "BUY_WATCH"
    assessment.market.current_price = 99.0
    assessment.market.previous_close = 100.0
    assessment.market.day_change_pct = -1.0
    assessment.market.recent_high = 103.0
    assessment.market.drop_from_recent_high_pct = -3.88
    assessment.market.sma200 = 101.0
    assessment.market.above_sma200 = False
    assessment.checklists["buy"] = {
        "dip_trigger": False,
        "trend_ok": False,
        "watch_buy_line_near": True,
        "trend_filter_blocking": True,
    }
    assessment.reasons = [
        "前日比が -1.00% で、買い条件 -3.00% 以下を未達",
        "SMA200 を下回っており、長期上昇トレンド条件を未達",
        "買い候補ラインまで +2.06% で、監視距離 4.00% 以内",
    ]
    assessment.next_price_lines = {
        "buy_candidate_line": 97.0,
        "distance_to_buy_line_pct": 2.06,
        "distance_to_sma200_pct": -1.98,
    }
    return assessment


def test_test_discord_mode_does_not_update_state(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    called = {"save_state": False}

    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: Namespace(
            entry_price=None,
            entry_date=None,
            position_size=None,
            json_output=False,
            markdown=False,
            notify_preview=False,
            state_path=state_path,
            manual_positions_path=tmp_path / "manual_positions.json",
            order_proposals_path=tmp_path / "order_proposals.json",
            force_notify=False,
            send_discord=False,
            send_email=False,
            dry_run_notify=True,
            test_discord=True,
            test_email=False,
            proposal_jpy=1000.0,
            debug=False,
        ),
    )
    monkeypatch.setattr(
        run_btc_dip_alert,
        "save_notification_state",
        lambda *args, **kwargs: called.__setitem__("save_state", True),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert called["save_state"] is False
    assert not state_path.exists()
    assert "Discord payload preview" in output


def test_test_discord_json_does_not_include_webhook_url(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: Namespace(
            entry_price=None,
            entry_date=None,
            position_size=None,
            json_output=True,
            markdown=False,
            notify_preview=False,
            state_path=state_path,
            manual_positions_path=tmp_path / "manual_positions.json",
            order_proposals_path=tmp_path / "order_proposals.json",
            force_notify=False,
            send_discord=False,
            send_email=False,
            dry_run_notify=True,
            test_discord=True,
            test_email=False,
            proposal_jpy=1000.0,
            debug=False,
        ),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "example.test" not in output
    assert '"test_notification": true' in output.lower()


def test_test_email_mode_does_not_update_state(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    called = {"save_state": False}

    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: Namespace(
            entry_price=None,
            entry_date=None,
            position_size=None,
            json_output=False,
            markdown=False,
            notify_preview=False,
            state_path=state_path,
            manual_positions_path=tmp_path / "manual_positions.json",
            order_proposals_path=tmp_path / "order_proposals.json",
            force_notify=False,
            send_discord=False,
            send_email=False,
            dry_run_notify=True,
            test_discord=False,
            test_email=True,
            proposal_jpy=1000.0,
            debug=False,
        ),
    )
    monkeypatch.setattr(
        run_btc_dip_alert,
        "save_notification_state",
        lambda *args, **kwargs: called.__setitem__("save_state", True),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert called["save_state"] is False
    assert not state_path.exists()
    assert "Email payload preview" in output


def test_test_email_json_does_not_include_password(monkeypatch, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("ALERT_EMAIL_PASSWORD", "secret-app-password")
    monkeypatch.setattr(
        run_btc_dip_alert,
        "load_email_config_from_env",
        lambda: run_btc_dip_alert.EmailConfig(
            host="smtp.gmail.com",
            port=587,
            username="user@example.com",
            password="secret-app-password",
            from_address="from@example.com",
            to_address="to@example.com",
        ),
    )
    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: Namespace(
            entry_price=None,
            entry_date=None,
            position_size=None,
            json_output=True,
            markdown=False,
            notify_preview=False,
            state_path=state_path,
            manual_positions_path=tmp_path / "manual_positions.json",
            order_proposals_path=tmp_path / "order_proposals.json",
            force_notify=False,
            send_discord=False,
            send_email=False,
            dry_run_notify=True,
            test_discord=False,
            test_email=True,
            proposal_jpy=1000.0,
            debug=False,
        ),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "secret-app-password" not in output


def test_normal_launchd_equivalent_run_saves_buy_skip_signal_without_paper_trade(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run_btc_dip_alert, "parse_args", lambda: _base_args(tmp_path, markdown=False))
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_skip_assessment())
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-02T09:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Signal saved: True" in output
    assert "Signal id: btc_jpy_20260502_090005_buy_skip" in output
    signal_payload = json.loads((tmp_path / "signal_history.json").read_text(encoding="utf-8"))
    assert signal_payload["signals"][0]["signal_id"] == "btc_jpy_20260502_090005_buy_skip"
    assert signal_payload["signals"][0]["should_notify"] is False
    assert not (tmp_path / "paper_trades.json").exists()


def test_run_script_daily_summary_dry_run_preview_for_buy_skip(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: _base_args(tmp_path, send_daily_summary=True, dry_run_notify=True),
    )
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_skip_assessment("2026-05-05T22:00:05+09:00"))
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T22:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Daily summary payload preview" in output
    assert "【BTC Alert Daily】日次サマリー" in output
    assert "Buy status: BUY_SKIP" in output
    assert "Daily summary sent: False" in output
    assert "Daily summary skipped reason: dry_run_notify=true" in output
    assert not (tmp_path / "daily_summary_state.json").exists()


def test_run_script_daily_summary_marks_state_after_send(monkeypatch, tmp_path, capsys):
    sent = {"count": 0}

    def fake_send(config, payload):
        sent["count"] += 1
        assert payload["subject"] == "【BTC Alert Daily】日次サマリー"
        assert "これは投資助言ではなく" in payload["body"]

    monkeypatch.setattr(
        run_btc_dip_alert,
        "parse_args",
        lambda: _base_args(tmp_path, send_daily_summary=True),
    )
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_skip_assessment("2026-05-05T22:00:05+09:00"))
    monkeypatch.setattr(
        run_btc_dip_alert,
        "load_email_config_from_env",
        lambda: run_btc_dip_alert.EmailConfig("smtp.gmail.com", 587, "user@example.com", "secret", "from@example.com", "to@example.com"),
    )
    monkeypatch.setattr("src.alerts.daily_summary.send_email_via_smtp", fake_send)
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T22:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert sent["count"] == 1
    assert "Daily summary sent: True" in output
    state_payload = json.loads((tmp_path / "daily_summary_state.json").read_text(encoding="utf-8"))
    assert state_payload["sent_dates"] == ["2026-05-05"]


def test_run_script_important_email_notification_still_uses_should_notify(monkeypatch, tmp_path, capsys):
    sent = {"subjects": []}

    def fake_email_send(config, payload):
        sent["subjects"].append(payload["subject"])

    monkeypatch.setattr(run_btc_dip_alert, "parse_args", lambda: _base_args(tmp_path, send_email=True))
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_candidate_assessment())
    monkeypatch.setattr(
        run_btc_dip_alert,
        "load_email_config_from_env",
        lambda: run_btc_dip_alert.EmailConfig("smtp.gmail.com", 587, "user@example.com", "secret", "from@example.com", "to@example.com"),
    )
    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_email_send)
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T15:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert sent["subjects"] == ["【BTC Alert】買い候補"]
    assert "Should notify: True" in output
    assert "Email notification sent" in output


def test_run_script_buy_candidate_saves_order_proposal_and_paper_trades(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run_btc_dip_alert, "parse_args", lambda: _base_args(tmp_path, dry_run_notify=True))
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_candidate_assessment())
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T22:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Buy status: BUY_CANDIDATE" in output
    assert "Order proposal saved: True" in output
    assert "Paper trades created: 3" in output

    proposals = json.loads((tmp_path / "order_proposals.json").read_text(encoding="utf-8"))["proposals"]
    trades = json.loads((tmp_path / "paper_trades.json").read_text(encoding="utf-8"))["paper_trades"]
    assert len(proposals) == 1
    assert proposals[0]["source_status"] == "BUY_CANDIDATE"
    assert proposals[0]["send_to_exchange"] is False
    assert proposals[0]["requires_manual_confirmation"] is True
    assert proposals[0]["max_loss_jpy"] > 0
    assert len(trades) == 3
    assert {trade["rule_id"] for trade in trades} == {"Conservative", "Current", "Wide"}


def test_run_script_buy_watch_notifies_without_order_proposal_or_paper_trade(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run_btc_dip_alert, "parse_args", lambda: _base_args(tmp_path, send_email=True, dry_run_notify=True))
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: _buy_watch_assessment())
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T15:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Buy status: BUY_WATCH" in output
    assert "Should notify: True" in output
    assert "Order proposal saved: False" in output
    assert "source_status=BUY_WATCH は注文案生成対象外" in output
    assert "Paper trades created: 0" in output
    assert not (tmp_path / "order_proposals.json").exists()


def test_stale_market_data_does_not_notify_or_create_order_proposal(monkeypatch, tmp_path, capsys):
    assessment = _buy_candidate_assessment()
    assessment.market.data_stale_level = "invalid"
    assessment.market.data_stale_reason = "market data is older than 24h: age=25.0h"
    assessment.warnings = [assessment.market.data_stale_reason]

    monkeypatch.setattr(run_btc_dip_alert, "parse_args", lambda: _base_args(tmp_path, send_email=True))
    monkeypatch.setattr(run_btc_dip_alert, "load_default_assessment", lambda position, config: assessment)
    monkeypatch.setattr(
        run_btc_dip_alert,
        "load_email_config_from_env",
        lambda: run_btc_dip_alert.EmailConfig("smtp.gmail.com", 587, "user@example.com", "secret", "from@example.com", "to@example.com"),
    )
    monkeypatch.setattr(
        run_btc_dip_alert,
        "datetime",
        type("FixedDateTime", (), {
            "now": staticmethod(lambda tz: datetime.fromisoformat("2026-05-05T15:00:05+09:00"))
        }),
    )

    exit_code = run_btc_dip_alert.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Should notify: False" in output
    assert "Order proposal saved: False" in output
    assert "market data is older than 24h" in output
    assert not (tmp_path / "order_proposals.json").exists()
