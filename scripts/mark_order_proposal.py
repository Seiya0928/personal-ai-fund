"""注文案の状態更新。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.order_proposal import (
    ALLOWED_PROPOSAL_STATUSES,
    DEFAULT_ORDER_PROPOSALS_PATH,
    mark_order_proposal,
)


def parse_args():
    parser = argparse.ArgumentParser(description="注文案状態更新")
    parser.add_argument("--id", required=True)
    parser.add_argument("--status", required=True, choices=sorted(ALLOWED_PROPOSAL_STATUSES))
    parser.add_argument("--note", default="")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_ORDER_PROPOSALS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    proposal = mark_order_proposal(
        proposal_id=args.id,
        status=args.status,
        note=args.note,
        path=args.state_path,
    )
    print(f"updated: {proposal['proposal_id']} -> {proposal['status']}")


if __name__ == "__main__":
    main()
