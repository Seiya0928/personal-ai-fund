"""
USD/JPY watch_candidate シグナル確認 CLI
実注文なし・研究用のみ

使用方法:
    python scripts/run_fx_watch_candidate.py
    python scripts/run_fx_watch_candidate.py --save   # state/fx_watch_signals.json に保存

出力:
    action, current_price, trend_direction, breakout_level,
    stop_loss, take_profit, risk_pips, reward_pips, rr_ratio,
    reason, data_timestamp

制約:
    - OrderProposal・DRY_RUN注文には昇格しない
    - 実注文APIは一切呼ばない
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.fx.candidate_signal_runner import run_candidate_signal
from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.strategy_candidate import (
    USDJPY_PRIMARY_CANDIDATE,
    save_watch_signal,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def _fmt(val: object, decimals: int = 4) -> str:
    if val is None:
        return "n/a"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def print_signal(sig) -> None:
    print("=" * 60)
    print("FX Watch Candidate シグナル（観察専用・実注文なし）")
    print("=" * 60)
    print(f"  strategy     : {sig.strategy_name}")
    print(f"  signal_id    : {sig.signal_id}")
    print(f"  action       : {sig.action.upper()}")
    print(f"  current_price: {_fmt(sig.current_price)}")
    print(f"  trend        : {sig.trend_direction}")
    print(f"  breakout_lvl : {_fmt(sig.breakout_level)}")
    print(f"  stop_loss    : {_fmt(sig.stop_loss)}")
    print(f"  take_profit  : {_fmt(sig.take_profit)}")
    print(f"  risk_pips    : {_fmt(sig.risk_pips, 1)} pips" if sig.risk_pips is not None else "  risk_pips    : n/a")
    print(f"  reward_pips  : {_fmt(sig.reward_pips, 1)} pips" if sig.reward_pips is not None else "  reward_pips  : n/a")
    print(f"  rr_ratio     : {_fmt(sig.rr_ratio, 2)}")
    print(f"  reason       : {sig.reason}")
    print(f"  data_ts(UTC) : {sig.data_timestamp}")
    print(f"  created_at   : {sig.created_at}")
    print("=" * 60)
    print("注意: 実注文・OrderProposal・DRY_RUN注文には昇格しない")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="USD/JPY watch_candidate シグナル確認（実注文なし）"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="state/fx_watch_signals.json にシグナルを保存する",
    )
    args = parser.parse_args()

    fetcher = YFinanceFetcher()
    df_h1 = fetcher.load_latest("H1")
    df_d1 = fetcher.load_latest("D1")

    if df_h1.empty:
        print("[ERROR] H1データが見つかりません。先に fetch_fx_ohlcv_longterm.py を実行してください。")
        return 1
    if df_d1.empty:
        print("[WARN] D1データが見つかりません。H1からリサンプルします。")
        from src.fx.data_loader import FXDataLoader
        import pandas as pd
        loader = FXDataLoader()
        df_d1 = loader.resample(df_h1, to="1D")
        if "timestamp" in df_d1.columns:
            df_d1["timestamp"] = pd.to_datetime(df_d1["timestamp"], utc=True)

    sig = run_candidate_signal(df_h1, df_d1, config=USDJPY_PRIMARY_CANDIDATE)
    print_signal(sig)

    if args.save:
        stored, is_new = save_watch_signal(sig)
        if is_new:
            print(f"\n[保存済み] {sig.signal_id}")
        else:
            print(f"\n[スキップ] 既存シグナル: {sig.signal_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
