from src.alerts.btc_dip_alert import BTC_JPY_ALERT_CONFIG, build_alert_assessment
from src.alerts.signal_history import build_signal_record, list_signal_history, save_signal_record


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


def test_signal_history_saves_and_deduplicates(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 323.0, "timestamp": "2026-04-29T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.notification = {"should_notify": True, "notification_type": "BUY_CANDIDATE"}
    record = build_signal_record(assessment)

    stored1, saved1 = save_signal_record(record, tmp_path / "signal_history.json")
    stored2, saved2 = save_signal_record(record, tmp_path / "signal_history.json")

    assert saved1 is True
    assert saved2 is False
    assert stored1["signal_id"] == stored2["signal_id"]
    assert len(list_signal_history(tmp_path / "signal_history.json")) == 1


def test_buy_skip_should_notify_false_is_saved(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 340.0, "timestamp": "2026-05-02T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.buy_status = "BUY_SKIP"
    assessment.notification = {"should_notify": False, "notification_type": "BUY_SKIP"}

    record = build_signal_record(assessment, created_at="2026-05-02T09:00:05+09:00")
    stored, saved = save_signal_record(record, tmp_path / "signal_history.json")

    assert saved is True
    assert stored["signal_id"] == "btc_jpy_20260502_090005_buy_skip"
    assert stored["should_notify"] is False
    assert stored["buy_status"] == "BUY_SKIP"


def test_same_day_and_status_with_different_run_times_are_separate_signals(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 340.0, "timestamp": "2026-05-02T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.buy_status = "BUY_SKIP"
    assessment.notification = {"should_notify": False, "notification_type": "BUY_SKIP"}

    first = build_signal_record(assessment, created_at="2026-05-02T09:00:05+09:00")
    second = build_signal_record(assessment, created_at="2026-05-02T15:00:05+09:00")
    _, saved1 = save_signal_record(first, tmp_path / "signal_history.json")
    _, saved2 = save_signal_record(second, tmp_path / "signal_history.json")

    signals = list_signal_history(tmp_path / "signal_history.json")
    assert saved1 is True
    assert saved2 is True
    assert [signal["signal_id"] for signal in signals] == [
        "btc_jpy_20260502_090005_buy_skip",
        "btc_jpy_20260502_150005_buy_skip",
    ]


def test_same_second_symbol_and_status_is_not_saved_twice(tmp_path):
    prices = [100 + i for i in range(210)] + [320, 325, 330, 335, 340]
    assessment = build_alert_assessment(
        _make_rows(prices),
        {"last": 340.0, "timestamp": "2026-05-02T00:00:00Z"},
        None,
        BTC_JPY_ALERT_CONFIG,
    )
    assessment.buy_status = "BUY_SKIP"
    assessment.notification = {"should_notify": False, "notification_type": "BUY_SKIP"}

    first = build_signal_record(assessment, created_at="2026-05-02T09:00:05+09:00")
    second = build_signal_record(assessment, created_at="2026-05-02T09:00:05+09:00")
    _, saved1 = save_signal_record(first, tmp_path / "signal_history.json")
    _, saved2 = save_signal_record(second, tmp_path / "signal_history.json")

    assert saved1 is True
    assert saved2 is False
    assert len(list_signal_history(tmp_path / "signal_history.json")) == 1
