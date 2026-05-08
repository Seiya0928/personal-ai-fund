from pathlib import Path
import stat


ROOT = Path(__file__).resolve().parents[1]


def test_run_daily_btc_alert_script_exists():
    path = ROOT / "scripts" / "run_daily_btc_alert.sh"
    assert path.exists()


def test_run_daily_btc_alert_script_is_executable():
    path = ROOT / "scripts" / "run_daily_btc_alert.sh"
    mode = path.stat().st_mode
    assert mode & stat.S_IXUSR


def test_run_daily_btc_alert_script_is_safe():
    content = (ROOT / "scripts" / "run_daily_btc_alert.sh").read_text(encoding="utf-8")
    assert "live_order_once.py" not in content
    assert "READ_ONLY=false" not in content
    assert "ALERT_EMAIL_PASSWORD" not in content
    assert "--send-daily-summary" in content
    assert "echo" not in content or "ALERT_EMAIL_PASSWORD" not in content


def test_env_example_contains_email_placeholders_only():
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ALERT_EMAIL_SMTP_HOST=smtp.gmail.com" in content
    assert "ALERT_EMAIL_SMTP_PORT=587" in content
    assert "ALERT_EMAIL_USERNAME=" in content
    assert "ALERT_EMAIL_PASSWORD=" in content
    assert "ALERT_EMAIL_FROM=" in content
    assert "ALERT_EMAIL_TO=" in content
    assert "app-password" not in content
    assert "ALERT_EMAIL_USERNAME=user@" not in content
    assert "ALERT_EMAIL_PASSWORD=app-" not in content
    assert "ALERT_EMAIL_FROM=from@" not in content
    assert "ALERT_EMAIL_TO=to@" not in content


def test_launchd_example_plist_exists():
    path = ROOT / "docs" / "launchd_btc_alert.example.plist"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "run_daily_btc_alert.sh" in content
    assert "StandardOutPath" in content
    assert "StandardErrorPath" in content
    assert "<integer>9</integer>" in content
    assert "<integer>15</integer>" in content
    assert "<integer>22</integer>" in content
    assert content.count("<key>Hour</key>") == 3
    assert content.count("<key>Minute</key>") == 3
    assert content.count("<integer>0</integer>") >= 3
