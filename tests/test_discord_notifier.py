from pathlib import Path

import requests

from src.alerts.discord_notifier import (
    maybe_send_discord_notification,
    maybe_send_test_discord_notification,
)
from src.alerts.notification_decision import NotificationDecision


def _decision(should_notify=True):
    return NotificationDecision(
        should_notify=should_notify,
        notification_type="BUY_CANDIDATE" if should_notify else "BUY_SKIP",
        title="【BTC Alert】買い候補",
        message="BTC/JPY が買い条件に一致しました。",
        priority="high" if should_notify else "low",
        reasons=[],
        distance_to_buy_line_pct=1.98,
        effective_status="BUY_CANDIDATE" if should_notify else "BUY_SKIP",
        previous_effective_status=None,
        deduped=False,
    )


def test_should_notify_false_skips_without_sending(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_discord_notification(
        decision=_decision(should_notify=False),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert result.sent is False
    assert result.skipped_reason == "should_notify=false"
    assert called["value"] is False


def test_notify_preview_skips_sending(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_discord_notification(
        decision=_decision(),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=True,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert result.sent is False
    assert result.skipped_reason == "notify_preview=true"
    assert called["value"] is False


def test_missing_webhook_skips_sending(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    result = maybe_send_discord_notification(
        decision=_decision(),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        webhook_url=None,
    )

    assert result.sent is False
    assert result.skipped_reason == "DISCORD_WEBHOOK_URL not set"
    assert result.error is None


def test_payload_preview_does_not_include_webhook_url():
    result = maybe_send_discord_notification(
        decision=_decision(),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=False,
        dry_run_notify=True,
        webhook_url="https://example.test/webhook",
    )

    assert result.payload_preview is not None
    assert "example.test" not in str(result.payload_preview)


def test_should_notify_true_and_webhook_calls_sender(monkeypatch):
    called = {"value": False}

    def fake_send(webhook_url, payload):
        called["value"] = True
        assert webhook_url == "https://example.test/webhook"
        assert "Report: reports/btc_jpy_dip_alert_20260429.md" in payload["content"]

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_discord_notification(
        decision=_decision(),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert called["value"] is True
    assert result.sent is True
    assert result.error is None


def test_http_error_returns_safe_failure(monkeypatch):
    def fake_send(*args, **kwargs):
        raise requests.HTTPError("boom")

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_discord_notification(
        decision=_decision(),
        report_path=Path("reports/btc_jpy_dip_alert_20260429.md"),
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert result.sent is False
    assert result.skipped_reason == "discord_http_error"
    assert result.error == "HTTPError"


def test_test_discord_sends_without_should_notify(monkeypatch):
    called = {"value": False}

    def fake_send(webhook_url, payload):
        called["value"] = True
        assert "BTC Alert Test" in payload["content"]

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_test_discord_notification(
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert called["value"] is True
    assert result.sent is True


def test_test_discord_notify_preview_skips_send(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_test_discord_notification(
        requested=True,
        notify_preview=True,
        dry_run_notify=False,
        webhook_url="https://example.test/webhook",
    )

    assert result.sent is False
    assert result.skipped_reason == "notify_preview=true"
    assert result.payload_preview is not None
    assert called["value"] is False


def test_test_discord_dry_run_skips_send(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.discord_notifier.send_discord_webhook", fake_send)
    result = maybe_send_test_discord_notification(
        requested=True,
        notify_preview=False,
        dry_run_notify=True,
        webhook_url="https://example.test/webhook",
    )

    assert result.sent is False
    assert result.skipped_reason == "dry_run_notify=true"
    assert result.payload_preview is not None
    assert called["value"] is False
