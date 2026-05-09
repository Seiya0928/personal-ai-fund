"""
FX Watch Candidate シグナルの事後評価スクリプト
実注文なし・研究用のみ

目的:
- state/fx_watch_signals.json に保存済みのシグナルを読み込み
- 最新 H1 データで TP/SL 到達判定を行う
- 評価結果を更新保存し、集計レポートを生成する

使用方法:
    python scripts/evaluate_fx_watch_signals.py
    python scripts/evaluate_fx_watch_signals.py --timeout-bars 48
    python scripts/evaluate_fx_watch_signals.py --save     # 評価結果を上書き保存

制約:
- 実注文API・成行注文・指値注文・決済注文は一切実装しない
- OrderProposal・DRY_RUN注文には昇格しない
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.strategy_candidate import (
    DEFAULT_WATCH_SIGNALS_PATH,
    list_watch_signals,
    save_watch_signals,
    watch_signal_from_dict,
    watch_signal_to_dict,
)
from src.fx.watch_signal_evaluator import (
    aggregate_evaluation,
    evaluate_all_signals,
    render_evaluation_report,
)
from src.utils.logger import get_logger

log = get_logger(__name__)
REPORTS_DIR = _PROJECT_ROOT / "reports"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FX Watch Candidate 事後評価（実注文なし・研究用のみ）"
    )
    parser.add_argument(
        "--timeout-bars",
        type=int,
        default=24,
        help="タイムアウト本数: 指定本数経過しても未到達なら timeout 扱い (default: 24)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="評価結果を state/fx_watch_signals.json に更新保存する",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("FX Watch Candidate 事後評価")
    print("実注文なし・研究用のみ")
    print("=" * 60)

    # H1 データ読み込み
    fetcher = YFinanceFetcher()
    df_h1 = fetcher.load_latest("H1")
    if df_h1.empty:
        print("[ERROR] H1データが見つかりません。先に fetch_fx_ohlcv_longterm.py を実行してください。")
        return 1

    print(f"H1データ: {len(df_h1):,} 行")

    # シグナル読み込み
    raw = list_watch_signals(DEFAULT_WATCH_SIGNALS_PATH)
    if not raw:
        print("シグナルが見つかりません。先に run_fx_watch_candidate.py --save を実行してください。")
        return 0

    signals = [watch_signal_from_dict(d) for d in raw]
    print(f"シグナル読み込み: {len(signals)} 件")

    open_before = sum(1 for s in signals if s.status == "open")
    print(f"  うち open: {open_before} 件")

    # 評価
    evaluated = evaluate_all_signals(signals, df_h1, timeout_bars=args.timeout_bars)
    stats = aggregate_evaluation(evaluated)

    print(f"\n評価結果:")
    print(f"  actionable: {stats['actionable_signals']} 件 (buy={stats['buy_count']}, sell={stats['sell_count']})")
    print(f"  tp_hit    : {stats['tp_hit']} 件")
    print(f"  sl_hit    : {stats['sl_hit']} 件")
    print(f"  timeout   : {stats['timeout']} 件")
    print(f"  ambiguous : {stats['ambiguous']} 件")
    print(f"  open      : {stats['open']} 件")
    if stats["win_rate"] is not None:
        print(f"  win_rate  : {stats['win_rate'] * 100:.1f}%")
    if stats["avg_mfe"] is not None:
        print(f"  avg_mfe   : {stats['avg_mfe']:.2f} pips")
    if stats["avg_mae"] is not None:
        print(f"  avg_mae   : {stats['avg_mae']:.2f} pips")

    # 保存
    if args.save:
        payload = {"signals": [watch_signal_to_dict(s) for s in evaluated]}
        save_watch_signals(payload, DEFAULT_WATCH_SIGNALS_PATH)
        print(f"\n[保存済み] {DEFAULT_WATCH_SIGNALS_PATH}")

    # レポート生成
    generated_at = datetime.now(timezone.utc)
    report = render_evaluation_report(evaluated, generated_at, timeout_bars=args.timeout_bars)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    datestr = generated_at.strftime("%Y%m%d")
    report_path = REPORTS_DIR / f"fx_watch_candidate_evaluation_{datestr}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nレポート保存: {report_path}")

    print("\n--- レポート先頭 (25行) ---")
    for line in report.splitlines()[:25]:
        print(line)
    print("...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
