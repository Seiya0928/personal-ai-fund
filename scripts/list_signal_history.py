"""シグナル履歴の一覧表示。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.signal_history import DEFAULT_SIGNAL_HISTORY_PATH, list_signal_history


def parse_args():
    parser = argparse.ArgumentParser(description="シグナル履歴一覧")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_SIGNAL_HISTORY_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    signals = list_signal_history(args.state_path)
    if not signals:
        print("no signals")
        return
    for signal in signals[-20:]:
        print(
            f"{signal['signal_id']} | {signal['created_at']} | {signal['symbol']} | "
            f"buy={signal['buy_status']} | hold={signal['hold_status']} | "
            f"notify={signal['should_notify']} | proposal={signal.get('order_proposal_id')}"
        )


if __name__ == "__main__":
    main()
