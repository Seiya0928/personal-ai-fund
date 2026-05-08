import smtplib

from src.alerts.email_notifier import (
    EmailConfig,
    maybe_send_email_notification,
    maybe_send_test_email_notification,
    serialize_email_message,
    send_email_via_smtp,
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


def _config():
    return EmailConfig(
        host="smtp.gmail.com",
        port=587,
        username="user@example.com",
        password="app-password",
        from_address="from@example.com",
        to_address="to@example.com",
    )


def test_should_notify_false_skips_email_send(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_send)
    result = maybe_send_email_notification(
        decision=_decision(False),
        report_path=None,
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        config=_config(),
    )

    assert result.sent is False
    assert result.skipped_reason == "should_notify=false"
    assert called["value"] is False


def test_notify_preview_skips_email_send(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_send)
    result = maybe_send_email_notification(
        decision=_decision(True),
        report_path=None,
        requested=True,
        notify_preview=True,
        dry_run_notify=False,
        config=_config(),
    )

    assert result.sent is False
    assert result.skipped_reason == "notify_preview=true"
    assert called["value"] is False


def test_dry_run_skips_email_send(monkeypatch):
    called = {"value": False}

    def fake_send(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_send)
    result = maybe_send_email_notification(
        decision=_decision(True),
        report_path=None,
        requested=True,
        notify_preview=False,
        dry_run_notify=True,
        config=_config(),
    )

    assert result.sent is False
    assert result.skipped_reason == "dry_run_notify=true"
    assert result.payload_preview is not None
    assert called["value"] is False


def test_missing_smtp_config_skips_send():
    import os

    for key in [
        "ALERT_EMAIL_SMTP_HOST",
        "ALERT_EMAIL_SMTP_PORT",
        "ALERT_EMAIL_USERNAME",
        "ALERT_EMAIL_PASSWORD",
        "ALERT_EMAIL_FROM",
        "ALERT_EMAIL_TO",
    ]:
        os.environ.pop(key, None)
    result = maybe_send_email_notification(
        decision=_decision(True),
        report_path=None,
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        config=None,
    )

    assert result.sent is False
    assert result.skipped_reason == "EMAIL_SMTP_CONFIG not set"


def test_test_email_sends_even_without_should_notify(monkeypatch):
    called = {"value": False}

    def fake_send(config, payload):
        called["value"] = True
        assert payload["subject"] == "【BTC Alert Test】Gmail通知テスト"

    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_send)
    result = maybe_send_test_email_notification(
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        config=_config(),
    )

    assert result.sent is True
    assert called["value"] is True


def test_test_email_http_error_is_safe_failure(monkeypatch):
    def fake_send(*args, **kwargs):
        raise smtplib.SMTPException("boom")

    monkeypatch.setattr("src.alerts.email_notifier.send_email_via_smtp", fake_send)
    result = maybe_send_test_email_notification(
        requested=True,
        notify_preview=False,
        dry_run_notify=False,
        config=_config(),
    )

    assert result.sent is False
    assert result.skipped_reason == "email_smtp_error"
    assert result.error == "SMTPException"


def test_serialize_email_message_supports_utf8_subject_and_body():
    payload = {
        "subject": "【BTC Alert Test】Gmail通知テスト",
        "body": "現在価格：¥12,140,122\nBUY_SKIP → BUY_WATCH\nBUY_WATCH ← BUY_SKIP\n買い候補ラインまであと 1.98%",
        "from_address": "from@example.com",
        "to_address": "to@example.com",
    }

    message_bytes = serialize_email_message(payload)

    assert b"Subject:" in message_bytes
    assert b"charset=\"utf-8\"" in message_bytes
    assert "BUY_SKIP → BUY_WATCH".encode("utf-8") in message_bytes
    assert "BUY_WATCH ← BUY_SKIP".encode("utf-8") in message_bytes
    assert "現在価格：¥12,140,122".encode("utf-8") in message_bytes


def test_send_email_via_smtp_uses_bytes_and_not_ascii_string(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.gmail.com"
            assert port == 587
            assert timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    payload = {
        "subject": "【BTC Alert Test】Gmail通知テスト",
        "body": "現在価格：¥12,140,122\nBUY_SKIP → BUY_WATCH\nBUY_WATCH ← BUY_SKIP\n買い候補ラインまであと 1.98%",
        "from_address": "from@example.com",
        "to_address": "to@example.com",
    }

    send_email_via_smtp(_config(), payload)

    assert sent["starttls"] is True
    assert sent["login"] == ("user@example.com", "app-password")
    assert sent["msg"]["From"] == "from@example.com"
    assert sent["msg"]["To"] == "to@example.com"
    assert "BUY_SKIP → BUY_WATCH".encode("utf-8") in sent["msg"].as_bytes()
    assert "BUY_WATCH ← BUY_SKIP".encode("utf-8") in sent["msg"].as_bytes()
