#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.alerts.dry_run_orders import DEFAULT_DRY_RUN_ORDERS_PATH
from src.alerts.order_proposal import DEFAULT_ORDER_PROPOSALS_PATH
from src.fx.order_proposal import DEFAULT_FX_ORDER_PROPOSALS_PATH
from src.reports.order_proposal_report import (
    DEFAULT_DAILY_ORDER_PROPOSAL_REPORTS_DIR,
    collect_daily_order_proposals,
    render_daily_order_proposal_report,
    save_daily_order_proposal_report,
)
from src.risk.execution_gate import DEFAULT_STOP_TRADING_FILE

JST = ZoneInfo("Asia/Tokyo")


def _env_true(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def ensure_read_only_dry_run() -> None:
    if not _env_true("DRY_RUN", True):
        raise RuntimeError("daily proposal report requires DRY_RUN=true")
    if not _env_true("READ_ONLY", True):
        raise RuntimeError("daily proposal report requires READ_ONLY=true")


def stop_trading_active(stop_trading_file: Path) -> bool:
    return _env_true("STOP_TRADING", False) or stop_trading_file.exists()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List BTC/FX daily order proposals and write a markdown report.")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(JST).date())
    parser.add_argument("--dry-run-orders-path", type=Path, default=DEFAULT_DRY_RUN_ORDERS_PATH)
    parser.add_argument("--btc-order-proposals-path", type=Path, default=DEFAULT_ORDER_PROPOSALS_PATH)
    parser.add_argument("--fx-order-proposals-path", type=Path, default=DEFAULT_FX_ORDER_PROPOSALS_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_DAILY_ORDER_PROPOSAL_REPORTS_DIR)
    parser.add_argument("--stop-trading-file", type=Path, default=DEFAULT_STOP_TRADING_FILE)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ensure_read_only_dry_run()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    stopped = stop_trading_active(args.stop_trading_file)
    proposals = collect_daily_order_proposals(
        target_date=args.date,
        dry_run_orders_path=args.dry_run_orders_path,
        btc_order_proposals_path=args.btc_order_proposals_path,
        fx_order_proposals_path=args.fx_order_proposals_path,
        stop_trading_active=stopped,
    )
    content = render_daily_order_proposal_report(
        proposals,
        target_date=args.date,
        generated_at=datetime.now(JST),
        stop_trading_active=stopped,
    )
    print(content)
    if not args.no_write:
        path = save_daily_order_proposal_report(content, target_date=args.date, reports_dir=args.reports_dir)
        print(f"report_path: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
