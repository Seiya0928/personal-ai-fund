from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from src.alerts.btc_dip_alert import AlertAssessment, BTC_JPY_ALERT_CONFIG


def default_state_path_for_symbol(symbol: str) -> Path:
    return Path(__file__).resolve().parents[2] / "state" / f"{symbol.lower()}_dip_alert_state.json"


DEFAULT_STATE_PATH = default_state_path_for_symbol(BTC_JPY_ALERT_CONFIG.symbol)


@dataclass
class NotificationState:
    effective_status: Optional[str] = None
    buy_status: Optional[str] = None
    hold_status: Optional[str] = None
    last_notification_at: Optional[str] = None
    last_notification_hash: Optional[str] = None


@dataclass
class NotificationDecision:
    should_notify: bool
    notification_type: str
    title: str
    message: str
    priority: str
    reasons: list[str]
    distance_to_buy_line_pct: Optional[float]
    effective_status: str
    previous_effective_status: Optional[str]
    deduped: bool


def load_notification_state(path: Path = DEFAULT_STATE_PATH) -> NotificationState:
    if not path.exists():
        return NotificationState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return NotificationState(**payload)


def save_notification_state(
    decision: NotificationDecision,
    assessment: AlertAssessment,
    path: Path = DEFAULT_STATE_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = NotificationState(
        effective_status=decision.effective_status,
        buy_status=assessment.buy_status,
        hold_status=assessment.hold_status,
        last_notification_at=assessment.market.as_of_jst if (decision.should_notify or decision.message) else None,
        last_notification_hash=_notification_hash(decision.title, decision.message) if decision.message else None,
    )
    path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def notification_state_to_dict(state: NotificationState) -> dict:
    return asdict(state)


def _effective_status(assessment: AlertAssessment) -> str:
    return assessment.hold_status or assessment.buy_status


def _distance_to_buy_line_pct(assessment: AlertAssessment) -> Optional[float]:
    line = assessment.next_price_lines.get("buy_candidate_line")
    if not line:
        return None
    current = assessment.market.current_price
    return round((current / line - 1) * 100, 2)


def _notification_hash(title: str, message: str) -> str:
    return hashlib.sha256(f"{title}\n{message}".encode("utf-8")).hexdigest()


def _build_status_change_message(previous_status: str, current_status: str, assessment: AlertAssessment) -> tuple[str, str, str]:
    title = "【BTC Alert】判定変化"
    priority = "medium"
    message = (
        f"BTC/JPY の判定が変化しました。\n"
        f"対象：{assessment.display_symbol}\n"
        f"前回：{previous_status}\n"
        f"今回：{current_status}\n"
        f"現在価格：¥{assessment.market.current_price:,.0f}\n"
        "実発注は行いません。手動確認してください。"
    )
    return title, message, priority


def _build_primary_message(
    assessment: AlertAssessment,
    status: str,
    distance_to_buy_line_pct: Optional[float],
) -> tuple[str, str, str, list[str]]:
    reasons: list[str] = []
    if status == "BUY_CANDIDATE":
        return (
            "【BTC Alert】買い候補",
            (
                f"{assessment.display_symbol} が買い条件に一致しました。\n"
                f"現在価格：¥{assessment.market.current_price:,.0f}\n"
                f"買い候補ライン：¥{assessment.next_price_lines['buy_candidate_line']:,.0f}\n"
                f"14日高値からの下落率：{assessment.market.drop_from_recent_high_pct:+.2f}%\n"
                f"SMA200判定：{'OK' if assessment.market.above_sma200 else 'NG'}\n"
                "実発注は行いません。手動確認してください。"
            ),
            "high",
            reasons,
        )
    if status == "BUY_WATCH":
        if distance_to_buy_line_pct is not None and distance_to_buy_line_pct <= 3.0:
            reasons.append(f"買い候補ラインまであと {distance_to_buy_line_pct:.2f}%")
            return (
                "【BTC Alert】買い候補に接近",
                (
                    f"{assessment.display_symbol} が買い候補ラインまであと {distance_to_buy_line_pct:.2f}% です。\n"
                    f"現在価格：¥{assessment.market.current_price:,.0f}\n"
                    f"買い候補ライン：¥{assessment.next_price_lines['buy_candidate_line']:,.0f}\n"
                    "判定：まだ見送り"
                ),
                "medium",
                reasons,
            )
        reasons.append("BUY_WATCH だが買い候補ラインまで 3% 超")
        return "", "", "low", reasons
    if status == "TAKE_PROFIT_CANDIDATE":
        pnl = assessment.position["unrealized_pnl_pct"]
        return (
            "【BTC Alert】利確候補",
            (
                f"{assessment.display_symbol} が利確条件に到達しました。\n"
                f"取得価格：¥{assessment.position['entry_price']:,.0f}\n"
                f"現在価格：¥{assessment.market.current_price:,.0f}\n"
                f"含み益：{pnl:+.2f}%\n"
                "手動確認してください。"
            ),
            "high",
            reasons,
        )
    if status == "STOP_LOSS_CANDIDATE":
        pnl = assessment.position["unrealized_pnl_pct"]
        return (
            "【BTC Alert】損切り候補",
            (
                f"{assessment.display_symbol} が損切り条件に到達しました。\n"
                f"取得価格：¥{assessment.position['entry_price']:,.0f}\n"
                f"現在価格：¥{assessment.market.current_price:,.0f}\n"
                f"含み損：{pnl:+.2f}%\n"
                "手動確認してください。"
            ),
            "high",
            reasons,
        )
    if status == "TIMEOUT_EXIT_CANDIDATE":
        pnl = assessment.position["unrealized_pnl_pct"]
        return (
            "【BTC Alert】保有期限到達",
            (
                "最大保有日数に到達しました。\n"
                f"保有日数：{assessment.position['holding_days']}日\n"
                f"現在損益：{pnl:+.2f}%\n"
                "手動確認してください。"
            ),
            "medium",
            reasons,
        )
    if status == "HOLD":
        reasons.append("HOLD 継続は通常通知しない")
        return "", "", "low", reasons
    reasons.append("BUY_SKIP 継続は通常通知しない")
    return "", "", "low", reasons


def notify_decision(
    assessment: AlertAssessment,
    previous_state: Optional[NotificationState] = None,
    force_notify: bool = False,
) -> NotificationDecision:
    previous_state = previous_state or NotificationState()
    effective_status = _effective_status(assessment)
    previous_effective_status = previous_state.effective_status
    distance_to_buy_line_pct = _distance_to_buy_line_pct(assessment)

    title, message, priority, reasons = _build_primary_message(
        assessment,
        effective_status,
        distance_to_buy_line_pct,
    )
    notification_type = effective_status
    should_notify = bool(message)

    if previous_effective_status and previous_effective_status != effective_status:
        reasons.append(f"前回ステータス {previous_effective_status} から {effective_status} に変化")
        if not message:
            title, message, priority = _build_status_change_message(
                previous_effective_status,
                effective_status,
                assessment,
            )
            notification_type = "STATUS_CHANGED"
            should_notify = True

    deduped = False
    if message:
        current_hash = _notification_hash(title, message)
        if current_hash == previous_state.last_notification_hash and not force_notify:
            reasons.append("前回通知と同一内容のため重複通知を抑止")
            should_notify = False
            deduped = True

    if force_notify and not message:
        title, message, priority = _build_status_change_message(
            previous_effective_status or "UNKNOWN",
            effective_status,
            assessment,
        )
        notification_type = "FORCED_PREVIEW"
        reasons.append("force_notify により通知文面を強制生成")

    return NotificationDecision(
        should_notify=should_notify,
        notification_type=notification_type,
        title=title,
        message=message,
        priority=priority,
        reasons=reasons,
        distance_to_buy_line_pct=distance_to_buy_line_pct,
        effective_status=effective_status,
        previous_effective_status=previous_effective_status,
        deduped=deduped,
    )
