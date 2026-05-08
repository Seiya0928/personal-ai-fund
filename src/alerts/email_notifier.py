from __future__ import annotations

import os
import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Optional

from src.alerts.notification_decision import NotificationDecision


@dataclass
class EmailConfig:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    to_address: str


@dataclass
class EmailSendResult:
    requested: bool
    sent: bool
    skipped_reason: Optional[str]
    error: Optional[str]
    payload_preview: Optional[dict]


def load_email_config_from_env() -> Optional[EmailConfig]:
    host = os.getenv("ALERT_EMAIL_SMTP_HOST")
    port = os.getenv("ALERT_EMAIL_SMTP_PORT")
    username = os.getenv("ALERT_EMAIL_USERNAME")
    password = os.getenv("ALERT_EMAIL_PASSWORD")
    from_address = os.getenv("ALERT_EMAIL_FROM")
    to_address = os.getenv("ALERT_EMAIL_TO")
    if not all([host, port, username, password, from_address, to_address]):
        return None
    return EmailConfig(
        host=host,
        port=int(port),
        username=username,
        password=password,
        from_address=from_address,
        to_address=to_address,
    )


def build_email_payload(subject: str, body: str, config: EmailConfig) -> dict:
    return {
        "subject": subject,
        "body": body,
        "from_address": config.from_address,
        "to_address": config.to_address,
    }


def build_email_payload_preview(payload: Optional[dict]) -> Optional[dict]:
    if payload is None:
        return None
    return {
        "subject": payload["subject"],
        "body": payload["body"],
    }


def _build_email_message(payload: dict) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["Subject"] = payload["subject"]
    message["From"] = payload["from_address"]
    message["To"] = payload["to_address"]
    message.set_content(payload["body"], charset="utf-8")
    return message


def serialize_email_message(payload: dict) -> bytes:
    return _build_email_message(payload).as_bytes(policy=SMTP)


def send_email_via_smtp(config: EmailConfig, payload: dict) -> None:
    message = _build_email_message(payload)
    with smtplib.SMTP(config.host, config.port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def maybe_send_email_notification(
    decision: NotificationDecision,
    report_path: Optional[Path],
    requested: bool,
    notify_preview: bool,
    dry_run_notify: bool,
    config: Optional[EmailConfig] = None,
) -> EmailSendResult:
    config = config or load_email_config_from_env()
    preview_payload = None
    payload = None
    if decision.title and decision.message:
        body = decision.message
        if report_path is not None:
            body += f"\n\nReport: {report_path}"
        preview_payload = {
            "subject": decision.title,
            "body": body,
        }
        if config is not None:
            payload = build_email_payload(decision.title, body, config)
    if not requested:
        return EmailSendResult(False, False, "send_email_not_requested", None, preview_payload if dry_run_notify else None)
    if notify_preview:
        return EmailSendResult(True, False, "notify_preview=true", None, preview_payload if dry_run_notify else None)
    if not decision.should_notify:
        return EmailSendResult(True, False, "should_notify=false", None, preview_payload if dry_run_notify else None)
    if dry_run_notify:
        return EmailSendResult(True, False, "dry_run_notify=true", None, preview_payload)
    if config is None:
        return EmailSendResult(True, False, "EMAIL_SMTP_CONFIG not set", None, None)
    try:
        send_email_via_smtp(config, payload)
        return EmailSendResult(True, True, None, None, None)
    except smtplib.SMTPException as exc:
        return EmailSendResult(True, False, "email_smtp_error", exc.__class__.__name__, None)


def maybe_send_test_email_notification(
    requested: bool,
    notify_preview: bool,
    dry_run_notify: bool,
    config: Optional[EmailConfig] = None,
) -> EmailSendResult:
    config = config or load_email_config_from_env()
    preview_payload = {
        "subject": "【BTC Alert Test】Gmail通知テスト",
        "body": (
            "Gmail通知テストです。\n"
            "BUY_SKIP → BUY_WATCH\n"
            "BUY_WATCH ← BUY_SKIP\n"
            "現在価格：¥12,140,122\n"
            "このメールが届けば、メール通知設定は正常です。\n"
            "実発注は行っていません。"
        ),
    }
    payload = build_email_payload(
        preview_payload["subject"],
        preview_payload["body"],
        config,
    ) if config is not None else None
    if not requested:
        return EmailSendResult(False, False, "test_email_not_requested", None, preview_payload if dry_run_notify else None)
    if notify_preview:
        return EmailSendResult(True, False, "notify_preview=true", None, preview_payload if dry_run_notify else None)
    if dry_run_notify:
        return EmailSendResult(True, False, "dry_run_notify=true", None, preview_payload)
    if config is None:
        return EmailSendResult(True, False, "EMAIL_SMTP_CONFIG not set", None, None)
    try:
        send_email_via_smtp(config, payload)
        return EmailSendResult(True, True, None, None, None)
    except smtplib.SMTPException as exc:
        return EmailSendResult(True, False, "email_smtp_error", exc.__class__.__name__, None)


def email_result_to_dict(result: EmailSendResult) -> dict:
    return asdict(result)
