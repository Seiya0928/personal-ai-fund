from datetime import date, datetime

from src.alerts.btc_dip_alert import (
    BASELINE_PARAMS,
    BTC_JPY_ALERT_CONFIG,
    PositionInput,
    assessment_to_dict,
    build_alert_assessment,
    build_market_snapshot,
    render_cli,
    render_markdown,
)


def _make_rows(prices, step_ms=86_400_000):
    rows = []
    for i, price in enumerate(prices):
        rows.append({
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1.0,
            "timestamp": str(i * step_ms),
        })
    return rows


def test_build_market_snapshot_requires_200_days():
    try:
        build_market_snapshot(_make_rows([100] * 50), None, False, BASELINE_PARAMS)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "200 件以上必要" in str(exc)


def test_buy_candidate_when_drop_and_trend_conditions_are_met():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    rows = _make_rows(prices)
    ticker = {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(rows, ticker, None, BTC_JPY_ALERT_CONFIG)

    assert assessment.buy_status == "BUY_CANDIDATE"
    assert assessment.checklists["buy"]["trend_ok"] is True
    assert assessment.checklists["buy"]["dip_trigger"] is True


def test_fresh_data_unmet_conditions_stays_buy_skip():
    rows = _make_rows([100] * 229 + [105])
    ticker = {"last": 105.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(rows, ticker, None, BTC_JPY_ALERT_CONFIG)

    assert assessment.buy_status == "BUY_SKIP"
    assert assessment.checklists["buy"]["dip_trigger"] is False
    assert assessment.checklists["buy"]["watch_buy_line_near"] is False
    assert assessment.checklists["buy"]["watch_recent_high_pullback"] is False
    assert assessment.checklists["buy"]["watch_day_drop_progress"] is False


def test_buy_watch_when_near_buy_line_but_not_candidate():
    rows = _make_rows([100] * 230)
    ticker = {"last": 99.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(rows, ticker, None, BTC_JPY_ALERT_CONFIG)

    assert assessment.buy_status == "BUY_WATCH"
    assert assessment.checklists["buy"]["dip_trigger"] is False
    assert assessment.checklists["buy"]["watch_buy_line_near"] is True
    assert assessment.order_proposal is None
    assert "買い候補ラインまで" in " ".join(assessment.reasons)


def test_buy_watch_when_trend_filter_blocks_candidate_but_pullback_is_visible():
    rows = _make_rows([120] * 229 + [116])
    ticker = {"last": 116.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(rows, ticker, None, BTC_JPY_ALERT_CONFIG)

    assert assessment.buy_status == "BUY_WATCH"
    assert assessment.checklists["buy"]["trend_ok"] is False
    assert assessment.checklists["buy"]["trend_filter_blocking"] is True
    assert "trend_filter は NG" in " ".join(assessment.reasons)


def test_stale_ticker_adds_warning_without_changing_strategy_thresholds():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    rows = _make_rows(prices)
    ticker = {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(
        rows,
        ticker,
        None,
        BTC_JPY_ALERT_CONFIG,
        now=datetime.fromisoformat("2026-04-29T07:30:00+00:00"),
    )

    assert assessment.market.data_stale_level == "warning"
    assert "older than 6h" in assessment.warnings[0]
    assert assessment.buy_status == "BUY_CANDIDATE"


def test_invalid_stale_ticker_suppresses_buy_candidate():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    rows = _make_rows(prices)
    ticker = {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"}

    assessment = build_alert_assessment(
        rows,
        ticker,
        None,
        BTC_JPY_ALERT_CONFIG,
        now=datetime.fromisoformat("2026-04-30T01:00:00+00:00"),
    )
    markdown = render_markdown(assessment)

    assert assessment.market.data_stale_level == "invalid"
    assert assessment.buy_status == "BUY_SKIP"
    assert assessment.checklists["buy"]["fresh_market_data"] is False
    assert "市場データが24時間以上古いため" in assessment.reasons[0]
    assert "Market data stale level: invalid" in markdown


def test_hold_status_reports_take_profit():
    prices = [100] * 220
    rows = _make_rows(prices)
    ticker = {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}
    position = PositionInput(entry_price=100.0, entry_date=date(2026, 4, 1), position_size=0.01)

    assessment = build_alert_assessment(rows, ticker, position, BTC_JPY_ALERT_CONFIG)

    assert assessment.hold_status == "TAKE_PROFIT_CANDIDATE"
    assert assessment.position["take_profit_line"] == 110


def test_hold_status_reports_timeout():
    prices = [100] * 220
    rows = _make_rows(prices)
    ticker = {"last": 101.0, "timestamp": "2026-04-29T00:00:00Z"}
    position = PositionInput(entry_price=100.0, entry_date=date(2025, 12, 1), position_size=0.01)

    assessment = build_alert_assessment(rows, ticker, position, BTC_JPY_ALERT_CONFIG)

    assert assessment.hold_status == "TIMEOUT_EXIT_CANDIDATE"


def test_renderers_include_expected_sections():
    prices = [100] * 205 + [103, 105, 106, 107, 103]
    rows = _make_rows(prices)
    ticker = {"last": 99.0, "timestamp": "2026-04-29T00:00:00Z"}
    assessment = build_alert_assessment(rows, ticker, None, BTC_JPY_ALERT_CONFIG)

    cli_output = render_cli(assessment)
    markdown_output = render_markdown(assessment)
    payload = assessment_to_dict(assessment)

    assert "BTC/JPY Dip Alert" in cli_output
    assert "買い候補ライン" in markdown_output
    assert payload["buy_status"] in {"BUY_CANDIDATE", "BUY_WATCH", "BUY_SKIP"}


def test_renderers_include_next_action_for_buy_statuses():
    cases = [
        ([100] * 229 + [105], {"last": 105.0, "timestamp": "2026-04-29T00:00:00Z"}, "何もしない。記録のみ。"),
        ([100] * 230, {"last": 99.0, "timestamp": "2026-04-29T00:00:00Z"}, "監視のみ。手動購入しない。注文案は作らない。"),
        ([100 + i for i in range(210)] + [320, 325, 330, 335, 340], {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"}, "order proposalを確認し、必要ならdry-run注文記録を作る。実注文はまだしない。"),
    ]
    for prices, ticker, expected in cases:
        assessment = build_alert_assessment(_make_rows(prices), ticker, None, BTC_JPY_ALERT_CONFIG)
        cli_output = render_cli(assessment)
        markdown_output = render_markdown(assessment)

        assert f"Next action: {expected}" in cli_output
        assert f"- 次アクション: {expected}" in markdown_output


def test_renderers_include_next_action_for_sell_candidates():
    rows = _make_rows([100] * 220)
    position = PositionInput(entry_price=100.0, entry_date=date(2026, 4, 1), position_size=0.01)
    cases = [
        ({"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}, "SELL proposalを確認し、dry-run決済記録を作る。実注文はまだしない。"),
        ({"last": 87.0, "timestamp": "2026-04-29T00:00:00Z"}, "SELL proposalを確認し、損切りリハーサルを優先する。実注文はまだしない。"),
        ({"last": 101.0, "timestamp": "2026-07-10T00:00:00Z"}, "保有期限切れ候補としてSELL proposalを確認する。実注文はまだしない。"),
    ]
    for ticker, expected in cases:
        assessment = build_alert_assessment(rows, ticker, position, BTC_JPY_ALERT_CONFIG)
        cli_output = render_cli(assessment)
        markdown_output = render_markdown(assessment)

        assert f"Next action: {expected}" in cli_output
        assert f"- 次アクション: {expected}" in markdown_output


def test_stale_invalid_next_action_tells_operator_to_check_fetch_and_health():
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
        now=datetime.fromisoformat("2026-04-30T01:00:00+00:00"),
    )

    expected = "市場データが古いため判断無効。fetch/health checkを確認。"

    assert f"Next action: {expected}" in render_cli(assessment)
    assert f"- 次アクション: {expected}" in render_markdown(assessment)


def test_markdown_includes_position_details():
    prices = [100] * 220
    rows = _make_rows(prices)
    ticker = {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}
    position = PositionInput(
        entry_price=100.0,
        entry_date=date(2026, 4, 1),
        position_size=0.01,
        position_id="btc_20260429_001",
        note="manual buy",
    )

    assessment = build_alert_assessment(rows, ticker, position, BTC_JPY_ALERT_CONFIG)
    markdown_output = render_markdown(assessment)

    assert "position_id: btc_20260429_001" in markdown_output
    assert "含み損益額" in markdown_output


def test_renderers_include_signal_and_paper_trade_sections():
    prices = [100] * 220
    rows = _make_rows(prices)
    ticker = {"last": 111.0, "timestamp": "2026-04-29T00:00:00Z"}
    position = PositionInput(entry_price=100.0, entry_date=date(2026, 4, 1), position_size=0.01)

    assessment = build_alert_assessment(rows, ticker, position, BTC_JPY_ALERT_CONFIG)
    assessment.signal_history_state = {"signal_id": "sig_1", "saved": True, "reason": "saved"}
    assessment.paper_trade_state = {"created_count": 3, "reason": "created", "open_count": 3, "created_trade_ids": ["a", "b", "c"]}
    assessment.paper_trade_performance = [{"rule_id": "Current", "trades": 1, "open": 1, "closed": 0, "win_rate": 0.0, "total_pnl_jpy": 0.0, "max_drawdown_pct": 0.0}]

    cli_output = render_cli(assessment)
    markdown_output = render_markdown(assessment)

    assert "Signal id: sig_1" in cli_output
    assert "## シグナル履歴" in markdown_output
    assert "## Paper Trade" in markdown_output
