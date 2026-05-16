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
# run が scheduled slot の何分以内なら「その slot をカバーした」とみなすか
SLOT_TOLERANCE_MINUTES = 30

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
    """Health check の判定結果。

    status:
        "OK"      - 全条件クリア
        "WARNING" - 現在状態はOKだが予定実行の取りこぼし or market data warning がある
        "NG"      - 最新実行失敗 / market invalid / ログなし 等
    current_state:
        "OK" / "NG" - 最新実行の状態（スケジュール取りこぼしを含まない）
    reason:
        NG の主因（WARNING では None）
    schedule_warnings:
        予定実行取りこぼし等の警告リスト（WARNING のとき）
    missed_runs:
        取りこぼした予定スロットのラベルリスト (例: ["09:00"])
    manual_runs:
        予定時刻外の成功実行ラベルリスト (例: ["21:41"])
    """

    status: str
    current_state: str
    last_run: Optional[ParsedRun]
    expected_runs: list
    observed_runs: list
    missed_runs: list
    manual_runs: list
    market_data: Optional["MarketDataFreshness"]
    schedule_warnings: list
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


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


def expected_run_labels(now: datetime) -> list:
    labels = []
    for hour, minute in EXPECTED_SLOTS:
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= slot:
            labels.append(f"{hour:02d}:{minute:02d}")
    return labels


def parse_runs(log_text: str) -> list:
    runs: list = []
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


def _run_slot_minutes(run: ParsedRun) -> int:
    return run.started_at.hour * 60 + run.started_at.minute


def observed_run_labels(runs: list) -> list:
    """成功した実行で SLOT_TOLERANCE_MINUTES 以内にカバーされた予定スロットのラベル。"""
    labels = []
    for hour, minute in EXPECTED_SLOTS:
        slot_mins = hour * 60 + minute
        for run in runs:
            if run.exit_code != 0:
                continue
            delta = _run_slot_minutes(run) - slot_mins
            if 0 <= delta < SLOT_TOLERANCE_MINUTES:
                labels.append(f"{hour:02d}:{minute:02d}")
                break
    return labels


def manual_run_labels(runs: list) -> list:
    """予定スロットのウィンドウ外にある成功実行の HH:MM ラベル（重複なし）。"""
    labels = []
    for run in runs:
        if run.exit_code != 0:
            continue
        run_mins = _run_slot_minutes(run)
        is_scheduled = any(
            0 <= run_mins - (h * 60 + m) < SLOT_TOLERANCE_MINUTES
            for h, m in EXPECTED_SLOTS
        )
        if not is_scheduled:
            label = f"{run.started_at.hour:02d}:{run.started_at.minute:02d}"
            if label not in labels:
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
    expected = expected_run_labels(now)

    def _ng(reason: str, last_run=None, observed=None, missed=None, manual=None) -> HealthResult:
        return HealthResult(
            status="NG",
            current_state="NG",
            reason=reason,
            last_run=last_run,
            expected_runs=expected,
            observed_runs=observed or [],
            missed_runs=missed or [],
            manual_runs=manual or [],
            market_data=market_data,
            schedule_warnings=[],
        )

    if not log_path.exists():
        return _ng("log file not found")

    runs = parse_runs(log_path.read_text(encoding="utf-8"))
    observed = observed_run_labels(runs)
    missed = [s for s in expected if s not in observed]
    manual = manual_run_labels(runs)

    if not runs:
        return _ng("log file has no runs", observed=observed, missed=missed, manual=manual)

    last_run = runs[-1]

    # 現在状態チェック（最新実行の品質のみで判定）
    if last_run.exit_code is None:
        return _ng("last run missing exit_code", last_run, observed, missed, manual)
    if last_run.exit_code != 0:
        return _ng(f"last exit_code={last_run.exit_code}", last_run, observed, missed, manual)
    if not last_run.markdown_report_saved:
        return _ng("markdown report not saved", last_run, observed, missed, manual)
    if last_run.should_notify is True and last_run.email_sent is not True:
        reason_str = last_run.email_skipped_reason or "email not sent"
        return _ng(f"email not sent: {reason_str}", last_run, observed, missed, manual)
    if market_data.stale_level == "invalid":
        return _ng(f"market data invalid: {market_data.stale_reason}", last_run, observed, missed, manual)

    # 現在状態はOK。スケジュール取りこぼしと market warning を収集
    warnings: list = []
    for slot in missed:
        warnings.append(f"missed expected run {slot}")
    if market_data.stale_level == "warning":
        warnings.append(f"market data warning: {market_data.stale_reason}")

    if warnings:
        return HealthResult(
            status="WARNING",
            current_state="OK",
            reason=None,
            last_run=last_run,
            expected_runs=expected,
            observed_runs=observed,
            missed_runs=missed,
            manual_runs=manual,
            market_data=market_data,
            schedule_warnings=warnings,
        )

    return HealthResult(
        status="OK",
        current_state="OK",
        reason=None,
        last_run=last_run,
        expected_runs=expected,
        observed_runs=observed,
        missed_runs=[],
        manual_runs=manual,
        market_data=market_data,
        schedule_warnings=[],
    )


def render_health(result: HealthResult) -> str:
    lines = [
        "BTC Alert Health Check",
        f"Status: {result.status}",
        f"Current state: {result.current_state}",
    ]
    if result.reason:
        lines.append(f"Reason: {result.reason}")
    for w in result.schedule_warnings:
        lines.append(f"Schedule warning: {w}")
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
    lines.append(f"Observed scheduled runs: {', '.join(result.observed_runs) if result.observed_runs else '(none)'}")
    if result.missed_runs:
        lines.append(f"Missed runs: {', '.join(result.missed_runs)}")
    if result.manual_runs:
        lines.append(f"Manual/latest run detected: {', '.join(result.manual_runs)}")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(JST)
    result = evaluate_health(now, log_path_for_date(now))
    print(render_health(result))
    # WARNING は現在状態OK（スケジュール取りこぼしのみ）なので exit 0
    return 0 if result.status in ("OK", "WARNING") else 1


if __name__ == "__main__":
    sys.exit(main())
