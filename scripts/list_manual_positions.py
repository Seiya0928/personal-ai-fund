"""手動ポジションの一覧表示。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.manual_positions import DEFAULT_MANUAL_POSITIONS_PATH, list_manual_positions


def parse_args():
    parser = argparse.ArgumentParser(description="手動ポジション一覧")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_MANUAL_POSITIONS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    positions = list_manual_positions(args.state_path)
    if not positions:
        print("no positions")
        return
    for position in positions:
        print(
            f"{position['id']} | {position['symbol']} | {position['entry_date']} | "
            f"{position['entry_price']} | {position['position_size']} | {position['status']} | "
            f"{position.get('note', '')}"
        )


if __name__ == "__main__":
    main()
