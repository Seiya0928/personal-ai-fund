"""手動購入したポジションを state/manual_positions.json に登録する。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.manual_positions import DEFAULT_MANUAL_POSITIONS_PATH, add_manual_position


def parse_args():
    parser = argparse.ArgumentParser(description="手動ポジション登録")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--entry-price", type=float, required=True)
    parser.add_argument("--entry-date", required=True)
    parser.add_argument("--position-size", type=float, required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_MANUAL_POSITIONS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    position = add_manual_position(
        symbol=args.symbol,
        entry_price=args.entry_price,
        entry_date=args.entry_date,
        position_size=args.position_size,
        note=args.note,
        path=args.state_path,
    )
    print(f"added: {position['id']}")


if __name__ == "__main__":
    main()
