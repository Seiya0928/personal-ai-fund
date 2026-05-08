"""注文案から半自動 DRY_RUN 注文記録を作成する。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.dry_run_orders import (
    DEFAULT_DRY_RUN_ORDERS_PATH,
    DRY_RUN_ORDER_APPROVAL_PHRASE,
    record_dry_run_order_from_proposal,
)
from src.alerts.order_proposal import DEFAULT_ORDER_PROPOSALS_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="注文案から DRY_RUN 注文記録を作成")
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--order-proposals-path", type=Path, default=DEFAULT_ORDER_PROPOSALS_PATH)
    parser.add_argument("--dry-run-orders-path", type=Path, default=DEFAULT_DRY_RUN_ORDERS_PATH)
    parser.add_argument("--yes-i-understand-dry-run-only", action="store_true")
    return parser.parse_args()


def _env_true(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def _approval_phrase(args: argparse.Namespace) -> str:
    if args.yes_i_understand_dry_run_only:
        return DRY_RUN_ORDER_APPROVAL_PHRASE
    print("This records a DRY_RUN order only. No exchange order is sent.")
    typed = input("Type approval phrase: ")
    return typed.strip()


def main() -> int:
    load_dotenv()
    args = parse_args()
    try:
        record, order_body = record_dry_run_order_from_proposal(
            proposal_id=args.proposal_id,
            approval_phrase=_approval_phrase(args),
            dry_run=_env_true("DRY_RUN", True),
            read_only=_env_true("READ_ONLY", True),
            order_proposals_path=args.order_proposals_path,
            dry_run_orders_path=args.dry_run_orders_path,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("DRY_RUN order recorded. No exchange order sent.")
    print(f"dry_run_order_id: {record['dry_run_order_id']}")
    print(f"source_order_proposal_id: {record['source_order_proposal_id']}")
    print("order_body:")
    print(f"  symbol: {order_body['symbol']}")
    print(f"  side: {order_body['side']}")
    print(f"  executionType: {order_body['executionType']}")
    print(f"  price: \"{order_body['price']}\"")
    print(f"  size: \"{order_body['size']}\"")
    print(f"state_path: {args.dry_run_orders_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
