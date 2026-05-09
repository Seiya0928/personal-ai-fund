from __future__ import annotations

import json
import smtplib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.alerts.btc_dip_alert import AlertAssessment, next_action_text
from src.alerts.email_notifier import (
    EmailConfig,
    EmailSendResult,
    build_email_payload,
    send_email_via_smtp,
)

DEFAULT_DAILY_SUMMARY_STATE_PATH = Path(__file__).resolve().parents[2] / "state" / "daily_summary_state.json"
DAILY_SUMMARY_SUBJECT = "【BTC Alert Daily】日次サマリー"
JST = ZoneInfo("Asia/Tokyo")


@dataclass
class DailySummaryDecision:
    requested: bool
    should_send: bool
    skipped_reason: Optional[str]
    run_date: str
    state_path: str


def load_daily_summary_state(path: Path = DEFAULT_DAILY_SUMMARY_STATE_PATH) -> dict:
    if not path.exists():
        return {"sent_dates": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    sent_dates = payload.get("sent_dates")
    if not isinstance(sent_dates, list):
        raise ValueError("daily_summary_state.json の形式が不正です。")
    return {"sent_dates": sent_dates}


def save_daily_summary_state(payload: dict, path: Path = DEFAULT_DAILY_SUMMARY_STATE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def mark_daily_summary_sent(run_date: str, path: Path = DEFAULT_DAILY_SUMMARY_STATE_PATH) -> None:
    payload = load_daily_summary_state(path)
    if run_date not in payload["sent_dates"]:
        payload["sent_dates"].append(run_date)
        save_daily_summary_state(payload, path)


def should_send_daily_summary(
    run_started_at_jst: str,
    requested: bool,
    force: bool,
    state_path: Path = DEFAULT_DAILY_SUMMARY_STATE_PATH,
) -> DailySummaryDecision:
    parsed = datetime.fromisoformat(run_started_at_jst)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    parsed = parsed.astimezone(JST)
    run_date = parsed.date().isoformat()
    if not requested and not force:
        return DailySummaryDecision(False, False, "send_daily_summary_not_requested", run_date, str(state_path))
    if force:
        return DailySummaryDecision(True, True, None, run_date, str(state_path))
    if parsed.hour != 22:
        return DailySummaryDecision(True, False, "not_22_jst_run", run_date, str(state_path))
    state = load_daily_summary_state(state_path)
    if run_date in state["sent_dates"]:
        return DailySummaryDecision(True, False, "daily_summary_already_sent", run_date, str(state_path))
    return DailySummaryDecision(True, True, None, run_date, str(state_path))


def _pct_to_buy_candidate_line(assessment: AlertAssessment) -> Optional[float]:
    line = assessment.next_price_lines.get("buy_candidate_line")
    if not line:
        return None
    return round((float(assessment.market.current_price) / float(line) - 1) * 100, 2)


def _pct_to_sma200(assessment: AlertAssessment) -> Optional[float]:
    if not assessment.market.sma200:
        return None
    return round((float(assessment.market.current_price) / float(assessment.market.sma200) - 1) * 100, 2)


def _format_data_age(age_hours: Optional[float]) -> str:
    return "unknown" if age_hours is None else f"{age_hours:.2f}h"


def _today_run_statuses(signals: list[dict], run_date: str) -> dict:
    statuses = {"09:00": "missing", "15:00": "missing", "22:00": "missing"}
    for signal in signals:
        created_at = signal.get("created_at", "")
        if not created_at.startswith(run_date):
            continue
        try:
            parsed = datetime.fromisoformat(created_at).astimezone(JST)
        except ValueError:
            continue
        for slot, hour in (("09:00", 9), ("15:00", 15), ("22:00", 22)):
            if parsed.hour == hour:
                statuses[slot] = signal.get("buy_status") or signal.get("hold_status") or "observed"
    return statuses


def _status_count(signals: list[dict], status: str) -> int:
    return sum(
        1
        for signal in signals
        if (signal.get("hold_status") or signal.get("buy_status")) == status
    )


def _latest_signal_status(signals: list[dict]) -> str:
    if not signals:
        return "None"
    latest = signals[-1]
    created_at = latest.get("created_at") or "unknown"
    status = latest.get("hold_status") or latest.get("buy_status") or "unknown"
    return f"{created_at} / {status}"


def _paper_trade_totals(paper_trade_performance: Optional[list[dict]]) -> dict:
    performance = paper_trade_performance or []
    return {
        "open": sum(int(row.get("open", 0)) for row in performance),
        "closed": sum(int(row.get("closed", 0)) for row in performance),
        "total_pnl_jpy": round(sum(float(row.get("total_pnl_jpy", 0.0)) for row in performance), 2),
    }


def _format_paper_trade_performance(paper_trade_performance: Optional[list[dict]]) -> list[str]:
    lines = []
    for row in paper_trade_performance or []:
        lines.append(
            "Paper trade {rule}: trades={trades}, open={open}, closed={closed}, "
            "win_rate={win_rate:.2f}%, total_pnl_jpy=¥{total_pnl_jpy:,.2f}, "
            "TP={tp}, SL={sl}, TIMEOUT={timeout}".format(
                rule=row.get("rule_id"),
                trades=int(row.get("trades", 0)),
                open=int(row.get("open", 0)),
                closed=int(row.get("closed", 0)),
                win_rate=float(row.get("win_rate", 0.0)),
                total_pnl_jpy=float(row.get("total_pnl_jpy", 0.0)),
                tp=int(row.get("take_profit_count", 0)),
                sl=int(row.get("stop_loss_count", 0)),
                timeout=int(row.get("timeout_count", 0)),
            )
        )
    return lines


def build_daily_summary_body(
    assessment: AlertAssessment,
    run_started_at_jst: str,
    should_notify: bool,
    signal_history: list[dict],
    paper_trade_open_count: int,
    markdown_report_path: Path,
    paper_trade_performance: Optional[list[dict]] = None,
) -> str:
    run_date = datetime.fromisoformat(run_started_at_jst).astimezone(JST).date().isoformat()
    run_statuses = _today_run_statuses(signal_history, run_date)
    today_signals = [signal for signal in signal_history if str(signal.get("created_at", "")).startswith(run_date)]
    trade_totals = _paper_trade_totals(paper_trade_performance)
    distance = _pct_to_buy_candidate_line(assessment)
    sma_distance = _pct_to_sma200(assessment)
    buy_line = assessment.next_price_lines.get("buy_candidate_line")
    lines = [
            "BTC Alert Daily Summary",
            "",
            f"実行時刻: {run_started_at_jst}",
            f"判定に使った価格時刻: {assessment.market.as_of_jst}",
            f"Market data age: {_format_data_age(assessment.market.data_age_hours)}",
            f"Market data stale level: {assessment.market.data_stale_level}",
            f"Market data stale reason: {assessment.market.data_stale_reason}",
            f"Buy status: {assessment.buy_status}",
            f"次アクション: {next_action_text(assessment)}",
            f"Should notify: {should_notify}",
            f"Current price: ¥{assessment.market.current_price:,.0f}",
            f"Prev close / 前日比: ¥{assessment.market.previous_close:,.0f} / {assessment.market.day_change_pct:+.2f}%",
            f"Recent 14d high: ¥{assessment.market.recent_high:,.0f}",
            f"14日高値からの下落率: {assessment.market.drop_from_recent_high_pct:+.2f}%",
            f"SMA200: ¥{assessment.market.sma200:,.0f}",
            f"close > SMA200: {assessment.market.above_sma200}",
            f"SMA200まであと何%: {sma_distance:+.2f}%" if sma_distance is not None else "SMA200まであと何%: None",
            f"Buy candidate line: ¥{buy_line:,.0f}" if buy_line is not None else "Buy candidate line: None",
            f"買い候補ラインまであと何%: {distance:+.2f}%" if distance is not None else "買い候補ラインまであと何%: None",
            "WATCH/SKIP理由: " + "; ".join(assessment.reasons[:5]) if assessment.reasons else "WATCH/SKIP理由: None",
            f"signal_history の直近件数: {len(signal_history)}",
            f"今日のBUY_WATCH件数: {_status_count(today_signals, 'BUY_WATCH')}",
            f"今日のBUY_CANDIDATE件数: {_status_count(today_signals, 'BUY_CANDIDATE')}",
            f"最新の候補/監視状態: {_latest_signal_status(signal_history)}",
            f"paper trade open件数: {paper_trade_open_count}",
            f"paper trade closed件数: {trade_totals['closed']}",
            f"paper trade 損益合計: ¥{trade_totals['total_pnl_jpy']:,.2f}",
            f"今日の09:00実行状況: {run_statuses['09:00']}",
            f"今日の15:00実行状況: {run_statuses['15:00']}",
            f"今日の22:00実行状況: {run_statuses['22:00']}",
            f"Markdown report path: {markdown_report_path}",
            "",
            "実発注は行っていません。",
            "これは投資助言ではなく、自分用の機械的判断補助です。",
    ]
    performance_lines = _format_paper_trade_performance(paper_trade_performance)
    if performance_lines:
        lines.insert(-2, "")
        lines[-2:-2] = performance_lines
    return "\n".join(lines)


def maybe_send_daily_summary_email(
    body: str,
    decision: DailySummaryDecision,
    dry_run_notify: bool,
    config: Optional[EmailConfig] = None,
) -> EmailSendResult:
    preview_payload = {
        "subject": DAILY_SUMMARY_SUBJECT,
        "body": body,
    }
    payload = build_email_payload(DAILY_SUMMARY_SUBJECT, body, config) if config is not None else None
    if not decision.requested:
        return EmailSendResult(False, False, decision.skipped_reason, None, preview_payload if dry_run_notify else None)
    if not decision.should_send:
        return EmailSendResult(True, False, decision.skipped_reason, None, preview_payload if dry_run_notify else None)
    if dry_run_notify:
        return EmailSendResult(True, False, "dry_run_notify=true", None, preview_payload)
    if config is None:
        return EmailSendResult(True, False, "EMAIL_SMTP_CONFIG not set", None, None)
    try:
        send_email_via_smtp(config, payload)
        return EmailSendResult(True, True, None, None, None)
    except smtplib.SMTPException as exc:
        return EmailSendResult(True, False, "email_smtp_error", exc.__class__.__name__, None)


def daily_summary_decision_to_dict(decision: DailySummaryDecision) -> dict:
    return asdict(decision)
