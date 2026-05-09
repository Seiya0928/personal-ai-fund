"""
USD/JPY H1足 長期バックテスト検証スクリプト
実注文なし・研究用のみ

データ: H1（エントリー足）、D1（トレンド判定）

DRY_RUN / READ_ONLY 設計:
  - 実注文 API は一切呼ばない
  - バックテスト・研究目的の検証のみ
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.fx.grid_search import FXGridSearch, GridSearchConfig
from src.fx.h1_backtest_runner import H1BacktestRunner
from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.ohlcv_validator import OHLCVValidator
from src.utils.logger import get_logger

log = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = _PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _fmt_result(result, label: str) -> str:
    """FXBacktestResult を Markdown テーブル行に変換する。"""
    return (
        f"| {label} | {result.total_return_pct:.2f}% | "
        f"{result.win_rate * 100:.1f}% | "
        f"{result.profit_factor:.2f} | "
        f"{result.max_drawdown_pct:.2f}% | "
        f"{result.trade_count} | "
        f"{result.expectancy:.0f}円 |"
    )


def _fmt_regime_summary(regime_summary: dict) -> str:
    """regime_summary を Markdown テーブルに変換する。"""
    lines = []
    lines.append("| regime | trades | win_rate | PF |")
    lines.append("|--------|--------|----------|----|")
    for regime, data in regime_summary.items():
        lines.append(
            f"| {regime} | {data['trade_count']} | "
            f"{data['win_rate'] * 100:.1f}% | "
            f"{data['profit_factor']:.2f} |"
        )
    return "\n".join(lines)


def _result_table_header() -> str:
    return (
        "| セット | total_return | win_rate | PF | MDD | trades | expectancy |\n"
        "|--------|-------------|----------|-----|-----|--------|------------|"
    )


def main() -> None:
    print("=" * 60)
    print("USD/JPY H1足 長期バックテスト検証スクリプト")
    print("READ_ONLY: 実注文 API は一切呼びません")
    print("=" * 60)

    fetcher = YFinanceFetcher()
    validator = OHLCVValidator()

    # --- 1. H1 データ読み込み（なければ fetch して保存）---
    print("\n[H1] データ読み込み中...")
    df_h1 = fetcher.load_latest("H1")
    if df_h1.empty:
        print("[H1] キャッシュなし → yfinance から取得します")
        df_h1 = fetcher.fetch_h1(period="730d")
        if df_h1.empty:
            print("[ERROR] H1 データの取得に失敗しました")
            sys.exit(1)
        fetcher.save(df_h1, "H1")

    # --- 2. D1 データ読み込み（なければ fetch して保存）---
    print("[D1] データ読み込み中...")
    df_d1 = fetcher.load_latest("D1")
    if df_d1.empty:
        print("[D1] キャッシュなし → yfinance から取得します")
        df_d1 = fetcher.fetch_d1(period="5y")
        if df_d1.empty:
            print("[ERROR] D1 データの取得に失敗しました")
            sys.exit(1)
        fetcher.save(df_d1, "D1")

    # timestamp を UTC 統一
    df_h1["timestamp"] = pd.to_datetime(df_h1["timestamp"], utc=True)
    df_d1["timestamp"] = pd.to_datetime(df_d1["timestamp"], utc=True)
    df_h1 = df_h1.sort_values("timestamp").reset_index(drop=True)
    df_d1 = df_d1.sort_values("timestamp").reset_index(drop=True)

    # --- 3. バリデーション ---
    vr_h1 = validator.validate(df_h1, timeframe="H1")
    vr_d1 = validator.validate(df_d1, timeframe="D1")
    print(f"[H1] バリデーション: {vr_h1.summary()}")
    print(f"[D1] バリデーション: {vr_d1.summary()}")

    h1_start = df_h1["timestamp"].min().date()
    h1_end = df_h1["timestamp"].max().date()
    d1_start = df_d1["timestamp"].min().date()
    d1_end = df_d1["timestamp"].max().date()

    # H1 期間をヶ月数で計算
    h1_months = (df_h1["timestamp"].max() - df_h1["timestamp"].min()).days // 30

    print(f"\n[H1] {len(df_h1)}本 ({h1_start} 〜 {h1_end})")
    print(f"[D1] {len(df_d1)}本 ({d1_start} 〜 {d1_end})")

    # --- 4. H1BacktestRunner でデフォルトパラメータ検証 ---
    runner = H1BacktestRunner()

    print("\n[検証] デフォルトパラメータ (both)...")
    result_both = runner.run_full_validation(df_h1, df_d1, direction="both")

    print("[検証] long_only...")
    result_long = runner.run_full_validation(df_h1, df_d1, direction="long_only")

    print("[検証] short_only...")
    result_short = runner.run_full_validation(df_h1, df_d1, direction="short_only")

    # --- 5. グリッドサーチ（H1/D1） ---
    print("\n[グリッドサーチ] H1/D1 対応グリッドサーチ実行中...")
    gs_config = GridSearchConfig(
        ema_fast_list=[20, 50],
        ema_slow_list=[100, 200],
        breakout_lookback_list=[10, 20],
        atr_sl_multiplier_list=[1.5, 2.0],
        rr_ratio_list=[2.0, 2.5],
        direction_list=["both", "long_only", "short_only"],
        min_trade_count=5,
        val_min_profit_factor=1.1,
        val_max_drawdown_pct=15.0,
    )
    gs = FXGridSearch(config=gs_config)

    # H1 を train/val/test に分割
    n = len(df_h1)
    n_train = int(n * 0.6)
    n_val = int(n * 0.2)
    df_h1_train = df_h1.iloc[:n_train].reset_index(drop=True)
    df_h1_val = df_h1.iloc[n_train: n_train + n_val].reset_index(drop=True)
    df_h1_test = df_h1.iloc[n_train + n_val:].reset_index(drop=True)

    gs_results = gs.run(
        df_entry_train=df_h1_train,
        df_entry_val=df_h1_val,
        df_trend_full=df_d1,
        df_entry_test=df_h1_test,
        timeframe="H1",
    )

    n_pass = sum(1 for r in gs_results if r.passes_val_filter)
    top5 = gs_results[:5]

    print(f"[グリッドサーチ] 評価: {len(gs_results)}件, valフィルター通過: {n_pass}件")

    # --- 6. レポート生成 ---
    now_jst = datetime.now(timezone.utc).astimezone(
        __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("Asia/Tokyo")
    )
    now_str = now_jst.strftime("%Y-%m-%d %H:%M JST")
    date_str = now_jst.strftime("%Y%m%d")

    report_path = REPORTS_DIR / f"fx_longterm_validation_usdjpy_{date_str}.md"

    # MFE/MAE サマリー（both・全セット）
    res_both_train = result_both["train"]
    res_both_val = result_both["val"]
    res_both_test = result_both["test"]

    # グリッドサーチ上位5候補テーブル
    gs_top_lines = []
    gs_top_lines.append(
        "| rank | direction | ema_fast | ema_slow | lookback | atr_sl | rr | "
        "train_pf | val_pf | val_mdd | val_trades |"
    )
    gs_top_lines.append(
        "|------|-----------|----------|----------|----------|--------|----|"
        "----------|--------|---------|------------|"
    )
    for rank, r in enumerate(top5, 1):
        p = r.params
        gs_top_lines.append(
            f"| {rank} | {r.direction} | {p['ema_fast']} | {p['ema_slow']} | "
            f"{p['breakout_lookback']} | {p['atr_sl_multiplier']} | {p['rr_ratio']} | "
            f"{r.train.profit_factor:.2f} | {r.val.profit_factor:.2f} | "
            f"{r.val.max_drawdown_pct:.2f}% | {r.val.trade_count} |"
        )

    report = f"""# USD/JPY H1足 長期バックテスト検証
生成日時: {now_str}
データ期間: {h1_start} 〜 {h1_end}（約{h1_months} ヶ月）

## データ制約
- M15: 最大60日（yfinance制限）→ 短期シグナル検証のみ
- H1:  取得期間 {h1_start} 〜 {h1_end}（{len(df_h1)}本）
- D1:  取得期間 {d1_start} 〜 {d1_end}（{len(df_d1)}本）

## デフォルトパラメータ検証（both方向）
{_result_table_header()}
{_fmt_result(result_both["train"], "train")}
{_fmt_result(result_both["val"], "val")}
{_fmt_result(result_both["test"], "test")}

## デフォルトパラメータ検証（long_only）
{_result_table_header()}
{_fmt_result(result_long["train"], "train")}
{_fmt_result(result_long["val"], "val")}
{_fmt_result(result_long["test"], "test")}

## デフォルトパラメータ検証（short_only）
{_result_table_header()}
{_fmt_result(result_short["train"], "train")}
{_fmt_result(result_short["val"], "val")}
{_fmt_result(result_short["test"], "test")}

## 相場環境別集計
{_fmt_regime_summary(result_both["regime_summary"])}

## MFE/MAE分析
- 勝ちトレード: MFE={res_both_train.avg_mfe_win_pips:.1f}pips(train), MAE={res_both_train.avg_mae_win_pips:.1f}pips(train)
- 負けトレード: MFE={res_both_train.avg_mfe_lose_pips:.1f}pips(train), MAE={res_both_train.avg_mae_lose_pips:.1f}pips(train)
- val: 勝ちMFE={res_both_val.avg_mfe_win_pips:.1f}pips, 勝ちMAE={res_both_val.avg_mae_win_pips:.1f}pips
- val: 負けMFE={res_both_val.avg_mfe_lose_pips:.1f}pips, 負けMAE={res_both_val.avg_mae_lose_pips:.1f}pips
- TP50%達成後損切り(val): {res_both_val.failed_after_half_tp_count}件

## グリッドサーチ（H1/D1）
検索組み合わせ: {len(gs_results)}件
valフィルター通過: {n_pass}件

### 上位候補
{chr(10).join(gs_top_lines)}

## 結論
- H1足を用いた EMA トレンドフォロー戦略のバックテストを実施しました
- D1の EMA50/200 でトレンド方向を判定し、H1 でブレイクアウトエントリーを検証
- 相場環境（uptrend/downtrend/range）別に成績を集計しました
- グリッドサーチによりパラメータ最適化候補を抽出しました
- 本検証は研究目的のみ。実注文は一切行いません
"""

    report_path.write_text(report, encoding="utf-8")
    print(f"\n[レポート] 保存完了: {report_path}")

    # サマリーをコンソール出力
    print("\n" + "=" * 60)
    print("検証完了サマリー")
    print("=" * 60)
    print(f"H1データ: {len(df_h1)}本 ({h1_start} 〜 {h1_end})")
    print(f"D1データ: {len(df_d1)}本 ({d1_start} 〜 {d1_end})")
    print()
    print("デフォルトパラメータ (both):")
    print(f"  train: trades={result_both['train'].trade_count}, WR={result_both['train'].win_rate*100:.1f}%, PF={result_both['train'].profit_factor:.2f}, Return={result_both['train'].total_return_pct:.2f}%")
    print(f"  val:   trades={result_both['val'].trade_count}, WR={result_both['val'].win_rate*100:.1f}%, PF={result_both['val'].profit_factor:.2f}, Return={result_both['val'].total_return_pct:.2f}%")
    print(f"  test:  trades={result_both['test'].trade_count}, WR={result_both['test'].win_rate*100:.1f}%, PF={result_both['test'].profit_factor:.2f}, Return={result_both['test'].total_return_pct:.2f}%")
    print()
    print("相場環境別:")
    for reg, data in result_both["regime_summary"].items():
        print(f"  {reg}: trades={data['trade_count']}, WR={data['win_rate']*100:.1f}%, PF={data['profit_factor']:.2f}")
    print()
    print(f"グリッドサーチ: {len(gs_results)}件評価, {n_pass}件通過")
    print(f"レポート: {report_path}")


if __name__ == "__main__":
    main()
