"""paper trade ルール別成績の表示。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.paper_trades import DEFAULT_PAPER_TRADES_PATH, summarize_paper_performance


def parse_args():
    parser = argparse.ArgumentParser(description="paper trade 成績レポート")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PAPER_TRADES_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    summaries = summarize_paper_performance(args.state_path)
    for summary in summaries:
        print(
            f"{summary['rule_id']} | trades={summary['trades']} | open={summary['open']} | "
            f"closed={summary['closed']} | win_rate={summary['win_rate']:.2f}% | "
            f"total_pnl_jpy=¥{summary['total_pnl_jpy']:,.2f} | avg_pnl_pct={summary['avg_pnl_pct']:+.2f}% | "
            f"max_drawdown_pct={summary['max_drawdown_pct']:.2f}% | avg_holding_days={summary['avg_holding_days']:.1f} | "
            f"take_profit={summary['take_profit_count']} | stop_loss={summary['stop_loss_count']} | timeout={summary['timeout_count']}"
        )


if __name__ == "__main__":
    main()
