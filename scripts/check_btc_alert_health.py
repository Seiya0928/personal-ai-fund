"""BTC alert 定時実行の health check。"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage.sqlite_store import SQLiteStore

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
EXPECTED_SLOTS = [(9, 0), (15, 0), (22, 0)]
MARKET_DATA_WARNING_AFTER = timedelta(hours=6)
MARKET_DATA_INVALID_AFTER = timedelta(hours=24)

START_RE = re.compile(r"^\[(?P<ts>.+?)\] run_daily_btc_alert start$")
EXIT_RE = re.compile(r"^\[(?P<ts>.+?)\] run_daily_btc_alert exit_code=(?P<code>\d+)$")


@dataclass
class ParsedRun:
    started_at: datetime
    exit_code: Optional[int] = None
    buy_status: Optional[str] = None
    should_notify: Optional[bool] = None
    email_sent: Optional[bool] = None
    email_skipped_reason: Optional[str] = None
    markdown_report_saved: Optional[str] = None


@dataclass
class HealthResult:
    ok: bool
    reason: Optional[str]
    last_run: Optional[ParsedRun]
    expected_runs: list[str]
    observed_runs: list[str]
    market_data: Optional["MarketDataFreshness"] = None


@dataclass
class MarketDataFreshness:
    latest_ticker_at: Optional[datetime]
    age_hours: Optional[float]
    stale_level: str
    stale_reason: Optional[str]


def log_path_for_date(day: datetime) -> Path:
    return LOG_DIR / f"btc_dip_alert_{day.strftime('%Y%m%d')}.log"


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z").astimezone(JST)


def expected_run_labels(now: datetime) -> list[str]:
    labels = []
    for hour, minute in EXPECTED_SLOTS:
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= slot:
            labels.append(f"{hour:02d}:{minute:02d}")
    return labels


def parse_runs(log_text: str) -> list[ParsedRun]:
    runs: list[ParsedRun] = []
    current: Optional[ParsedRun] = None
    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        start_match = START_RE.match(line)
        if start_match:
            current = ParsedRun(started_at=_parse_timestamp(start_match.group("ts")))
            runs.append(current)
            continue
        if current is None:
            continue
        exit_match = EXIT_RE.match(line)
        if exit_match:
            current.exit_code = int(exit_match.group("code"))
            continue
        if line.startswith("Buy status: "):
            current.buy_status = line.split(": ", 1)[1]
        elif line.startswith("Should notify: "):
            current.should_notify = line.split(": ", 1)[1].strip() == "True"
        elif line.startswith("Email sent: "):
            current.email_sent = line.split(": ", 1)[1].strip() == "True"
        elif line.startswith("Email skipped reason: "):
            current.email_skipped_reason = line.split(": ", 1)[1]
        elif line.startswith("Markdown report saved: "):
            current.markdown_report_saved = line.split(": ", 1)[1]
    return runs


def observed_run_labels(runs: list[ParsedRun]) -> list[str]:
    labels: list[str] = []
    for run in runs:
        label = f"{run.started_at.hour:02d}:{run.started_at.minute:02d}"
        if (run.started_at.hour, run.started_at.minute) in EXPECTED_SLOTS and label not in labels:
            labels.append(label)
    return labels


def load_market_data_freshness(now: datetime, store: Optional[SQLiteStore] = None) -> MarketDataFreshness:
    store = store or SQLiteStore()
    ticker = store.load_latest_ticker("BTC_JPY")
    if not ticker or not ticker.get("timestamp"):
        return MarketDataFreshness(None, None, "invalid", "latest BTC_JPY ticker not found")
    try:
        latest = datetime.fromisoformat(str(ticker["timestamp"]).replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return MarketDataFreshness(None, None, "invalid", "latest BTC_JPY ticker timestamp is invalid")
    age = now.astimezone(JST) - latest
    age_hours = max(age.total_seconds() / 3600, 0.0)
    if age >= MARKET_DATA_INVALID_AFTER:
        return MarketDataFreshness(latest, round(age_hours, 2), "invalid", f"market data is older than 24h: age={age_hours:.1f}h")
    if age >= MARKET_DATA_WARNING_AFTER:
        return MarketDataFreshness(latest, round(age_hours, 2), "warning", f"market data is older than 6h: age={age_hours:.1f}h")
    return MarketDataFreshness(latest, round(age_hours, 2), "fresh", None)


def evaluate_health(now: datetime, log_path: Path, market_data: Optional[MarketDataFreshness] = None) -> HealthResult:
    market_data = market_data or load_market_data_freshness(now)
    if not log_path.exists():
        return HealthResult(False, "log file not found", None, expected_run_labels(now), [], market_data)

    runs = parse_runs(log_path.read_text(encoding="utf-8"))
    expected = expected_run_labels(now)
    observed = observed_run_labels(runs)
    missing = [slot for slot in expected if slot not in observed]
    if missing:
        return HealthResult(False, f"no run after expected time {missing[0]}", runs[-1] if runs else None, expected, observed, market_data)
    if not runs:
        return HealthResult(False, "log file has no runs", None, expected, observed, market_data)

    last_run = runs[-1]
    if last_run.exit_code is None:
        return HealthResult(False, "last run missing exit_code", last_run, expected, observed, market_data)
    if last_run.exit_code != 0:
        return HealthResult(False, f"last exit_code={last_run.exit_code}", last_run, expected, observed, market_data)
    if not last_run.markdown_report_saved:
        return HealthResult(False, "markdown report not saved", last_run, expected, observed, market_data)
    if last_run.should_notify is True and last_run.email_sent is not True:
        reason = last_run.email_skipped_reason or "email not sent"
        return HealthResult(False, f"email not sent: {reason}", last_run, expected, observed, market_data)
    if market_data.stale_level != "fresh":
        return HealthResult(False, f"market data stale: {market_data.stale_reason}", last_run, expected, observed, market_data)

    return HealthResult(True, None, last_run, expected, observed, market_data)


def render_health(result: HealthResult) -> str:
    lines = [
        "BTC Alert Health Check",
        f"Status: {'OK' if result.ok else 'NG'}",
    ]
    if result.reason:
        lines.append(f"Reason: {result.reason}")
    if result.last_run:
        lines.append(f"Last run: {result.last_run.started_at.strftime('%Y-%m-%d %H:%M:%S JST')}")
        lines.append(f"Exit code: {result.last_run.exit_code}")
        lines.append(f"Buy status: {result.last_run.buy_status}")
        lines.append(f"Should notify: {result.last_run.should_notify}")
        if result.last_run.email_sent:
            lines.append("Email: sent")
        else:
            lines.append(f"Email: skipped / {result.last_run.email_skipped_reason}")
        lines.append(f"Markdown: {'saved' if result.last_run.markdown_report_saved else 'missing'}")
    if result.market_data:
        latest = result.market_data.latest_ticker_at.strftime("%Y-%m-%d %H:%M:%S JST") if result.market_data.latest_ticker_at else "None"
        age = f"{result.market_data.age_hours:.2f}h" if result.market_data.age_hours is not None else "unknown"
        lines.append(f"Latest ticker: {latest}")
        lines.append(f"Market data age: {age}")
        lines.append(f"Market data stale level: {result.market_data.stale_level}")
        lines.append(f"Market data stale reason: {result.market_data.stale_reason}")
    lines.append(f"Expected runs so far: {', '.join(result.expected_runs) if result.expected_runs else '(none)'}")
    lines.append(f"Observed runs: {', '.join(result.observed_runs) if result.observed_runs else '(none)'}")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(JST)
    result = evaluate_health(now, log_path_for_date(now))
    print(render_health(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
