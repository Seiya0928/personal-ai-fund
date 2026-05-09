from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.storage.sqlite_store import SQLiteStore

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_INTERVAL = "1day"
MARKET_DATA_WARNING_AFTER = timedelta(hours=6)
MARKET_DATA_INVALID_AFTER = timedelta(hours=24)
BASELINE_PARAMS = {
    "dip_threshold_pct": 3.0,
    "watch_distance_to_buy_line_pct": 4.0,
    "watch_min_drop_from_recent_high_pct": 2.0,
    "watch_day_drop_progress_ratio": 0.5,
    "recent_high_lookback_days": 14,
    "trend_filter": True,
    "volatility_filter": "none",
    "min_days_between_entries": 7.0,
    "take_profit_pct": 10.0,
    "stop_loss_pct": 12.5,
    "max_holding_days": 90.0,
    "max_position_ratio": 0.15,
    "cooldown_days": 14.0,
}
BTC_BACKTEST_REFERENCE = {
    "annualized_return_pct": 4.95,
    "max_drawdown_pct": 3.58,
    "portfolio_unrealized_drawdown_pct": 1.81,
    "trades": 516,
    "stop_loss_count": 14,
    "average_holding_days": 27.0,
}


@dataclass(frozen=True)
class AlertConfig:
    symbol: str
    display_symbol: str
    interval: str
    report_slug: str
    params: dict
    reference_backtest: dict


BTC_JPY_ALERT_CONFIG = AlertConfig(
    symbol="BTC_JPY",
    display_symbol="BTC/JPY",
    interval=DEFAULT_INTERVAL,
    report_slug="btc_jpy_dip_alert",
    params=BASELINE_PARAMS,
    reference_backtest=BTC_BACKTEST_REFERENCE,
)


@dataclass
class PositionInput:
    entry_price: float
    entry_date: date
    position_size: float
    position_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class MarketSnapshot:
    as_of_utc: str
    as_of_jst: str
    current_price: float
    previous_close: float
    day_change_pct: float
    recent_high: float
    drop_from_recent_high_pct: float
    sma200: float
    above_sma200: bool
    last_entry_date_jst: Optional[str]
    days_since_last_entry: Optional[int]
    has_position: bool
    data_age_hours: Optional[float] = None
    data_stale_level: str = "fresh"
    data_stale_reason: Optional[str] = None


@dataclass
class AlertAssessment:
    symbol: str
    display_symbol: str
    report_slug: str
    market: MarketSnapshot
    buy_status: str
    hold_status: Optional[str]
    checklists: dict
    reasons: list[str]
    action_reasons: list[str]
    next_price_lines: dict
    position: Optional[dict]
    positions: list[dict]
    warnings: list[str]
    reference_backtest: dict
    note: str
    order_proposal: Optional[dict] = None
    order_proposal_state: Optional[dict] = None
    signal_history_state: Optional[dict] = None
    paper_trade_state: Optional[dict] = None
    paper_trade_performance: Optional[list[dict]] = None
    notification: Optional[dict] = None
    discord: Optional[dict] = None
    email: Optional[dict] = None
    test_notification: bool = False
    test_discord_result: Optional[dict] = None
    test_email_result: Optional[dict] = None


def _parse_rows(rows: list[dict]) -> pd.DataFrame:
    if len(rows) < 200:
        raise ValueError("日足データが不足しています。SMA200 計算には 200 件以上必要です。")
    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _latest_entry_info(df: pd.DataFrame, params: dict) -> tuple[Optional[pd.Timestamp], Optional[int]]:
    history = df.copy()
    history["pct_change"] = history["close"].pct_change() * 100
    history["sma200"] = history["close"].rolling(200, min_periods=200).mean()
    history["signal"] = (
        (history["pct_change"] <= -params["dip_threshold_pct"])
        & (history["close"] > history["sma200"])
    )
    matches = history.loc[history["signal"], "timestamp"]
    if matches.empty:
        return None, None
    last_entry = matches.iloc[-1]
    now_jst = df.iloc[-1]["timestamp"].tz_convert(JST).date()
    last_jst = last_entry.tz_convert(JST).date()
    return last_entry, (now_jst - last_jst).days


def build_market_snapshot(
    rows: list[dict],
    latest_ticker: Optional[dict],
    has_position: bool,
    params: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> MarketSnapshot:
    params = params or BASELINE_PARAMS
    df = _parse_rows(rows)
    current_bar = df.iloc[-1]
    prev_bar = df.iloc[-2]
    current_price = float(latest_ticker["last"]) if latest_ticker and latest_ticker.get("last") else float(current_bar["close"])
    previous_close = float(prev_bar["close"])
    day_change_pct = (current_price / previous_close - 1) * 100
    lookback = params["recent_high_lookback_days"]
    recent_high = float(df["high"].tail(lookback).max())
    drop_from_recent_high_pct = (current_price / recent_high - 1) * 100
    sma200 = float(df["close"].tail(200).mean())
    last_entry_ts, days_since_last_entry = _latest_entry_info(df, params)
    as_of_utc = current_bar["timestamp"]
    if latest_ticker and latest_ticker.get("timestamp"):
        try:
            as_of_utc = pd.to_datetime(latest_ticker["timestamp"], utc=True)
        except Exception:
            pass
    age_hours = None
    stale_level = "fresh"
    stale_reason = None
    if now is not None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        now_utc = now.astimezone(ZoneInfo("UTC"))
        data_age = now_utc - as_of_utc.to_pydatetime()
        age_hours = max(data_age.total_seconds() / 3600, 0.0)
        if data_age >= MARKET_DATA_INVALID_AFTER:
            stale_level = "invalid"
            stale_reason = f"market data is older than 24h: age={age_hours:.1f}h"
        elif data_age >= MARKET_DATA_WARNING_AFTER:
            stale_level = "warning"
            stale_reason = f"market data is older than 6h: age={age_hours:.1f}h"
    return MarketSnapshot(
        as_of_utc=as_of_utc.isoformat(),
        as_of_jst=as_of_utc.tz_convert(JST).isoformat(),
        current_price=round(current_price, 0),
        previous_close=round(previous_close, 0),
        day_change_pct=round(day_change_pct, 2),
        recent_high=round(recent_high, 0),
        drop_from_recent_high_pct=round(drop_from_recent_high_pct, 2),
        sma200=round(sma200, 0),
        above_sma200=current_price > sma200,
        last_entry_date_jst=last_entry_ts.tz_convert(JST).date().isoformat() if last_entry_ts is not None else None,
        days_since_last_entry=days_since_last_entry,
        has_position=has_position,
        data_age_hours=round(age_hours, 2) if age_hours is not None else None,
        data_stale_level=stale_level,
        data_stale_reason=stale_reason,
    )


def evaluate_buy(snapshot: MarketSnapshot, params: Optional[dict] = None) -> tuple[str, dict, list[str], dict]:
    params = params or BASELINE_PARAMS
    buy_line = snapshot.previous_close * (1 - params["dip_threshold_pct"] / 100)
    distance_to_buy_line_pct = round((snapshot.current_price / buy_line - 1) * 100, 2) if buy_line else None
    distance_to_sma200 = distance_to_sma200_pct(snapshot)
    watch_day_drop_threshold = -params["dip_threshold_pct"] * params.get("watch_day_drop_progress_ratio", 0.5)
    checks = {
        "dip_trigger": snapshot.day_change_pct <= -params["dip_threshold_pct"],
        "trend_ok": (not params["trend_filter"]) or snapshot.above_sma200,
        "entry_gap_ok": snapshot.days_since_last_entry is None or snapshot.days_since_last_entry >= params["min_days_between_entries"],
        "cooldown_ok": snapshot.days_since_last_entry is None or snapshot.days_since_last_entry >= params["cooldown_days"],
        "recent_high_filter_ok": snapshot.drop_from_recent_high_pct <= -params.get("min_drop_from_recent_high_pct", 0.0),
        "no_position": not snapshot.has_position,
        "watch_buy_line_near": (
            distance_to_buy_line_pct is not None
            and 0 <= distance_to_buy_line_pct <= params.get("watch_distance_to_buy_line_pct", 4.0)
        ),
        "watch_recent_high_pullback": (
            snapshot.drop_from_recent_high_pct <= -params.get("watch_min_drop_from_recent_high_pct", 2.0)
        ),
        "watch_day_drop_progress": snapshot.day_change_pct <= watch_day_drop_threshold,
        "trend_filter_blocking": params["trend_filter"] and not snapshot.above_sma200,
    }
    reasons = []
    if not checks["dip_trigger"]:
        reasons.append(f"前日比が {snapshot.day_change_pct:+.2f}% で、買い条件 { -params['dip_threshold_pct']:.2f}% 以下を未達")
    if not checks["trend_ok"]:
        reasons.append("SMA200 を下回っており、長期上昇トレンド条件を未達")
    if not checks["entry_gap_ok"]:
        reasons.append(f"前回エントリーから {snapshot.days_since_last_entry} 日で、最小間隔 {params['min_days_between_entries']} 日を未達")
    if not checks["cooldown_ok"]:
        reasons.append(f"前回エントリーから {snapshot.days_since_last_entry} 日で、cooldown {params['cooldown_days']} 日を未達")
    if not checks["no_position"]:
        reasons.append("保有中のため新規買い判定を停止")

    candidate_checks = [
        checks["dip_trigger"],
        checks["trend_ok"],
        checks["entry_gap_ok"],
        checks["cooldown_ok"],
        checks["recent_high_filter_ok"],
        checks["no_position"],
    ]
    watch_triggers = [
        checks["watch_buy_line_near"],
        checks["watch_recent_high_pullback"],
        checks["watch_day_drop_progress"],
        checks["dip_trigger"] and not checks["trend_ok"],
    ]
    if all(candidate_checks):
        status = "BUY_CANDIDATE"
    elif checks["no_position"] and any(watch_triggers):
        status = "BUY_WATCH"
        if checks["watch_buy_line_near"]:
            reasons.append(f"買い候補ラインまで {distance_to_buy_line_pct:+.2f}% で、監視距離 {params.get('watch_distance_to_buy_line_pct', 4.0):.2f}% 以内")
        if checks["watch_recent_high_pullback"]:
            reasons.append(f"直近14日高値から {snapshot.drop_from_recent_high_pct:+.2f}% 下落し、監視水準に到達")
        if checks["watch_day_drop_progress"]:
            reasons.append(f"前日比 {snapshot.day_change_pct:+.2f}% で、急落条件に向けた下落進行を検知")
        if checks["trend_filter_blocking"]:
            reasons.append("trend_filter は NG だが、買い候補接近の監視対象として記録")
    else:
        status = "BUY_SKIP"

    return status, checks, reasons, {
        "buy_candidate_line": round(buy_line, 0),
        "distance_to_buy_line_pct": distance_to_buy_line_pct,
        "distance_to_sma200_pct": distance_to_sma200,
    }


def evaluate_position(snapshot: MarketSnapshot, position: Optional[PositionInput], params: Optional[dict] = None) -> tuple[Optional[str], dict, list[str], Optional[dict]]:
    params = params or BASELINE_PARAMS
    if position is None:
        return None, {}, [], None

    as_of_date = datetime.fromisoformat(snapshot.as_of_jst).date()
    holding_days = (as_of_date - position.entry_date).days
    pnl_pct = (snapshot.current_price / position.entry_price - 1) * 100
    pnl_jpy = (snapshot.current_price - position.entry_price) * position.position_size
    take_profit_line = position.entry_price * (1 + params["take_profit_pct"] / 100)
    stop_loss_line = position.entry_price * (1 - params["stop_loss_pct"] / 100)
    max_holding_deadline = position.entry_date.fromordinal(position.entry_date.toordinal() + int(params["max_holding_days"]))
    checks = {
        "take_profit_hit": pnl_pct >= params["take_profit_pct"],
        "stop_loss_hit": pnl_pct <= -params["stop_loss_pct"],
        "timeout_hit": holding_days >= params["max_holding_days"],
    }
    action_reasons = []
    if checks["take_profit_hit"]:
        status = "TAKE_PROFIT_CANDIDATE"
        action_reasons.append(f"含み損益率 {pnl_pct:+.2f}% が利確ライン +{params['take_profit_pct']:.2f}% を到達")
    elif checks["stop_loss_hit"]:
        status = "STOP_LOSS_CANDIDATE"
        action_reasons.append(f"含み損益率 {pnl_pct:+.2f}% が損切りライン -{params['stop_loss_pct']:.2f}% を下回った")
    elif checks["timeout_hit"]:
        status = "TIMEOUT_EXIT_CANDIDATE"
        action_reasons.append(f"保有日数 {holding_days} 日が最大保有 {params['max_holding_days']} 日を超過")
    else:
        status = "HOLD"
        action_reasons.append("利確・損切り・時間切れの条件に未到達")

    return status, checks, action_reasons, {
        "id": position.position_id,
        "entry_price": position.entry_price,
        "entry_date": position.entry_date.isoformat(),
        "position_size": position.position_size,
        "note": position.note,
        "current_price": snapshot.current_price,
        "unrealized_pnl_pct": round(pnl_pct, 2),
        "unrealized_pnl_jpy": round(pnl_jpy, 2),
        "holding_days": holding_days,
        "take_profit_line": round(take_profit_line, 0),
        "stop_loss_line": round(stop_loss_line, 0),
        "max_holding_days": params["max_holding_days"],
        "max_holding_deadline": max_holding_deadline.isoformat(),
    }


def build_alert_assessment(
    rows: list[dict],
    latest_ticker: Optional[dict],
    position: Optional[PositionInput],
    config: Optional[AlertConfig] = None,
    positions: Optional[list[dict]] = None,
    warnings: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> AlertAssessment:
    config = config or BTC_JPY_ALERT_CONFIG
    params = config.params
    snapshot = build_market_snapshot(rows, latest_ticker, position is not None, params, now=now)
    buy_status, buy_checks, reasons, next_lines = evaluate_buy(snapshot, params)
    hold_status, hold_checks, action_reasons, position_summary = evaluate_position(snapshot, position, params)
    if position_summary is not None:
        next_lines["take_profit_line"] = position_summary["take_profit_line"]
        next_lines["stop_loss_line"] = position_summary["stop_loss_line"]
    stale_warnings = []
    if snapshot.data_stale_reason:
        stale_warnings.append(snapshot.data_stale_reason)
    if snapshot.data_stale_level == "invalid":
        buy_status = "BUY_SKIP"
        hold_status = None if position_summary is None else "HOLD"
        buy_checks["fresh_market_data"] = False
        reasons.insert(0, "市場データが24時間以上古いため、売買候補判定を無効化")
        action_reasons.append("市場データが24時間以上古いため、保有アクション判定を無効化")
    else:
        buy_checks["fresh_market_data"] = True
    return AlertAssessment(
        symbol=config.symbol,
        display_symbol=config.display_symbol,
        report_slug=config.report_slug,
        market=snapshot,
        buy_status=buy_status,
        hold_status=hold_status,
        checklists={"buy": buy_checks, "hold": hold_checks},
        reasons=reasons,
        action_reasons=action_reasons,
        next_price_lines=next_lines,
        position=position_summary,
        positions=positions or [],
        warnings=[*(warnings or []), *stale_warnings],
        reference_backtest=config.reference_backtest,
        note="これは投資助言ではなく、自分用の機械的判断補助です。実発注は行わず、GMOサポート回答前は発注系を再開しません。",
    )


def assessment_to_dict(assessment: AlertAssessment) -> dict:
    payload = asdict(assessment)
    payload["discord_send_result"] = payload.get("discord")
    payload["email_send_result"] = payload.get("email")
    return payload


def _format_data_age(age_hours: Optional[float]) -> str:
    return "unknown" if age_hours is None else f"{age_hours:.2f}h"


def distance_to_buy_candidate_line_pct(assessment: AlertAssessment) -> Optional[float]:
    line = assessment.next_price_lines.get("buy_candidate_line")
    if not line:
        return None
    return round((float(assessment.market.current_price) / float(line) - 1) * 100, 2)


def distance_to_sma200_pct(snapshot: MarketSnapshot) -> Optional[float]:
    if not snapshot.sma200:
        return None
    return round((float(snapshot.current_price) / float(snapshot.sma200) - 1) * 100, 2)


def next_action_text(assessment: AlertAssessment) -> str:
    if assessment.market.data_stale_level == "invalid":
        return "市場データが古いため判断無効。fetch/health checkを確認。"
    status = assessment.hold_status or assessment.buy_status
    actions = {
        "BUY_SKIP": "何もしない。記録のみ。",
        "BUY_WATCH": "監視のみ。手動購入しない。注文案は作らない。",
        "BUY_CANDIDATE": "order proposalを確認し、必要ならdry-run注文記録を作る。実注文はまだしない。",
        "TAKE_PROFIT_CANDIDATE": "SELL proposalを確認し、dry-run決済記録を作る。実注文はまだしない。",
        "STOP_LOSS_CANDIDATE": "SELL proposalを確認し、損切りリハーサルを優先する。実注文はまだしない。",
        "TIMEOUT_EXIT_CANDIDATE": "保有期限切れ候補としてSELL proposalを確認する。実注文はまだしない。",
    }
    return actions.get(status, "記録のみ。実注文はまだしない。")


def render_cli(assessment: AlertAssessment) -> str:
    lines = [
        f"{assessment.display_symbol} Dip Alert",
        f"As of JST: {assessment.market.as_of_jst}",
        f"Current price: ¥{assessment.market.current_price:,.0f}",
        f"Prev close: ¥{assessment.market.previous_close:,.0f} ({assessment.market.day_change_pct:+.2f}%)",
        f"Recent 14d high: ¥{assessment.market.recent_high:,.0f} ({assessment.market.drop_from_recent_high_pct:+.2f}% from high)",
        f"SMA200: ¥{assessment.market.sma200:,.0f} / close>SMA200={assessment.market.above_sma200}",
        f"Market data age: {_format_data_age(assessment.market.data_age_hours)} / stale={assessment.market.data_stale_level}",
        f"Buy status: {assessment.buy_status}",
        f"Next action: {next_action_text(assessment)}",
    ]
    if assessment.reasons:
        lines.append("Buy reasons:")
        lines.extend(f"- {reason}" for reason in assessment.reasons)
    if assessment.hold_status:
        lines.append(f"Hold status: {assessment.hold_status}")
        lines.extend(f"- {reason}" for reason in assessment.action_reasons)
    if assessment.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in assessment.warnings)
    buy_line = assessment.next_price_lines.get("buy_candidate_line")
    if buy_line is not None:
        lines.append(f"Buy candidate line: ¥{buy_line:,.0f}")
        distance = assessment.next_price_lines.get("distance_to_buy_line_pct")
        if distance is not None:
            lines.append(f"Distance to buy candidate line: {distance:+.2f}%")
    sma_distance = assessment.next_price_lines.get("distance_to_sma200_pct")
    if sma_distance is not None:
        lines.append(f"Distance to SMA200: {sma_distance:+.2f}%")
    if assessment.position:
        lines.append(f"Position id: {assessment.position.get('id')}")
        lines.append(f"Take profit line: ¥{assessment.next_price_lines['take_profit_line']:,.0f}")
        lines.append(f"Stop loss line: ¥{assessment.next_price_lines['stop_loss_line']:,.0f}")
        lines.append(f"Unrealized PnL: ¥{assessment.position['unrealized_pnl_jpy']:,.2f}")
        lines.append(f"Max holding deadline: {assessment.position['max_holding_deadline']}")
    if assessment.order_proposal:
        lines.append("Order proposal:")
        lines.append(f"- Proposal id: {assessment.order_proposal['proposal_id']}")
        lines.append(f"- Side: {assessment.order_proposal['side']}")
        lines.append(f"- GMO spot symbol: {assessment.order_proposal.get('gmo_spot_symbol')}")
        lines.append(f"- Price: ¥{assessment.order_proposal['suggested_price']:,.0f}")
        lines.append(f"- Size: {assessment.order_proposal['suggested_size']}")
        lines.append(f"- Estimated JPY: ¥{assessment.order_proposal['estimated_jpy']:,.2f}")
        lines.append(f"- Source status: {assessment.order_proposal['source_status']}")
    if assessment.order_proposal_state:
        lines.append(f"Order proposal saved: {assessment.order_proposal_state['saved']}")
        lines.append(f"Order proposal save reason: {assessment.order_proposal_state['reason']}")
    if assessment.signal_history_state:
        lines.append(f"Signal saved: {assessment.signal_history_state['saved']}")
        lines.append(f"Signal id: {assessment.signal_history_state['signal_id']}")
    if assessment.paper_trade_state:
        lines.append(f"Paper trades created: {assessment.paper_trade_state['created_count']}")
        lines.append(f"Open paper trades: {assessment.paper_trade_state['open_count']}")
        if assessment.paper_trade_state.get("path"):
            lines.append(f"Paper trade path: {assessment.paper_trade_state['path']}")
    if assessment.paper_trade_performance:
        lines.append("Paper trade performance:")
        for summary in assessment.paper_trade_performance:
            lines.append(
                f"- {summary['rule_id']}: trades={summary['trades']} open={summary['open']} "
                f"closed={summary['closed']} win_rate={summary['win_rate']:.2f}% total_pnl_jpy=¥{summary['total_pnl_jpy']:,.2f}"
            )
    if assessment.notification:
        lines.append(f"Should notify: {assessment.notification['should_notify']}")
        lines.append(f"Notification type: {assessment.notification['notification_type']}")
        lines.append(f"Priority: {assessment.notification['priority']}")
        if assessment.notification.get("reasons"):
            lines.append("Notification reasons:")
            lines.extend(f"- {reason}" for reason in assessment.notification["reasons"])
        if assessment.notification.get("title") and assessment.notification.get("message"):
            lines.append("Notification preview:")
            lines.append(assessment.notification["title"])
            lines.append(assessment.notification["message"])
    if assessment.discord:
        lines.append(f"Discord requested: {assessment.discord['requested']}")
        lines.append(f"Discord sent: {assessment.discord['sent']}")
        lines.append(f"Discord skipped reason: {assessment.discord['skipped_reason']}")
        lines.append(f"Discord error: {assessment.discord['error']}")
    if assessment.email:
        lines.append(f"Email requested: {assessment.email['requested']}")
        lines.append(f"Email sent: {assessment.email['sent']}")
        lines.append(f"Email skipped reason: {assessment.email['skipped_reason']}")
        lines.append(f"Email error: {assessment.email['error']}")
    if assessment.test_discord_result:
        lines.append(f"Test notification: {assessment.test_notification}")
        lines.append(f"Test Discord requested: {assessment.test_discord_result['requested']}")
        lines.append(f"Test Discord sent: {assessment.test_discord_result['sent']}")
        lines.append(f"Test Discord skipped reason: {assessment.test_discord_result['skipped_reason']}")
        lines.append(f"Test Discord error: {assessment.test_discord_result['error']}")
    if assessment.test_email_result:
        lines.append(f"Test notification: {assessment.test_notification}")
        lines.append(f"Test Email requested: {assessment.test_email_result['requested']}")
        lines.append(f"Test Email sent: {assessment.test_email_result['sent']}")
        lines.append(f"Test Email skipped reason: {assessment.test_email_result['skipped_reason']}")
        lines.append(f"Test Email error: {assessment.test_email_result['error']}")
    return "\n".join(lines)


def render_markdown(assessment: AlertAssessment) -> str:
    lines = [
        f"# {assessment.display_symbol} Dip Alert",
        "",
        "## 今日の判定",
        "",
        f"- Buy status: {assessment.buy_status}",
        f"- Hold status: {assessment.hold_status or 'NO_POSITION'}",
        f"- As of JST: {assessment.market.as_of_jst}",
        f"- Market data age hours: {_format_data_age(assessment.market.data_age_hours)}",
        f"- Market data stale level: {assessment.market.data_stale_level}",
        f"- 次アクション: {next_action_text(assessment)}",
        "",
        "## 市況",
        "",
        f"- 現在価格: ¥{assessment.market.current_price:,.0f}",
        f"- 前日終値: ¥{assessment.market.previous_close:,.0f}",
        f"- 前日比: {assessment.market.day_change_pct:+.2f}%",
        f"- 直近14日高値: ¥{assessment.market.recent_high:,.0f}",
        f"- 直近14日高値からの下落率: {assessment.market.drop_from_recent_high_pct:+.2f}%",
        f"- SMA200: ¥{assessment.market.sma200:,.0f}",
        f"- close > SMA200: {assessment.market.above_sma200}",
        f"- 直近エントリーからの日数: {assessment.market.days_since_last_entry}",
        "",
        "## 条件別チェックリスト",
        "",
    ]
    for key, value in assessment.checklists["buy"].items():
        lines.append(f"- buy:{key}: {value}")
    for key, value in assessment.checklists["hold"].items():
        lines.append(f"- hold:{key}: {value}")
    if assessment.warnings:
        lines += [
            "",
            "## 警告",
            "",
        ]
        lines.extend(f"- {warning}" for warning in assessment.warnings)
    lines += [
        "",
        "## 見送り理由 / アクション理由",
        "",
    ]
    if assessment.reasons:
        lines.extend(f"- {reason}" for reason in assessment.reasons)
    if assessment.action_reasons:
        lines.extend(f"- {reason}" for reason in assessment.action_reasons)
    lines += [
        "",
        "## 次に見るべき価格ライン",
        "",
    ]
    if "buy_candidate_line" in assessment.next_price_lines:
        lines.append(f"- 買い候補ライン: ¥{assessment.next_price_lines['buy_candidate_line']:,.0f}")
    if "distance_to_buy_line_pct" in assessment.next_price_lines:
        lines.append(f"- 買い候補ラインまであと: {assessment.next_price_lines['distance_to_buy_line_pct']:+.2f}%")
    if "distance_to_sma200_pct" in assessment.next_price_lines:
        lines.append(f"- SMA200まであと: {assessment.next_price_lines['distance_to_sma200_pct']:+.2f}%")
    if assessment.position:
        lines += [
            f"- 利確ライン: ¥{assessment.next_price_lines['take_profit_line']:,.0f}",
            f"- 損切りライン: ¥{assessment.next_price_lines['stop_loss_line']:,.0f}",
            f"- 最大保有期限: {assessment.position['max_holding_days']} 日",
            f"- 最大保有期限日: {assessment.position['max_holding_deadline']}",
        ]
    if assessment.position:
        lines += [
            "",
            "## 保有中の判定",
            "",
            f"- entry_price: ¥{assessment.position['entry_price']:,.0f}",
            f"- entry_date: {assessment.position['entry_date']}",
            f"- position_size: {assessment.position['position_size']}",
            f"- position_id: {assessment.position.get('id')}",
            f"- note: {assessment.position.get('note')}",
            f"- current_price: ¥{assessment.position['current_price']:,.0f}",
            f"- 含み損益率: {assessment.position['unrealized_pnl_pct']:+.2f}%",
            f"- 含み損益額: ¥{assessment.position['unrealized_pnl_jpy']:,.2f}",
            f"- 保有日数: {assessment.position['holding_days']} 日",
            f"- hold_status: {assessment.hold_status}",
        ]
    lines += [
        "",
        "## 注文案",
        "",
    ]
    if assessment.order_proposal:
        lines += [
            f"- proposal_id: {assessment.order_proposal['proposal_id']}",
            f"- created_at: {assessment.order_proposal['created_at']}",
            f"- side: {assessment.order_proposal['side']}",
            f"- gmo_spot_symbol: {assessment.order_proposal.get('gmo_spot_symbol')}",
            f"- execution_type: {assessment.order_proposal['execution_type']}",
            f"- suggested_price: ¥{assessment.order_proposal['suggested_price']:,.0f}",
            f"- suggested_size: {assessment.order_proposal['suggested_size']}",
            f"- estimated_jpy: ¥{assessment.order_proposal['estimated_jpy']:,.2f}",
            f"- source_status: {assessment.order_proposal['source_status']}",
            f"- reason: {assessment.order_proposal['reason']}",
            f"- requires_manual_confirmation: {assessment.order_proposal['requires_manual_confirmation']}",
            f"- send_to_exchange: {assessment.order_proposal['send_to_exchange']}",
        ]
        if assessment.order_proposal.get("position_id"):
            lines.append(f"- position_id: {assessment.order_proposal['position_id']}")
        if assessment.order_proposal.get("estimated_pnl_pct") is not None:
            lines.append(f"- estimated_pnl_pct: {assessment.order_proposal['estimated_pnl_pct']:+.2f}%")
        if assessment.order_proposal.get("estimated_pnl_jpy") is not None:
            lines.append(f"- estimated_pnl_jpy: ¥{assessment.order_proposal['estimated_pnl_jpy']:,.2f}")
        if assessment.order_proposal.get("risk_notes"):
            lines.extend(f"- risk_note: {note}" for note in assessment.order_proposal["risk_notes"])
    else:
        lines.append("- order_proposal: none")
    if assessment.order_proposal_state:
        lines += [
            f"- saved: {assessment.order_proposal_state['saved']}",
            f"- save_reason: {assessment.order_proposal_state['reason']}",
        ]
    lines += [
        "",
        "## シグナル履歴",
        "",
    ]
    if assessment.signal_history_state:
        lines += [
            f"- signal_id: {assessment.signal_history_state['signal_id']}",
            f"- saved: {assessment.signal_history_state['saved']}",
            f"- save_reason: {assessment.signal_history_state['reason']}",
        ]
    else:
        lines.append("- signal_history: not_saved")
    lines += [
        "",
        "## Paper Trade",
        "",
    ]
    if assessment.paper_trade_state:
        lines += [
            f"- created_count: {assessment.paper_trade_state['created_count']}",
            f"- save_reason: {assessment.paper_trade_state['reason']}",
            f"- open_count: {assessment.paper_trade_state['open_count']}",
        ]
        if assessment.paper_trade_state.get("created_trade_ids"):
            lines.extend(f"- paper_trade_id: {trade_id}" for trade_id in assessment.paper_trade_state["created_trade_ids"])
    else:
        lines.append("- paper_trades: not_evaluated")
    if assessment.paper_trade_performance:
        lines += [
            "",
            "### ルール別簡易成績",
            "",
        ]
        for summary in assessment.paper_trade_performance:
            lines.append(
                f"- {summary['rule_id']}: trades={summary['trades']}, open={summary['open']}, "
                f"closed={summary['closed']}, win_rate={summary['win_rate']:.2f}%, "
                f"total_pnl_jpy=¥{summary['total_pnl_jpy']:,.2f}, max_drawdown_pct={summary['max_drawdown_pct']:.2f}%"
            )
    lines += [
        "",
        "## 通知判定",
        "",
    ]
    if assessment.notification:
        lines += [
            f"- should_notify: {assessment.notification['should_notify']}",
            f"- notification_type: {assessment.notification['notification_type']}",
            f"- priority: {assessment.notification['priority']}",
            f"- previous_effective_status: {assessment.notification['previous_effective_status']}",
            f"- distance_to_buy_line_pct: {assessment.notification['distance_to_buy_line_pct']}",
        ]
        if assessment.notification.get("reasons"):
            lines.extend(f"- notify_reason: {reason}" for reason in assessment.notification["reasons"])
        if assessment.notification.get("title"):
            lines += [
                "",
                "### 通知プレビュー",
                "",
                assessment.notification["title"],
                "",
                assessment.notification["message"],
            ]
    else:
        lines.append("- notification: not_evaluated")
    lines += [
        "",
        "## Discord通知結果",
        "",
    ]
    if assessment.discord:
        lines += [
            f"- requested: {assessment.discord['requested']}",
            f"- sent: {assessment.discord['sent']}",
            f"- skipped_reason: {assessment.discord['skipped_reason']}",
            f"- error: {assessment.discord['error']}",
        ]
    else:
        lines.append("- discord: not_evaluated")
    lines += [
        "",
        "## Email通知結果",
        "",
    ]
    if assessment.email:
        lines += [
            f"- requested: {assessment.email['requested']}",
            f"- sent: {assessment.email['sent']}",
            f"- skipped_reason: {assessment.email['skipped_reason']}",
            f"- error: {assessment.email['error']}",
        ]
    else:
        lines.append("- email: not_evaluated")
    lines += [
        "",
        "## テスト通知結果",
        "",
    ]
    if assessment.test_discord_result:
        lines += [
            f"- test_notification: {assessment.test_notification}",
            f"- requested: {assessment.test_discord_result['requested']}",
            f"- sent: {assessment.test_discord_result['sent']}",
            f"- skipped_reason: {assessment.test_discord_result['skipped_reason']}",
            f"- error: {assessment.test_discord_result['error']}",
        ]
    elif assessment.test_email_result:
        lines += [
            f"- test_notification: {assessment.test_notification}",
            f"- requested: {assessment.test_email_result['requested']}",
            f"- sent: {assessment.test_email_result['sent']}",
            f"- skipped_reason: {assessment.test_email_result['skipped_reason']}",
            f"- error: {assessment.test_email_result['error']}",
        ]
    else:
        lines.append("- test_discord: not_evaluated")
    lines += [
        "",
        "## バックテスト参考成績",
        "",
        f"- Annualized {assessment.reference_backtest['annualized_return_pct']:+.2f}%",
        f"- Max DD {assessment.reference_backtest['max_drawdown_pct']:.2f}%",
        f"- Portfolio Unrealized DD {assessment.reference_backtest['portfolio_unrealized_drawdown_pct']:.2f}%",
        f"- Trades {assessment.reference_backtest['trades']}",
        f"- Stop Loss {assessment.reference_backtest['stop_loss_count']}",
        f"- Avg Hold {assessment.reference_backtest['average_holding_days']:.1f}日",
        "",
        "## 注意書き",
        "",
        f"- {assessment.note}",
    ]
    return "\n".join(lines) + "\n"


def save_markdown_report(content: str, root: Path) -> Path:
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(JST).strftime("%Y%m%d")
    path = reports_dir / f"{BTC_JPY_ALERT_CONFIG.report_slug}_{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path


def default_report_path(root: Path, config: AlertConfig) -> Path:
    reports_dir = root / "reports"
    date_str = datetime.now(JST).strftime("%Y%m%d")
    return reports_dir / f"{config.report_slug}_{date_str}.md"


def save_markdown_report_for_config(content: str, root: Path, config: AlertConfig) -> Path:
    path = default_report_path(root, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def load_default_assessment(position: Optional[PositionInput] = None, config: Optional[AlertConfig] = None) -> AlertAssessment:
    config = config or BTC_JPY_ALERT_CONFIG
    store = SQLiteStore()
    rows = store.load_ohlcv(config.symbol, config.interval, limit=400)
    if not rows:
        raise ValueError("保存済みの日足データがありません。先に fetch_btc_price.py を実行してください。")
    ticker = store.load_latest_ticker(config.symbol)
    return build_alert_assessment(rows, ticker, position, config, now=datetime.now(JST))
