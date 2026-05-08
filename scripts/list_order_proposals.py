"""注文案の一覧表示。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.order_proposal import DEFAULT_ORDER_PROPOSALS_PATH, list_order_proposals


def parse_args():
    parser = argparse.ArgumentParser(description="注文案一覧")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_ORDER_PROPOSALS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    proposals = list_order_proposals(args.state_path)
    if not proposals:
        print("no proposals")
        return
    for proposal in proposals:
        print(
            f"{proposal['proposal_id']} | {proposal['created_at']} | {proposal['symbol']} | "
            f"{proposal['side']} | {proposal['suggested_price']} | {proposal['suggested_size']} | "
            f"{proposal['estimated_jpy']} | {proposal['source_status']} | {proposal['status']}"
        )


if __name__ == "__main__":
    main()
