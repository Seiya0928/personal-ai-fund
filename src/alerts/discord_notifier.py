from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import requests

from src.alerts.notification_decision import NotificationDecision


@dataclass
class DiscordSendResult:
    requested: bool
    sent: bool
    skipped_reason: Optional[str]
    error: Optional[str]
    payload_preview: Optional[dict]


def build_discord_payload(
    decision: NotificationDecision,
    report_path: Optional[Path],
) -> dict:
    content = f"{decision.title}\n{decision.message}"
    if report_path is not None:
        content += f"\n\nReport: {report_path}"
    return {"content": content}


def build_test_discord_payload() -> dict:
    return {
        "content": (
            "【BTC Alert Test】\n"
            "Discord通知テストです。\n"
            "このメッセージが届けば、Webhook設定は正常です。\n"
            "実発注は行っていません。"
        )
    }


def send_discord_webhook(webhook_url: str, payload: dict) -> None:
    response = requests.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()


def maybe_send_discord_notification(
    decision: NotificationDecision,
    report_path: Optional[Path],
    requested: bool,
    notify_preview: bool,
    dry_run_notify: bool,
    webhook_url: Optional[str] = None,
) -> DiscordSendResult:
    payload = build_discord_payload(decision, report_path) if decision.title and decision.message else None
    if not requested:
        return DiscordSendResult(False, False, "send_discord_not_requested", None, payload if dry_run_notify else None)
    if notify_preview:
        return DiscordSendResult(True, False, "notify_preview=true", None, payload if dry_run_notify else None)
    if not decision.should_notify:
        return DiscordSendResult(True, False, "should_notify=false", None, payload if dry_run_notify else None)
    if dry_run_notify:
        return DiscordSendResult(True, False, "dry_run_notify=true", None, payload)
    webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return DiscordSendResult(True, False, "DISCORD_WEBHOOK_URL not set", None, None)

    try:
        send_discord_webhook(webhook_url, payload)
        return DiscordSendResult(True, True, None, None, None)
    except requests.RequestException as exc:
        return DiscordSendResult(True, False, "discord_http_error", exc.__class__.__name__, None)


def discord_result_to_dict(result: DiscordSendResult) -> dict:
    return asdict(result)


def maybe_send_test_discord_notification(
    requested: bool,
    notify_preview: bool,
    dry_run_notify: bool,
    webhook_url: Optional[str] = None,
) -> DiscordSendResult:
    payload = build_test_discord_payload()
    if not requested:
        return DiscordSendResult(False, False, "test_discord_not_requested", None, payload if dry_run_notify else None)
    if notify_preview:
        return DiscordSendResult(True, False, "notify_preview=true", None, payload)
    if dry_run_notify:
        return DiscordSendResult(True, False, "dry_run_notify=true", None, payload)
    webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return DiscordSendResult(True, False, "DISCORD_WEBHOOK_URL not set", None, None)
    try:
        send_discord_webhook(webhook_url, payload)
        return DiscordSendResult(True, True, None, None, None)
    except requests.RequestException as exc:
        return DiscordSendResult(True, False, "discord_http_error", exc.__class__.__name__, None)
