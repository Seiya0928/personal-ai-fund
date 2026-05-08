"""手動ポジションの終了登録。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.manual_positions import DEFAULT_MANUAL_POSITIONS_PATH, close_manual_position


def parse_args():
    parser = argparse.ArgumentParser(description="手動ポジション終了")
    parser.add_argument("--id", required=True)
    parser.add_argument("--exit-price", type=float, required=True)
    parser.add_argument("--exit-date", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_MANUAL_POSITIONS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    position = close_manual_position(
        position_id=args.id,
        exit_price=args.exit_price,
        exit_date=args.exit_date,
        reason=args.reason,
        path=args.state_path,
    )
    print(f"closed: {position['id']}")


if __name__ == "__main__":
    main()
