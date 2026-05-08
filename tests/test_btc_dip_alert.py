from datetime import date

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
