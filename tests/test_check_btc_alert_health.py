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

    result = module.evaluate_health(now, log_path)

    assert result.ok is True
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

    result = module.evaluate_health(now, log_path)

    assert result.ok is True


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

    result = module.evaluate_health(now, log_path)

    assert result.ok is False
    assert result.reason == "last exit_code=1"


def test_health_ng_when_log_is_missing(tmp_path):
    now = datetime(2026, 4, 30, 9, 30, 0, tzinfo=module.JST)
    result = module.evaluate_health(now, tmp_path / "missing.log")
    assert result.ok is False
    assert result.reason == "log file not found"


def test_health_ng_when_expected_run_missing(tmp_path):
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

    result = module.evaluate_health(now, log_path)

    assert result.ok is False
    assert result.reason == "no run after expected time 15:00"


def test_render_health_includes_summary_fields(tmp_path):
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
    result = module.evaluate_health(now, log_path)
    output = module.render_health(result)

    assert "Status: OK" in output
    assert "Buy status: BUY_SKIP" in output
    assert "Email: skipped / should_notify=false" in output
