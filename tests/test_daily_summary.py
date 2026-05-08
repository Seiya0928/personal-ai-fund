from pathlib import Path

from src.alerts.btc_dip_alert import BTC_BACKTEST_REFERENCE, AlertAssessment, MarketSnapshot
from src.alerts.daily_summary import (
    build_daily_summary_body,
    load_daily_summary_state,
    mark_daily_summary_sent,
    maybe_send_daily_summary_email,
    should_send_daily_summary,
)
from src.alerts.email_notifier import EmailConfig


def _config():
    return EmailConfig(
        host="smtp.gmail.com",
        port=587,
        username="user@example.com",
        password="app-password",
        from_address="from@example.com",
        to_address="to@example.com",
    )


def _assessment(buy_status="BUY_SKIP"):
    snapshot = MarketSnapshot(
        as_of_utc="2026-05-05T13:00:05+00:00",
        as_of_jst="2026-05-05T22:00:05+09:00",
        current_price=12_140_122.0,
        previous_close=12_272_351.0,
        day_change_pct=-1.08,
        recent_high=12_680_080.0,
        drop_from_recent_high_pct=-4.26,
        sma200=13_205_120.0,
        above_sma200=False,
        last_entry_date_jst=None,
        days_since_last_entry=None,
        has_position=False,
    )
    return AlertAssessment(
        symbol="BTC_JPY",
        display_symbol="BTC/JPY",
        report_slug="btc_jpy_dip_alert",
        market=snapshot,
        buy_status=buy_status,
        hold_status=None,
        checklists={"buy": {}, "hold": {}},
        reasons=[],
        action_reasons=[],
        next_price_lines={"buy_candidate_line": 11_904_180.0},
        position=None,
        positions=[],
        warnings=[],
        reference_backtest=BTC_BACKTEST_REFERENCE,
        note="test",
    )


def test_22_jst_run_is_daily_summary_target(tmp_path):
    decision = should_send_daily_summary(
        "2026-05-05T22:00:05+09:00",
        requested=True,
        force=False,
        state_path=tmp_path / "daily_summary_state.json",
    )

    assert decision.requested is True
    assert decision.should_send is True
    assert decision.skipped_reason is None


def test_9_and_15_jst_runs_are_not_daily_summary_targets(tmp_path):
    for ts in ["2026-05-05T09:00:05+09:00", "2026-05-05T15:00:05+09:00"]:
        decision = should_send_daily_summary(
            ts,
            requested=True,
            force=False,
            state_path=tmp_path / "daily_summary_state.json",
        )

        assert decision.should_send is False
        assert decision.skipped_reason == "not_22_jst_run"


def test_same_day_second_summary_is_deduped(tmp_path):
    state_path = tmp_path / "daily_summary_state.json"
    mark_daily_summary_sent("2026-05-05", state_path)

    decision = should_send_daily_summary(
        "2026-05-05T22:00:05+09:00",
        requested=True,
        force=False,
        state_path=state_path,
    )

    assert decision.should_send is False
    assert decision.skipped_reason == "daily_summary_already_sent"
    assert load_daily_summary_state(state_path)["sent_dates"] == ["2026-05-05"]


def test_force_daily_summary_ignores_time_and_dedup(tmp_path):
    state_path = tmp_path / "daily_summary_state.json"
    mark_daily_summary_sent("2026-05-05", state_path)

    decision = should_send_daily_summary(
        "2026-05-05T09:00:05+09:00",
        requested=False,
        force=True,
        state_path=state_path,
    )

    assert decision.requested is True
    assert decision.should_send is True
    assert decision.skipped_reason is None


def test_dry_run_daily_summary_does_not_send(monkeypatch, tmp_path):
    called = {"send": False}

    def fake_send(*args, **kwargs):
        called["send"] = True

    monkeypatch.setattr("src.alerts.daily_summary.send_email_via_smtp", fake_send)
    decision = should_send_daily_summary(
        "2026-05-05T22:00:05+09:00",
        requested=True,
        force=False,
        state_path=tmp_path / "daily_summary_state.json",
    )
    body = build_daily_summary_body(
        _assessment(),
        "2026-05-05T22:00:05+09:00",
        should_notify=False,
        signal_history=[],
        paper_trade_open_count=0,
        markdown_report_path=Path("reports/btc_jpy_dip_alert_20260505.md"),
    )

    result = maybe_send_daily_summary_email(body, decision, dry_run_notify=True, config=_config())

    assert result.sent is False
    assert result.skipped_reason == "dry_run_notify=true"
    assert result.payload_preview["subject"] == "【BTC Alert Daily】日次サマリー"
    assert "実発注は行っていません。" in result.payload_preview["body"]
    assert called["send"] is False


def test_buy_skip_daily_summary_is_sendable(monkeypatch, tmp_path):
    sent = {"subject": None}

    def fake_send(config, payload):
        sent["subject"] = payload["subject"]

    monkeypatch.setattr("src.alerts.daily_summary.send_email_via_smtp", fake_send)
    decision = should_send_daily_summary(
        "2026-05-05T22:00:05+09:00",
        requested=True,
        force=False,
        state_path=tmp_path / "daily_summary_state.json",
    )
    body = build_daily_summary_body(
        _assessment("BUY_SKIP"),
        "2026-05-05T22:00:05+09:00",
        should_notify=False,
        signal_history=[],
        paper_trade_open_count=0,
        markdown_report_path=Path("reports/btc_jpy_dip_alert_20260505.md"),
    )

    result = maybe_send_daily_summary_email(body, decision, dry_run_notify=False, config=_config())

    assert result.sent is True
    assert sent["subject"] == "【BTC Alert Daily】日次サマリー"
