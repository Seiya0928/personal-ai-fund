"""DRY_RUN 注文記録の一覧表示。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.dry_run_orders import DEFAULT_DRY_RUN_ORDERS_PATH, list_dry_run_orders


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DRY_RUN 注文記録一覧")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_DRY_RUN_ORDERS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    orders = list_dry_run_orders(args.state_path)
    if not orders:
        print("no dry run orders")
        return
    for order in orders:
        print(
            f"{order['dry_run_order_id']} | {order['created_at']} | "
            f"{order['source_order_proposal_id']} | {order['symbol']} | "
            f"{order['gmo_spot_symbol']} | {order['side']} | {order['price']} | "
            f"{order['size']} | {order['estimated_jpy']} | {order['status']}"
        )


if __name__ == "__main__":
    main()
