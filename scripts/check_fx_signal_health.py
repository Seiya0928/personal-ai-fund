#!/usr/bin/env python
"""
FX シグナル健全性チェック。
BTC の check_btc_alert_health.py と同じ思想で、
state/fx_signal_history.json を読み込んで状態を表示する。
実注文なし・研究用のみ。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fx.fx_signal_history import load_fx_signal_history, DEFAULT_FX_SIGNAL_HISTORY_PATH
from src.fx.fx_stale_checker import check_stale
from src.fx.order_proposal import load_fx_order_proposals, DEFAULT_FX_ORDER_PROPOSALS_PATH
from src.fx.fx_paper_trade import load_fx_paper_trades, DEFAULT_FX_PAPER_TRADES_PATH

JST = ZoneInfo("Asia/Tokyo")
EXPECTED_RUNS_PER_DAY = 3  # 00:00, 06:00, 12:00 JST


def _today_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def main() -> None:
    now_jst = datetime.now(JST)

    # fx_signal_history.json を読む
    history = load_fx_signal_history(DEFAULT_FX_SIGNAL_HISTORY_PATH)
    signals = history.get("signals", [])

    if not signals:
        print("Status: NG")
        print("Last run: (なし)")
        print("FX status: (なし)")
        print("Market data timestamp: (なし)")
        print("Market data age: -")
        print("Stale level: -")
        print("Stale reason: -")
        print("Latest signal id: (なし)")
        _print_counts(0, 0)
        return

    last = signals[-1]
    last_run = last.get("created_at", "")
    fx_status = last.get("fx_status", "")
    market_ts = last.get("market_data_timestamp", "")
    stale_level = last.get("stale_level", "")
    stale_reason = last.get("stale_reason", "")
    signal_id = last.get("signal_id", "")

    # 市場データの経過時間
    if market_ts:
        stale_result = check_stale(market_ts, now=now_jst)
        age_str = f"{stale_result.age_hours:.1f}h"
        stale_level = stale_result.level
        stale_reason = stale_result.reason
    else:
        age_str = "-"

    # 今日の実行回数
    today = _today_jst()
    runs_today = sum(
        1 for s in signals
        if (s.get("created_at") or "").startswith(today)
    )

    # proposal 件数
    try:
        proposals = load_fx_order_proposals(DEFAULT_FX_ORDER_PROPOSALS_PATH)["proposals"]
        proposal_count = len(proposals)
    except Exception:
        proposal_count = 0

    # open paper trades 件数
    try:
        paper_trades = load_fx_paper_trades(DEFAULT_FX_PAPER_TRADES_PATH)["paper_trades"]
        open_trades = sum(1 for t in paper_trades if t.get("status") == "open")
    except Exception:
        open_trades = 0

    # 全体 status
    overall_status = "OK" if stale_level != "invalid" else "NG"

    print(f"Status: {overall_status}")
    print(f"Last run: {last_run}")
    print(f"FX status: {fx_status}")
    print(f"Market data timestamp: {market_ts}")
    print(f"Market data age: {age_str}")
    print(f"Stale level: {stale_level}")
    print(f"Stale reason: {stale_reason}")
    print(f"Latest signal id: {signal_id}")
    _print_counts(proposal_count, open_trades)
    print(f"Expected runs today: {EXPECTED_RUNS_PER_DAY} (00:00, 06:00, 12:00 JST as configured)")
    print(f"Observed runs today: {runs_today}")


def _print_counts(proposal_count: int, open_trades: int) -> None:
    print(f"Proposal count: {proposal_count}")
    print(f"Open paper trades: {open_trades}")


if __name__ == "__main__":
    main()
