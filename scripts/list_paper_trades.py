"""paper trade の一覧表示。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.paper_trades import DEFAULT_PAPER_TRADES_PATH, list_paper_trades


def parse_args():
    parser = argparse.ArgumentParser(description="paper trade 一覧")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PAPER_TRADES_PATH)
    parser.add_argument("--status", choices=["open", "closed"])
    parser.add_argument("--rule")
    return parser.parse_args()


def main():
    args = parse_args()
    trades = list_paper_trades(args.state_path, status=args.status, rule_id=args.rule)
    if not trades:
        print("no paper trades")
        return
    for trade in trades:
        print(
            f"{trade['paper_trade_id']} | {trade['rule_id']} | {trade['symbol']} | "
            f"{trade['status']} | entry={trade['entry_price']} | pnl_pct={trade.get('pnl_pct', 0.0):+.2f}% | "
            f"holding_days={trade.get('holding_days', 0)} | exit_reason={trade.get('exit_reason')}"
        )


if __name__ == "__main__":
    main()
