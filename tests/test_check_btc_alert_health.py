import importlib.util
from datetime import datetime
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_btc_alert_health.py"
SPEC = importlib.util.spec_from_file_location("check_btc_alert_health_module", SCRIPT_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _make_log(*blocks: str) -> str:
    return "\n".join(blocks) + "\n"


def _fresh_market(now):
    return module.MarketDataFreshness(now, 0.0, "fresh", None)


def _warning_market(now):
    return module.MarketDataFreshness(
        latest_ticker_at=now,
        age_hours=7.0,
        stale_level="warning",
        stale_reason="market data is older than 6h: age=7.0h",
    )


def _invalid_market(now):
    return module.MarketDataFreshness(
        latest_ticker_at=datetime(2026, 4, 29, 8, 30, 0, tzinfo=module.JST),
        age_hours=25.0,
        stale_level="invalid",
        stale_reason="market data is older than 24h: age=25.0h",
    )


# ---------------------------------------------------------------------------
# 既存テスト（OK / NG の基本ケース）
# ---------------------------------------------------------------------------

def test_health_ok_with_should_notify_false(tmp_path):
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "OK"
    assert result.current_state == "OK"
    assert result.last_run.email_skipped_reason == "should_notify=false"


def test_health_ok_with_email_sent(tmp_path):
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
            "[2026-04-30 15:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: True",
            "Email sent: True",
            "Email skipped reason: None",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 15:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 15, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "OK"
    assert result.current_state == "OK"


def test_health_ng_when_exit_code_is_non_zero(tmp_path):
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=1",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "NG"
    assert result.current_state == "NG"
    assert result.reason == "last exit_code=1"


def test_health_ng_when_log_is_missing(tmp_path):
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, tmp_path / "missing.log", _fresh_market(now))
    assert result.status == "NG"
    assert result.reason == "log file not found"


def test_health_ng_when_market_data_is_invalid(tmp_path):
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _invalid_market(now))
    output = module.render_health(result)

    assert result.status == "NG"
    assert result.current_state == "NG"
    assert "market data invalid" in result.reason
    assert "Latest ticker: 2026-04-29 08:30:00 JST" in output
    assert "Market data age: 25.00h" in output


# ---------------------------------------------------------------------------
# WARNING ケース：予定実行取りこぼしがあっても現在状態OK
# ---------------------------------------------------------------------------

def test_health_warning_when_scheduled_run_missed_but_latest_fresh(tmp_path):
    """09:00 スロットで失敗し、21:41 手動補完成功 → WARNING"""
    log_path = tmp_path / "btc_dip_alert_20260516.log"
    log_path.write_text(
        _make_log(
            # 09:00 scheduled → failed
            "[2026-05-16 09:08:48 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "[2026-05-16 09:26:13 +0900] run_daily_btc_alert exit_code=1",
            # 15:00 scheduled → success
            "[2026-05-16 15:00:04 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: True",
            "Email sent: True",
            "Email skipped reason: None",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 15:00:34 +0900] run_daily_btc_alert exit_code=0",
            # 21:41 manual → success
            "[2026-05-16 21:41:36 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 21:41:58 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 5, 16, 21, 50, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "WARNING"
    assert result.current_state == "OK"
    assert result.reason is None
    # 09:08 は exit_code=1 なので 09:00 スロットをカバーできていない
    assert "09:00" in result.missed_runs
    # 15:00 はカバー済み
    assert "15:00" in result.observed_runs
    # 21:41 は manual run として検出
    assert "21:41" in result.manual_runs
    assert any("missed expected run 09:00" in w for w in result.schedule_warnings)


def test_health_warning_when_one_slot_missed_no_manual(tmp_path):
    """09:00 のみ成功、15:00 未実行、now=15:30 → WARNING"""
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 15, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "WARNING"
    assert result.current_state == "OK"
    assert result.missed_runs == ["15:00"]
    assert result.manual_runs == []
    assert any("missed expected run 15:00" in w for w in result.schedule_warnings)


def test_health_warning_when_market_data_is_warning_level(tmp_path):
    """全スロット成功 + market_data.stale_level='warning' → WARNING"""
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _warning_market(now))

    assert result.status == "WARNING"
    assert result.current_state == "OK"
    assert result.missed_runs == []
    assert any("market data warning" in w for w in result.schedule_warnings)


def test_health_ng_when_market_data_invalid_despite_manual_run(tmp_path):
    """手動補完成功後も market invalid → NG"""
    log_path = tmp_path / "btc_dip_alert_20260516.log"
    log_path.write_text(
        _make_log(
            "[2026-05-16 21:41:36 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 21:41:58 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 5, 16, 22, 0, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _invalid_market(now))

    assert result.status == "NG"
    assert result.current_state == "NG"
    assert "market data invalid" in result.reason


def test_health_ng_when_latest_run_failed_even_if_earlier_succeeded(tmp_path):
    """15:00 成功 → 21:41 失敗 → 最新実行失敗で NG"""
    log_path = tmp_path / "btc_dip_alert_20260516.log"
    log_path.write_text(
        _make_log(
            "[2026-05-16 15:00:04 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 15:00:34 +0900] run_daily_btc_alert exit_code=0",
            "[2026-05-16 21:41:36 +0900] run_daily_btc_alert start",
            "[2026-05-16 21:41:58 +0900] run_daily_btc_alert exit_code=1",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 5, 16, 22, 0, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "NG"
    assert result.reason == "last exit_code=1"


def test_health_ok_when_all_scheduled_slots_covered(tmp_path):
    """09:00, 15:00, 22:00 全スロット成功 → OK"""
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
            "[2026-04-30 15:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 15:00:03 +0900] run_daily_btc_alert exit_code=0",
            "[2026-04-30 22:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 22:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 22, 30, 0, tzinfo=module.JST)

    result = module.evaluate_health(now, log_path, _fresh_market(now))

    assert result.status == "OK"
    assert result.missed_runs == []
    assert result.manual_runs == []
    assert result.schedule_warnings == []


# ---------------------------------------------------------------------------
# render_health の出力検証
# ---------------------------------------------------------------------------

def test_render_health_ok_includes_summary_fields(tmp_path):
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:00:02 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:00:03 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, log_path, _fresh_market(now))
    output = module.render_health(result)

    assert "Status: OK" in output
    assert "Current state: OK" in output
    assert "Buy status: BUY_SKIP" in output
    assert "Email: skipped / should_notify=false" in output
    assert "Market data stale level: fresh" in output


def test_render_health_warning_has_separate_fields(tmp_path):
    """WARNING の render が現在状態・スケジュール警告・手動実行を分けて表示。"""
    log_path = tmp_path / "btc_dip_alert_20260516.log"
    log_path.write_text(
        _make_log(
            # 09:00 スロット：失敗
            "[2026-05-16 09:08:48 +0900] run_daily_btc_alert start",
            "[2026-05-16 09:26:13 +0900] run_daily_btc_alert exit_code=1",
            # 15:00 スロット：成功
            "[2026-05-16 15:00:04 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 15:00:34 +0900] run_daily_btc_alert exit_code=0",
            # 21:41 手動：成功
            "[2026-05-16 21:41:36 +0900] run_daily_btc_alert start",
            "Buy status: BUY_WATCH",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-05-16 21:41:58 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 5, 16, 21, 50, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, log_path, _fresh_market(now))
    output = module.render_health(result)

    assert "Status: WARNING" in output
    assert "Current state: OK" in output
    assert "Schedule warning: missed expected run 09:00" in output
    assert "Observed scheduled runs: 15:00" in output
    assert "Missed runs: 09:00" in output
    assert "Manual/latest run detected: 21:41" in output
    # Reason は表示されない
    assert "Reason:" not in output


def test_render_health_ng_shows_reason(tmp_path):
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, tmp_path / "missing.log", _fresh_market(now))
    output = module.render_health(result)

    assert "Status: NG" in output
    assert "Current state: NG" in output
    assert "Reason: log file not found" in output


# ---------------------------------------------------------------------------
# slot tolerance window の境界チェック
# ---------------------------------------------------------------------------

def test_slot_tolerance_run_at_29min_after_covers_slot(tmp_path):
    """スロット時刻の29分後の実行 → そのスロットをカバーとみなす。"""
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:29:00 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:29:01 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 35, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, log_path, _fresh_market(now))
    assert result.status == "OK"
    assert "09:00" in result.observed_runs


def test_slot_tolerance_run_at_30min_after_is_manual(tmp_path):
    """スロット時刻のちょうど30分後の実行 → スロット外（manual run）とみなす。"""
    log_path = tmp_path / "btc_dip_alert_20260430.log"
    log_path.write_text(
        _make_log(
            "[2026-04-30 09:30:00 +0900] run_daily_btc_alert start",
            "Buy status: BUY_SKIP",
            "Should notify: False",
            "Email sent: False",
            "Email skipped reason: should_notify=false",
            "Markdown report saved: /tmp/report.md",
            "[2026-04-30 09:30:01 +0900] run_daily_btc_alert exit_code=0",
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 9, 35, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, log_path, _fresh_market(now))
    # 09:30 は slot window 外なので manual 扱い → 09:00 は missed
    assert "09:30" in result.manual_runs
    assert "09:00" in result.missed_runs
    assert result.status == "WARNING"
