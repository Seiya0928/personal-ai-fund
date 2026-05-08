"""BTC急落買いの判断補助アラートを出力する。"""
import argparse
import json
import os
import sys
import traceback
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.btc_dip_alert import (
    AlertAssessment,
    BTC_JPY_ALERT_CONFIG,
    BTC_BACKTEST_REFERENCE,
    MarketSnapshot,
    PositionInput,
    assessment_to_dict,
    default_report_path,
    load_default_assessment,
    render_cli,
    render_markdown,
    save_markdown_report_for_config,
)
from src.alerts.discord_notifier import (
    discord_result_to_dict,
    maybe_send_discord_notification,
    maybe_send_test_discord_notification,
)
from src.alerts.daily_summary import (
    DEFAULT_DAILY_SUMMARY_STATE_PATH,
    build_daily_summary_body,
    daily_summary_decision_to_dict,
    mark_daily_summary_sent,
    maybe_send_daily_summary_email,
    should_send_daily_summary,
)
from src.alerts.email_notifier import (
    EmailConfig,
    email_result_to_dict,
    load_email_config_from_env,
    maybe_send_email_notification,
    maybe_send_test_email_notification,
)
from src.alerts.manual_positions import (
    DEFAULT_MANUAL_POSITIONS_PATH,
    parse_position_input,
    select_active_position,
)
from src.alerts.order_proposal import (
    DEFAULT_ORDER_PROPOSALS_PATH,
    format_order_proposal_for_message,
    generate_order_proposal,
    save_order_proposal,
)
from src.alerts.paper_trades import (
    DEFAULT_PAPER_TRADES_PATH,
    create_paper_trades_from_buy_proposal,
    list_paper_trades,
    save_paper_trade_records,
    summarize_paper_performance,
    update_open_paper_trades,
)
from src.alerts.signal_history import (
    DEFAULT_SIGNAL_HISTORY_PATH,
    build_signal_record,
    list_signal_history,
    save_signal_record,
)
from src.alerts.notification_decision import (
    default_state_path_for_symbol,
    load_notification_state,
    notify_decision,
    notification_state_to_dict,
    save_notification_state,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = BTC_JPY_ALERT_CONFIG
JST = ZoneInfo("Asia/Tokyo")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{CONFIG.display_symbol} 急落買いの判断補助アラート")
    parser.add_argument("--entry-price", type=float)
    parser.add_argument("--entry-date", type=str)
    parser.add_argument("--position-size", type=float)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--notify-preview", action="store_true")
    parser.add_argument("--state-path", type=Path, default=default_state_path_for_symbol(CONFIG.symbol))
    parser.add_argument("--manual-positions-path", type=Path, default=DEFAULT_MANUAL_POSITIONS_PATH)
    parser.add_argument("--order-proposals-path", type=Path, default=DEFAULT_ORDER_PROPOSALS_PATH)
    parser.add_argument("--signal-history-path", type=Path, default=DEFAULT_SIGNAL_HISTORY_PATH)
    parser.add_argument("--paper-trades-path", type=Path, default=DEFAULT_PAPER_TRADES_PATH)
    parser.add_argument("--daily-summary-state-path", type=Path, default=DEFAULT_DAILY_SUMMARY_STATE_PATH)
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--send-discord", action="store_true")
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--send-daily-summary", action="store_true")
    parser.add_argument("--force-daily-summary", action="store_true")
    parser.add_argument("--dry-run-notify", action="store_true")
    parser.add_argument("--test-discord", action="store_true")
    parser.add_argument("--test-email", action="store_true")
    parser.add_argument("--proposal-jpy", type=float, default=1000.0)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def build_position(args: argparse.Namespace) -> Optional[PositionInput]:
    if args.entry_price is None and args.entry_date is None and args.position_size is None:
        return None
    if None in (args.entry_price, args.entry_date, args.position_size):
        raise ValueError("保有中入力を使う場合は --entry-price --entry-date --position-size をすべて指定してください。")
    return PositionInput(
        entry_price=float(args.entry_price),
        entry_date=date.fromisoformat(args.entry_date),
        position_size=float(args.position_size),
    )


def build_test_assessment() -> AlertAssessment:
    now = date.today().isoformat()
    snapshot = MarketSnapshot(
        as_of_utc=f"{now}T00:00:00+00:00",
        as_of_jst=f"{now}T09:00:00+09:00",
        current_price=0.0,
        previous_close=0.0,
        day_change_pct=0.0,
        recent_high=0.0,
        drop_from_recent_high_pct=0.0,
        sma200=0.0,
        above_sma200=False,
        last_entry_date_jst=None,
        days_since_last_entry=None,
        has_position=False,
    )
    return AlertAssessment(
        symbol=CONFIG.symbol,
        display_symbol=CONFIG.display_symbol,
        report_slug=CONFIG.report_slug,
        market=snapshot,
        buy_status="TEST_MODE",
        hold_status=None,
        checklists={"buy": {}, "hold": {}},
        reasons=["test_discord mode"],
        action_reasons=[],
        next_price_lines={},
        position=None,
        positions=[],
        warnings=[],
        reference_backtest=BTC_BACKTEST_REFERENCE,
        note="これは投資助言ではなく、自分用の機械的判断補助です。実発注は行わず、GMOサポート回答前は発注系を再開しません。",
        test_notification=True,
    )


def main() -> int:
    args = parse_args()
    run_started_at_jst = datetime.now(JST).replace(microsecond=0).isoformat()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    email_config = load_email_config_from_env()
    try:
        if args.test_discord:
            assessment = build_test_assessment()
            test_result = maybe_send_test_discord_notification(
                requested=True,
                notify_preview=args.notify_preview,
                dry_run_notify=args.dry_run_notify,
                webhook_url=webhook_url,
            )
            assessment.test_discord_result = discord_result_to_dict(test_result)
            if args.json_output:
                print(json.dumps(assessment_to_dict(assessment), ensure_ascii=False, indent=2))
            else:
                print(render_cli(assessment))
            if args.notify_preview:
                print("")
                print("Test Discord preview")
                print("requested: True")
                print(f"notify_preview: {args.notify_preview}")
            if args.dry_run_notify and test_result.payload_preview:
                print("")
                print("Discord payload preview")
                print(json.dumps(test_result.payload_preview, ensure_ascii=False, indent=2))
            if test_result.skipped_reason == "DISCORD_WEBHOOK_URL not set":
                print("DISCORD_WEBHOOK_URL not set")
            elif test_result.sent:
                print("Discord test notification sent")
            elif test_result.error:
                print(f"Discord test notification failed: {test_result.error}")
            else:
                print(f"Discord test notification skipped: {test_result.skipped_reason}")
            if args.markdown:
                path = save_markdown_report_for_config(render_markdown(assessment), ROOT, CONFIG)
                print(f"Markdown report saved: {path}")
            return 0
        if args.test_email:
            assessment = build_test_assessment()
            test_result = maybe_send_test_email_notification(
                requested=True,
                notify_preview=args.notify_preview,
                dry_run_notify=args.dry_run_notify,
                config=email_config,
            )
            assessment.test_email_result = email_result_to_dict(test_result)
            if args.json_output:
                print(json.dumps(assessment_to_dict(assessment), ensure_ascii=False, indent=2))
            else:
                print(render_cli(assessment))
            if args.notify_preview:
                print("")
                print("Test Email preview")
                print("requested: True")
                print(f"notify_preview: {args.notify_preview}")
            if args.dry_run_notify and test_result.payload_preview:
                print("")
                print("Email payload preview")
                print(json.dumps(test_result.payload_preview, ensure_ascii=False, indent=2))
            if test_result.skipped_reason == "EMAIL_SMTP_CONFIG not set":
                print("EMAIL_SMTP_CONFIG not set")
            elif test_result.sent:
                print("Email test notification sent")
            elif test_result.error:
                print(f"Email test notification failed: {test_result.error}")
            else:
                print(f"Email test notification skipped: {test_result.skipped_reason}")
            if args.markdown:
                path = save_markdown_report_for_config(render_markdown(assessment), ROOT, CONFIG)
                print(f"Markdown report saved: {path}")
            return 0

        position = build_position(args)
        manual_position, manual_warnings, manual_positions = select_active_position(
            CONFIG.symbol,
            args.manual_positions_path,
        )
        if manual_position is not None:
            if position is not None:
                manual_warnings.append("CLIで指定された保有情報は無視し、manual_positions の open position を優先しました。")
            position = parse_position_input(manual_position)
        assessment = load_default_assessment(position, CONFIG)
        assessment.positions = manual_positions
        assessment.warnings = manual_warnings
        if manual_position is not None and assessment.position is not None:
            assessment.position["id"] = manual_position.get("id")
            assessment.position["note"] = manual_position.get("note")
        previous_state = load_notification_state(args.state_path)
        decision = notify_decision(assessment, previous_state=previous_state, force_notify=args.force_notify)
        proposal_source_status = None
        if assessment.hold_status in {"TAKE_PROFIT_CANDIDATE", "STOP_LOSS_CANDIDATE", "TIMEOUT_EXIT_CANDIDATE"}:
            proposal_source_status = assessment.hold_status
        elif assessment.buy_status == "BUY_CANDIDATE":
            proposal_source_status = "BUY_CANDIDATE"
        elif assessment.buy_status == "BUY_WATCH" and decision.should_notify:
            proposal_source_status = "BUY_WATCH"

        proposal, proposal_reason = generate_order_proposal(
            assessment,
            proposal_jpy=args.proposal_jpy,
            source_status=proposal_source_status,
        )
        assessment.order_proposal = proposal
        if proposal is not None:
            stored_proposal, saved = save_order_proposal(proposal, args.order_proposals_path)
            assessment.order_proposal = stored_proposal
            assessment.order_proposal_state = {
                "saved": saved,
                "reason": "saved" if saved else "duplicate_not_saved",
                "path": str(args.order_proposals_path),
            }
        else:
            assessment.order_proposal_state = {
                "saved": False,
                "reason": proposal_reason,
                "path": str(args.order_proposals_path),
            }

        paper_note = "\n- この注文案はpaper tradeにも記録されます\n- 実発注は行っていません\n- 成績検証用です"
        if proposal is not None and decision.message:
            decision = replace(
                decision,
                message=decision.message + "\n" + format_order_proposal_for_message(proposal),
            )

        report_path = default_report_path(ROOT, CONFIG)
        report_path_for_message = report_path.relative_to(ROOT)
        discord_result = maybe_send_discord_notification(
            decision=decision,
            report_path=report_path_for_message,
            requested=(args.send_discord or args.dry_run_notify),
            notify_preview=args.notify_preview,
            dry_run_notify=args.dry_run_notify,
            webhook_url=webhook_url,
        )
        email_decision = decision
        if proposal is not None and decision.message:
            email_decision = replace(decision, message=decision.message + paper_note)
        email_result = maybe_send_email_notification(
            decision=email_decision,
            report_path=report_path_for_message,
            requested=(args.send_email or args.dry_run_notify),
            notify_preview=args.notify_preview,
            dry_run_notify=args.dry_run_notify,
            config=email_config,
        )
        assessment.notification = {
            "should_notify": decision.should_notify,
            "notification_type": decision.notification_type,
            "title": decision.title,
            "message": decision.message,
            "priority": decision.priority,
            "reasons": decision.reasons,
            "distance_to_buy_line_pct": decision.distance_to_buy_line_pct,
            "effective_status": decision.effective_status,
            "previous_effective_status": decision.previous_effective_status,
            "deduped": decision.deduped,
            "state_path": str(args.state_path),
            "previous_state": notification_state_to_dict(previous_state),
        }
        signal_record = build_signal_record(assessment, created_at=run_started_at_jst)
        stored_signal, signal_saved = save_signal_record(signal_record, args.signal_history_path)
        assessment.signal_history_state = {
            "signal_id": stored_signal["signal_id"],
            "saved": signal_saved,
            "reason": "saved" if signal_saved else "duplicate_not_saved",
            "path": str(args.signal_history_path),
        }
        update_open_paper_trades(assessment.market.current_price, assessment.market.as_of_jst, args.paper_trades_path)
        created_records, paper_reason = create_paper_trades_from_buy_proposal(stored_signal, proposal)
        stored_records, created_count = save_paper_trade_records(created_records, args.paper_trades_path)
        paper_performance = summarize_paper_performance(args.paper_trades_path)
        all_open_count = len(list_paper_trades(args.paper_trades_path, status="open"))
        assessment.paper_trade_state = {
            "created_count": created_count,
            "reason": paper_reason,
            "path": str(args.paper_trades_path),
            "open_count": all_open_count,
            "created_trade_ids": [record["paper_trade_id"] for record in stored_records],
        }
        assessment.paper_trade_performance = paper_performance
        assessment.discord = discord_result_to_dict(discord_result)
        assessment.email = email_result_to_dict(email_result)
        signals = list_signal_history(args.signal_history_path)
        daily_summary_decision = should_send_daily_summary(
            run_started_at_jst,
            requested=getattr(args, "send_daily_summary", False),
            force=getattr(args, "force_daily_summary", False),
            state_path=getattr(args, "daily_summary_state_path", DEFAULT_DAILY_SUMMARY_STATE_PATH),
        )
        daily_summary_body = build_daily_summary_body(
            assessment=assessment,
            run_started_at_jst=run_started_at_jst,
            should_notify=decision.should_notify,
            signal_history=signals[-20:],
            paper_trade_open_count=all_open_count,
            markdown_report_path=report_path,
        )
        daily_summary_result = maybe_send_daily_summary_email(
            daily_summary_body,
            daily_summary_decision,
            dry_run_notify=args.dry_run_notify,
            config=email_config,
        )
        if daily_summary_result.sent:
            mark_daily_summary_sent(
                daily_summary_decision.run_date,
                getattr(args, "daily_summary_state_path", DEFAULT_DAILY_SUMMARY_STATE_PATH),
            )

        if args.json_output:
            payload = assessment_to_dict(assessment)
            payload["daily_summary"] = {
                "decision": daily_summary_decision_to_dict(daily_summary_decision),
                "email": email_result_to_dict(daily_summary_result),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_cli(assessment))
        if args.notify_preview:
            print("")
            print("Notify preview")
            print(f"should_notify: {decision.should_notify}")
            print(f"notification_type: {decision.notification_type}")
            print(f"priority: {decision.priority}")
            print(f"state_path: {args.state_path}")
            if decision.reasons:
                print("reasons:")
                for reason in decision.reasons:
                    print(f"- {reason}")
            if decision.title:
                print("title:")
                print(decision.title)
            if decision.message:
                print("message:")
                print(decision.message)
        if args.dry_run_notify and discord_result.payload_preview:
            print("")
            print("Discord payload preview")
            print(json.dumps(discord_result.payload_preview, ensure_ascii=False, indent=2))
        if args.send_discord or args.dry_run_notify:
            if discord_result.skipped_reason == "DISCORD_WEBHOOK_URL not set":
                print("DISCORD_WEBHOOK_URL not set")
            elif discord_result.sent:
                print("Discord notification sent")
            elif discord_result.error:
                print(f"Discord notification failed: {discord_result.error}")
            else:
                print(f"Discord notification skipped: {discord_result.skipped_reason}")
        if args.dry_run_notify and email_result.payload_preview:
            print("")
            print("Email payload preview")
            print(json.dumps(email_result.payload_preview, ensure_ascii=False, indent=2))
        if args.send_email or args.dry_run_notify:
            if email_result.skipped_reason == "EMAIL_SMTP_CONFIG not set":
                print("EMAIL_SMTP_CONFIG not set")
            elif email_result.sent:
                print("Email notification sent")
            elif email_result.error:
                print(f"Email notification failed: {email_result.error}")
            else:
                print(f"Email notification skipped: {email_result.skipped_reason}")
        if args.dry_run_notify and daily_summary_result.payload_preview:
            print("")
            print("Daily summary payload preview")
            print(json.dumps(daily_summary_result.payload_preview, ensure_ascii=False, indent=2))
        if getattr(args, "send_daily_summary", False) or getattr(args, "force_daily_summary", False) or args.dry_run_notify:
            print(f"Daily summary requested: {daily_summary_result.requested}")
            print(f"Daily summary sent: {daily_summary_result.sent}")
            print(f"Daily summary skipped reason: {daily_summary_result.skipped_reason}")
            print(f"Daily summary state path: {daily_summary_decision.state_path}")

        if args.markdown:
            path = save_markdown_report_for_config(render_markdown(assessment), ROOT, CONFIG)
            print(f"Markdown report saved: {path}")

        save_notification_state(decision, assessment, args.state_path)
        return 0
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        else:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
