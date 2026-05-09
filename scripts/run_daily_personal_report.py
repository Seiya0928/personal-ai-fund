"""
FX Watch Candidate 日次ワークフロー
実注文なし・研究用のみ

使用方法:
    python scripts/run_daily_personal_report.py
    python scripts/run_daily_personal_report.py --save-watch-signal --evaluate-watch-signals
    python scripts/run_daily_personal_report.py --save-watch-signal --evaluate-watch-signals --timeout-bars 48
    python scripts/run_daily_personal_report.py --report-date 20260509

制約:
    - 実注文API、成行注文、指値注文、決済注文は一切実装しない
    - OrderProposal化・DRY_RUN注文化は行わない
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.fx.candidate_signal_runner import run_candidate_signal
from src.fx.daily_watch_workflow import (
    compute_unresolved_count,
    compute_watch_eval_stats,
    get_ohlcv_data,
    load_safety_flags,
)
from src.fx.strategy_candidate import (
    DEFAULT_WATCH_SIGNALS_PATH,
    save_watch_signal,
    watch_signal_from_dict,
)
from src.fx.watch_signal_evaluator import (
    aggregate_evaluation,
    evaluate_all_signals,
    render_evaluation_report,
)
from src.proposals.common_proposal import common_proposal_from_dict
from src.proposals.storage import DEFAULT_COMMON_PROPOSALS_PATH, list_common_proposals
from src.reports.daily_personal_report import (
    render_daily_personal_report,
    save_daily_personal_report,
)

JST = ZoneInfo("Asia/Tokyo")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FX Watch Candidate 日次ワークフロー（実注文なし・研究用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--save-watch-signal",
        action="store_true",
        help="生成したシグナルを state/fx_watch_signals.json に保存する",
    )
    parser.add_argument(
        "--evaluate-watch-signals",
        action="store_true",
        help="過去の open シグナルを評価し、TP/SL/timeout を判定して保存する",
    )
    parser.add_argument(
        "--timeout-bars",
        type=int,
        default=24,
        metavar="N",
        help="シグナル評価のタイムアウト本数（デフォルト: 24）",
    )
    parser.add_argument(
        "--report-date",
        type=str,
        default=None,
        metavar="YYYYMMDD",
        help="レポート対象日（省略時は今日）",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # --- 対象日 ---
    if args.report_date:
        try:
            target_date = datetime.strptime(args.report_date, "%Y%m%d").date()
        except ValueError:
            print(f"[ERROR] --report-date の形式が不正です: {args.report_date} (YYYYMMDD が必要)")
            sys.exit(0)
    else:
        target_date = date.today()

    generated_at = datetime.now(JST)

    print(f"[INFO] FX Watch Candidate 日次ワークフロー開始 target_date={target_date}")
    print("[INFO] 実注文なし・研究用のみ")

    # --- 安全フラグ ---
    stop_trading_active, dry_run, read_only = load_safety_flags()
    print(
        f"[INFO] 安全フラグ: STOP_TRADING={stop_trading_active}, DRY_RUN={dry_run}, READ_ONLY={read_only}"
    )

    # --- Step 1: H1/D1 データ読み込み ---
    print("[STEP 1] H1/D1 OHLCV データを読み込み中...")
    try:
        df_h1, df_d1 = get_ohlcv_data()
        print(f"  H1: {len(df_h1)} 本, D1: {len(df_d1)} 本")
    except Exception as exc:
        print(f"[WARN] OHLCV データ読み込み失敗: {exc}")
        import pandas as pd
        df_h1 = pd.DataFrame()
        df_d1 = pd.DataFrame()

    # --- Step 2: FX Watch Candidate シグナル生成 ---
    watch_signal = None
    if df_h1.empty:
        print("[STEP 2] H1 データが空のためシグナル生成をスキップします")
    else:
        print("[STEP 2] FX Watch Candidate シグナルを生成中...")
        try:
            watch_signal = run_candidate_signal(df_h1, df_d1)
            print(
                f"  action={watch_signal.action}, price={watch_signal.current_price:.4f},"
                f" trend={watch_signal.trend_direction}"
            )
        except Exception as exc:
            print(f"[WARN] シグナル生成失敗: {exc}")

    # --- Step 3: シグナル保存 (--save-watch-signal) ---
    if args.save_watch_signal and watch_signal is not None:
        print("[STEP 3] シグナルを state/fx_watch_signals.json に保存中...")
        try:
            _, is_new = save_watch_signal(watch_signal)
            if is_new:
                print(f"  保存完了: signal_id={watch_signal.signal_id}")
            else:
                print(f"  重複スキップ: signal_id={watch_signal.signal_id}")
        except Exception as exc:
            print(f"[WARN] シグナル保存失敗: {exc}")
    elif args.save_watch_signal:
        print("[STEP 3] シグナルがないため保存をスキップします")
    else:
        print("[STEP 3] --save-watch-signal 未指定のため保存をスキップします")

    # --- Step 4: 過去シグナル評価 (--evaluate-watch-signals) ---
    watch_eval_stats: dict = {}
    if args.evaluate_watch_signals:
        print(f"[STEP 4] 過去 open シグナルを評価中 (timeout_bars={args.timeout_bars})...")
        try:
            from src.fx.strategy_candidate import (
                list_watch_signals,
                save_watch_signals,
                watch_signal_from_dict,
                watch_signal_to_dict,
            )
            raw_list = list_watch_signals()
            if not raw_list:
                print("  シグナルが存在しません")
            else:
                all_signals = [watch_signal_from_dict(d) for d in raw_list]
                if df_h1.empty:
                    print("[WARN] H1 データが空のため評価をスキップします")
                else:
                    evaluated = evaluate_all_signals(all_signals, df_h1, timeout_bars=args.timeout_bars)

                    # 状態が変わったシグナルを保存
                    updated_payload: dict = {"signals": [watch_signal_to_dict(s) for s in evaluated]}
                    save_watch_signals(updated_payload)

                    watch_eval_stats = aggregate_evaluation(evaluated)
                    print(
                        f"  評価完了: tp_hit={watch_eval_stats.get('tp_hit', 0)},"
                        f" sl_hit={watch_eval_stats.get('sl_hit', 0)},"
                        f" open={watch_eval_stats.get('open', 0)}"
                    )

                    # 評価レポート保存
                    try:
                        eval_report = render_evaluation_report(
                            evaluated, generated_at, timeout_bars=args.timeout_bars
                        )
                        reports_dir = _PROJECT_ROOT / "reports"
                        reports_dir.mkdir(parents=True, exist_ok=True)
                        eval_path = reports_dir / f"fx_watch_candidate_evaluation_{target_date.strftime('%Y%m%d')}.md"
                        eval_path.write_text(eval_report, encoding="utf-8")
                        print(f"  評価レポート保存: {eval_path}")
                    except Exception as exc:
                        print(f"[WARN] 評価レポート保存失敗: {exc}")
        except Exception as exc:
            print(f"[WARN] シグナル評価失敗: {exc}")
    else:
        print("[STEP 4] --evaluate-watch-signals 未指定のため評価をスキップします")
        # 保存済み評価 stats を読み込む
        try:
            watch_eval_stats = compute_watch_eval_stats()
        except Exception as exc:
            print(f"[WARN] 評価 stats 読み込み失敗: {exc}")

    # --- Step 5: 提案読み込み ---
    print("[STEP 5] 提案を state/common_proposals.json から読み込み中...")
    proposals = []
    try:
        raw_proposals = list_common_proposals()
        proposals = [common_proposal_from_dict(d) for d in raw_proposals]
        print(f"  提案件数: {len(proposals)}")
    except FileNotFoundError:
        print("  common_proposals.json が存在しません（提案なし）")
    except Exception as exc:
        print(f"[WARN] 提案読み込み失敗: {exc}")

    # --- Step 6: Daily Personal Report 生成・保存 ---
    print("[STEP 6] Daily Personal Report を生成中...")
    try:
        unresolved_count = compute_unresolved_count()
    except Exception as exc:
        print(f"[WARN] unresolved カウント取得失敗: {exc}")
        unresolved_count = 0

    watch_signals_for_report = [watch_signal] if watch_signal is not None else []

    try:
        content = render_daily_personal_report(
            proposals,
            target_date=target_date,
            generated_at=generated_at,
            stop_trading_active=stop_trading_active,
            dry_run=dry_run,
            read_only=read_only,
            watch_signals=watch_signals_for_report,
            watch_unresolved_count=unresolved_count,
            watch_eval_stats=watch_eval_stats or None,
        )
        report_path = save_daily_personal_report(content, target_date=target_date)
        print(f"  レポート保存完了: {report_path}")
    except Exception as exc:
        print(f"[ERROR] レポート生成失敗: {exc}")

    print("[INFO] ワークフロー完了")


if __name__ == "__main__":
    main()
