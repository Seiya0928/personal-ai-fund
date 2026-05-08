#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fx.order_proposal import DEFAULT_FX_ORDER_PROPOSALS_PATH, list_fx_order_proposals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List FX USD/JPY order proposals.")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_FX_ORDER_PROPOSALS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proposals = list_fx_order_proposals(args.state_path)
    if not proposals:
        print("no fx order proposals")
        return
    for proposal in proposals:
        print(
            f"{proposal['proposal_id']} | {proposal['created_at']} | "
            f"{proposal['source_signal_id']} | {proposal['symbol']} | {proposal['side']} | "
            f"{proposal['suggested_price']} | size={proposal['suggested_size']} | "
            f"max_loss_jpy={proposal['max_loss_jpy']} | {proposal['status']}"
        )


if __name__ == "__main__":
    main()
