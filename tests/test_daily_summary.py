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


def _summary_body_for_status(buy_status: str) -> str:
    return build_daily_summary_body(
        _assessment(buy_status),
        "2026-05-05T22:00:05+09:00",
        should_notify=buy_status != "BUY_SKIP",
        signal_history=[],
        paper_trade_open_count=0,
        markdown_report_path=Path("reports/btc_jpy_dip_alert_20260505.md"),
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


def test_daily_summary_includes_signal_counts_and_paper_trade_performance():
    body = build_daily_summary_body(
        _assessment("BUY_WATCH"),
        "2026-05-05T22:00:05+09:00",
        should_notify=True,
        signal_history=[
            {"created_at": "2026-05-05T09:00:05+09:00", "buy_status": "BUY_SKIP"},
            {"created_at": "2026-05-05T15:00:05+09:00", "buy_status": "BUY_WATCH"},
            {"created_at": "2026-05-05T22:00:05+09:00", "buy_status": "BUY_CANDIDATE"},
        ],
        paper_trade_open_count=2,
        markdown_report_path=Path("reports/btc_jpy_dip_alert_20260505.md"),
        paper_trade_performance=[
            {
                "rule_id": "Current",
                "trades": 3,
                "open": 2,
                "closed": 1,
                "win_rate": 100.0,
                "total_pnl_jpy": 120.5,
                "take_profit_count": 1,
                "stop_loss_count": 0,
                "timeout_count": 0,
            }
        ],
    )

    assert "今日のBUY_WATCH件数: 1" in body
    assert "今日のBUY_CANDIDATE件数: 1" in body
    assert "最新の候補/監視状態: 2026-05-05T22:00:05+09:00 / BUY_CANDIDATE" in body
    assert "paper trade open件数: 2" in body
    assert "paper trade closed件数: 1" in body
    assert "paper trade 損益合計: ¥120.50" in body
    assert "Paper trade Current: trades=3, open=2, closed=1" in body


def test_daily_summary_includes_next_action_for_buy_skip_watch_and_candidate():
    assert "次アクション: 何もしない。記録のみ。" in _summary_body_for_status("BUY_SKIP")
    watch_body = _summary_body_for_status("BUY_WATCH")
    candidate_body = _summary_body_for_status("BUY_CANDIDATE")

    assert "次アクション: 監視のみ。手動購入しない。注文案は作らない。" in watch_body
    assert "order proposal" not in watch_body
    assert "次アクション: order proposalを確認し、必要ならdry-run注文記録を作る。実注文はまだしない。" in candidate_body
    assert "実注文はまだしない" in candidate_body


def test_daily_summary_includes_stale_invalid_next_action():
    assessment = _assessment("BUY_CANDIDATE")
    assessment.market.data_stale_level = "invalid"
    body = build_daily_summary_body(
        assessment,
        "2026-05-05T22:00:05+09:00",
        should_notify=False,
        signal_history=[],
        paper_trade_open_count=0,
        markdown_report_path=Path("reports/btc_jpy_dip_alert_20260505.md"),
    )

    assert "次アクション: 市場データが古いため判断無効。fetch/health checkを確認。" in body
