from typing import Optional

from src.alerts.btc_dip_alert import AlertAssessment, MarketSnapshot
from src.alerts.notification_decision import NotificationState, notify_decision


def _assessment(
    buy_status: str = "BUY_SKIP",
    hold_status: Optional[str] = None,
    current_price: float = 100.0,
    buy_line: float = 98.0,
    position: Optional[dict] = None,
) -> AlertAssessment:
    return AlertAssessment(
        symbol="BTC_JPY",
        display_symbol="BTC/JPY",
        report_slug="btc_jpy_dip_alert",
        market=MarketSnapshot(
            as_of_utc="2026-04-29T00:00:00+00:00",
            as_of_jst="2026-04-29T09:00:00+09:00",
            current_price=current_price,
            previous_close=101.0,
            day_change_pct=-1.0,
            recent_high=110.0,
            drop_from_recent_high_pct=-9.09,
            sma200=95.0,
            above_sma200=True,
            last_entry_date_jst="2026-04-01",
            days_since_last_entry=28,
            has_position=position is not None,
        ),
        buy_status=buy_status,
        hold_status=hold_status,
        checklists={"buy": {}, "hold": {}},
        reasons=[],
        action_reasons=[],
        next_price_lines={"buy_candidate_line": buy_line},
        position=position,
        positions=[],
        warnings=[],
        reference_backtest={},
        note="note",
    )


def test_buy_watch_notifies_within_three_percent():
    assessment = _assessment(buy_status="BUY_WATCH", current_price=100.0, buy_line=98.0)

    decision = notify_decision(assessment)

    assert decision.should_notify is True
    assert decision.notification_type == "BUY_WATCH"
    assert decision.priority == "medium"
    assert decision.distance_to_buy_line_pct == 2.04


def test_buy_watch_notifies_even_when_watch_reason_is_pullback_not_line_distance():
    assessment = _assessment(buy_status="BUY_WATCH", current_price=105.0, buy_line=98.0)

    decision = notify_decision(assessment)

    assert decision.should_notify is True
    assert decision.priority == "medium"
    assert "まだ買わない理由" in decision.message


def test_buy_watch_is_suppressed_after_same_day_notification():
    assessment = _assessment(buy_status="BUY_WATCH", current_price=100.0, buy_line=98.0)

    decision = notify_decision(
        assessment,
        previous_state=NotificationState(
            effective_status="BUY_WATCH",
            last_notification_at="2026-04-29T09:00:00+09:00",
        ),
    )

    assert decision.should_notify is False
    assert decision.deduped is True
    assert "同日通知済み" in " ".join(decision.reasons)


def test_duplicate_notification_is_suppressed():
    assessment = _assessment(buy_status="BUY_CANDIDATE", current_price=97.0, buy_line=98.0)
    first = notify_decision(assessment)
    previous_state = NotificationState(
        effective_status="BUY_CANDIDATE",
        last_notification_hash="",
    )
    previous_state.last_notification_hash = __import__(
        "hashlib"
    ).sha256(f"{first.title}\n{first.message}".encode("utf-8")).hexdigest()

    second = notify_decision(assessment, previous_state=previous_state)

    assert second.should_notify is False
    assert second.deduped is True


def test_status_change_notifies_even_when_current_status_is_hold():
    assessment = _assessment(
        buy_status="BUY_SKIP",
        hold_status="HOLD",
        position={
            "entry_price": 100.0,
            "entry_date": "2026-04-01",
            "position_size": 0.01,
            "current_price": 101.0,
            "unrealized_pnl_pct": 1.0,
            "holding_days": 28,
            "take_profit_line": 110.0,
            "stop_loss_line": 87.5,
            "max_holding_days": 90.0,
        },
    )

    decision = notify_decision(assessment, previous_state=NotificationState(effective_status="BUY_WATCH"))

    assert decision.should_notify is True
    assert decision.notification_type == "STATUS_CHANGED"
    assert "判定変化" in decision.title
