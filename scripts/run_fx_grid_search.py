"""
USD/JPY EMAトレンドフォロー戦略 グリッドサーチ実行スクリプト
実注文なし・研究用のみ

DRY_RUN / READ_ONLY 設計:
  - 実注文 API は一切呼ばない
  - 保存済みCSVデータを読み込んでグリッドサーチのみ実行
  - 結果は reports/ ディレクトリに Markdown で保存するのみ
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fx.data_loader import FXDataLoader
from src.fx.fx_backtest import FXBacktestRunner
from src.fx.grid_search import FXGridSearch, GridSearchConfig, GridSearchResult
from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.utils.logger import get_logger

log = get_logger(__name__)

JST_OFFSET = 9 * 3600  # UTC+9


def _jst_now() -> str:
    now_utc = datetime.now(timezone.utc)
    jst_ts = now_utc.timestamp() + JST_OFFSET
    dt_jst = datetime.utcfromtimestamp(jst_ts)
    return dt_jst.strftime("%Y-%m-%d %H:%M JST")


def _result_row(rank: int, r: GridSearchResult) -> str:
    p = r.params
    pf_str = f"{r.val.profit_factor:.2f}" if r.val.profit_factor != float("inf") else "inf"
    return (
        f"| {rank} | {r.direction} | {p['ema_fast']} | {p['ema_slow']} | "
        f"{p['breakout_lookback']} | {p['atr_sl_multiplier']} | {p['rr_ratio']} | "
        f"{r.train.profit_factor:.2f} | {pf_str} | "
        f"{r.val.max_drawdown_pct:.2f}% | {r.val.trade_count} | "
        f"{r.val.win_rate * 100:.1f}% |"
    )


def _test_row(rank: int, r: GridSearchResult) -> str:
    t = r.test
    if t is None:
        return f"| {rank} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
    pf_str = f"{t.profit_factor:.2f}" if t.profit_factor != float("inf") else "inf"
    p = r.params
    return (
        f"| {rank} | {t.total_return_pct:+.2f}% | {pf_str} | "
        f"{t.max_drawdown_pct:.2f}% | {t.trade_count} | "
        f"{t.avg_mfe_pips:.1f} | {t.avg_mae_pips:.1f} | "
        f"{t.failed_after_half_tp_count} |"
    )


def build_report(
    results: list[GridSearchResult],
    grid_search: FXGridSearch,
    df_m15: "pd.DataFrame",
    df_h4: "pd.DataFrame",
    skipped_invalid: int,
    skipped_trade_count: int,
) -> str:
    import pandas as pd

    n_total = len(results)
    passes = [r for r in results if r.passes_val_filter]
    n_pass = len(passes)
    n_invalid = skipped_invalid

    ts_m15_start = df_m15["timestamp"].min()
    ts_m15_end = df_m15["timestamp"].max()

    cfg = grid_search.config
    total_combos_raw = (
        len(cfg.ema_fast_list) * len(cfg.ema_slow_list)
        * len(cfg.breakout_lookback_list) * len(cfg.atr_sl_multiplier_list)
        * len(cfg.rr_ratio_list) * len(cfg.direction_list)
    )

    lines: list[str] = []
    lines.append("# USD/JPY EMA グリッドサーチ結果")
    lines.append(f"生成日時: {_jst_now()}")
    lines.append(f"M15データ: {len(df_m15)}本 ({ts_m15_start} 〜 {ts_m15_end})")
    lines.append(f"H4データ:  {len(df_h4)}本")
    lines.append("")
    lines.append("## 検索概要")
    lines.append(f"- パラメータ組み合わせ総数（direction含む）: {total_combos_raw}")
    lines.append(f"- fast >= slow で除外: {n_invalid}")
    lines.append(f"- train trade_count < {cfg.min_trade_count} で除外: {skipped_trade_count}")
    lines.append(f"- 評価した組み合わせ: {n_total}")
    lines.append(f"- val フィルター通過: {n_pass} / {n_total}")
    lines.append("")
    lines.append("## 上位候補（val profit_factor 順）")
    lines.append(
        "| rank | direction | ema_fast | ema_slow | lookback | atr_sl | rr | "
        "train_pf | val_pf | val_mdd | val_trades | val_win_rate |"
    )
    lines.append(
        "|------|-----------|----------|----------|----------|--------|----|"
        "----------|--------|---------|------------|--------------|"
    )
    top10 = results[:10]
    for rank, r in enumerate(top10, 1):
        lines.append(_result_row(rank, r))

    lines.append("")
    lines.append("## フィルター通過候補のTEST結果")
    if passes:
        lines.append(
            "| rank | test_return | test_pf | test_mdd | test_trades | avg_mfe | avg_mae | failed_half_tp |"
        )
        lines.append(
            "|------|-------------|---------|----------|-------------|---------|---------|----------------|"
        )
        for rank, r in enumerate(passes[:10], 1):
            lines.append(_test_row(rank, r))
    else:
        lines.append("フィルター通過候補なし。")

    lines.append("")
    lines.append("## MFE/MAE分析（全候補の平均）")

    if results:
        all_win_mfe = [r.val.avg_mfe_win_pips for r in results if r.val.trade_count > 0]
        all_win_mae = [r.val.avg_mae_win_pips for r in results if r.val.trade_count > 0]
        all_lose_mfe = [r.val.avg_mfe_lose_pips for r in results if r.val.trade_count > 0]
        all_lose_mae = [r.val.avg_mae_lose_pips for r in results if r.val.trade_count > 0]

        def smean(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        total_lose = sum(
            r.val.trade_count - round(r.val.win_rate * r.val.trade_count)
            for r in results
        )
        total_failed_half = sum(r.val.failed_after_half_tp_count for r in results)
        pct_failed = total_failed_half / total_lose * 100 if total_lose > 0 else 0.0

        lines.append(f"- 勝ちトレード: 平均MFE={smean(all_win_mfe):.1f}pips, 平均MAE={smean(all_win_mae):.1f}pips")
        lines.append(f"- 負けトレード: 平均MFE={smean(all_lose_mfe):.1f}pips, 平均MAE={smean(all_lose_mae):.1f}pips")
        lines.append(
            f"- 一度TP50%以上まで届いて損切りになったトレード: {total_failed_half}件 "
            f"(全負けの {pct_failed:.1f}%)"
        )
    else:
        lines.append("分析データなし。")

    lines.append("")
    lines.append("## 失敗パターン分析")
    failed_half_results = [
        r for r in results if r.val.failed_after_half_tp_count > 0
    ]
    if failed_half_results:
        top_failed = sorted(
            failed_half_results,
            key=lambda r: r.val.failed_after_half_tp_count,
            reverse=True,
        )[:5]
        lines.append("TP50%達後に損切りが多いパラメータ（上位5件）:")
        for r in top_failed:
            p = r.params
            lines.append(
                f"- ema_fast={p['ema_fast']}, ema_slow={p['ema_slow']}, "
                f"lookback={p['breakout_lookback']}, atr_sl={p['atr_sl_multiplier']}, "
                f"rr={p['rr_ratio']}, direction={r.direction} → "
                f"failed_half_tp={r.val.failed_after_half_tp_count}件"
            )
    else:
        lines.append("TP50%以上達後に損切りになったパターンなし。")

    lines.append("")
    lines.append("## 結論")
    if passes:
        top = passes[0]
        p = top.params
        lines.append(
            f"- valフィルター通過の最良候補: direction={top.direction}, "
            f"ema_fast={p['ema_fast']}, ema_slow={p['ema_slow']}, "
            f"breakout_lookback={p['breakout_lookback']}, "
            f"atr_sl_multiplier={p['atr_sl_multiplier']}, rr_ratio={p['rr_ratio']}"
        )
        lines.append(f"  - val profit_factor={top.val.profit_factor:.2f}, mdd={top.val.max_drawdown_pct:.2f}%")
        if top.test is not None:
            lines.append(
                f"  - test profit_factor={top.test.profit_factor:.2f}, "
                f"return={top.test.total_return_pct:+.2f}%, mdd={top.test.max_drawdown_pct:.2f}%"
            )
    else:
        lines.append("- valフィルター通過候補なし。パラメータ範囲・フィルター条件の見直しを推奨。")

    lines.append("")
    lines.append("---")
    lines.append("*実注文なし・研究用のみ (DRY_RUN / READ_ONLY 設計)*")

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("[GRID SEARCH] USD/JPY EMA Strategy")
    print("READ_ONLY: 実注文 API は一切呼びません")
    print("=" * 60)

    fetcher = YFinanceFetcher()
    loader = FXDataLoader()

    # --- 1. M15 データ読み込み ---
    print("\n[M15] データ読み込み中...")
    df_m15 = fetcher.load_latest("M15")
    if df_m15.empty:
        print("[ERROR] M15 データが見つかりません。先に run_fx_backtest_real.py を実行してください。")
        sys.exit(1)
    print(f"[M15] {len(df_m15)}本 ({df_m15['timestamp'].min()} 〜 {df_m15['timestamp'].max()})")

    # --- 2. H4 データを M15 からリサンプル生成 ---
    print("\n[H4] M15 → H4 リサンプル中...")
    df_h4_full = loader.resample(df_m15, to="4h")
    print(f"[H4] {len(df_h4_full)}本")

    # --- 3. M15 を train(60%)/val(20%)/test(20%) に分割 ---
    df_m15_train, df_m15_val, df_m15_test = FXBacktestRunner.split(
        df_m15, train=0.6, val=0.2, test=0.2
    )
    print(f"\nデータ分割: train={len(df_m15_train)}, val={len(df_m15_val)}, test={len(df_m15_test)}")

    # --- 4. グリッドサーチ設定 ---
    config = GridSearchConfig()
    grid_search = FXGridSearch(config=config)

    # --- 5. グリッドサーチ実行 ---
    print("\n[GridSearch] 開始...")
    print(f"  ema_fast_list: {config.ema_fast_list}")
    print(f"  ema_slow_list: {config.ema_slow_list}")
    print(f"  breakout_lookback_list: {config.breakout_lookback_list}")
    print(f"  atr_sl_multiplier_list: {config.atr_sl_multiplier_list}")
    print(f"  rr_ratio_list: {config.rr_ratio_list}")
    print(f"  direction_list: {config.direction_list}")

    # 除外数を計算するためにカウンタを取得する（grid_search内部の統計を後から取得）
    results = grid_search.run(
        df_m15_train=df_m15_train,
        df_m15_val=df_m15_val,
        df_h4_full=df_h4_full,
        df_m15_test=df_m15_test,
    )

    # --- 6. 統計の計算 ---
    cfg = config
    import itertools
    param_combos = list(itertools.product(
        cfg.ema_fast_list,
        cfg.ema_slow_list,
        cfg.breakout_lookback_list,
        cfg.atr_sl_multiplier_list,
        cfg.rr_ratio_list,
    ))
    n_invalid_combos = sum(
        1 for (ef, es, *_) in param_combos if ef >= es
    ) * len(cfg.direction_list)

    total_combos_raw = len(param_combos) * len(cfg.direction_list)
    n_valid_combos_raw = total_combos_raw - n_invalid_combos
    skipped_trade_count = n_valid_combos_raw - len(results)

    passes = [r for r in results if r.passes_val_filter]
    print(f"\n[結果] 評価={len(results)}, val通過={len(passes)}")

    # --- 7. レポート生成 ---
    report_md = build_report(
        results=results,
        grid_search=grid_search,
        df_m15=df_m15,
        df_h4=df_h4_full,
        skipped_invalid=n_invalid_combos,
        skipped_trade_count=skipped_trade_count,
    )

    # --- 8. 保存 ---
    reports_dir = Path(__file__).resolve().parents[1] / "reports"
    reports_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_path = reports_dir / f"fx_grid_search_usdjpy_{today}.md"
    output_path.write_text(report_md, encoding="utf-8")
    print(f"\n結果を保存しました: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
