"""
USD/JPY H1/D1 lb=5 regime_filter 診断スクリプト
実注文なし・研究用のみ

目的:
- EMA20/200, breakout_lookback=5, atr_sl=1.5, rr=1.5, direction=both での
  各相場環境フィルターの成績を TRAIN/VAL/TEST で診断する
- direct D1 / resample D1 の両方で実行してD1ソース差分を確認する
- 採用判断ではなく、リスク構造の把握が目的

注意:
- test 結果はパラメータ選定に使わない（最終確認のみ）
- フィルターを増やして無理やり勝つ候補を作らない
- 部分利確・トレーリングSL は実装しない
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from src.fx.data_loader import FXDataLoader
from src.fx.h1_backtest_runner import H1BacktestRunner
from src.fx.lb5_regime_report import REGIME_PATTERNS, render_lb5_regime_report
from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.ohlcv_validator import OHLCVValidator

TARGET_PARAMS = {
    "ema_fast": 20,
    "ema_slow": 200,
    "breakout_lookback": 5,
    "atr_sl_multiplier": 1.5,
    "rr_ratio": 1.5,
    "direction": "both",
}

REPORTS_DIR = _PROJECT_ROOT / "reports"


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("=" * 60)
    print("データ読み込みと品質確認")
    print("=" * 60)

    fetcher = YFinanceFetcher()
    loader = FXDataLoader()
    validator = OHLCVValidator()

    df_h1 = fetcher.load_latest("H1")
    df_d1_direct = fetcher.load_latest("D1")

    if df_h1.empty:
        print("[ERROR] H1データが見つかりません")
        raise RuntimeError("H1データが見つかりません")

    vr_direct = validator.validate(df_d1_direct, "D1_direct") if not df_d1_direct.empty else None
    vr_h1 = validator.validate(df_h1, "H1")
    print(f"H1 : {len(df_h1):,} 行  OHLC違反: {vr_h1.ohlc_violations} 件")
    if not df_d1_direct.empty and vr_direct:
        print(f"D1 (direct): {len(df_d1_direct):,} 行  OHLC違反: {vr_direct.ohlc_violations} 件")

    df_d1_resample = loader.resample(df_h1, to="1D")
    if "timestamp" in df_d1_resample.columns:
        df_d1_resample["timestamp"] = pd.to_datetime(df_d1_resample["timestamp"], utc=True)
    print(f"D1 (resample): {len(df_d1_resample):,} 行")

    return df_h1, df_d1_direct if not df_d1_direct.empty else df_d1_resample


# ---------------------------------------------------------------------------
# バックテスト実行
# ---------------------------------------------------------------------------

def run_all_patterns(
    df_h1: pd.DataFrame,
    df_d1: pd.DataFrame,
    d1_source: str,
) -> dict[str, dict]:
    """全8パターンのバックテストを実行して結果を返す。"""
    runner = H1BacktestRunner()
    results: dict[str, dict] = {}

    print(f"\n  [{d1_source} D1] 全 {len(REGIME_PATTERNS)} パターン実行中...")

    for pat_name, regime_filter in REGIME_PATTERNS:
        res = runner.run_full_validation(
            df_h1,
            df_d1,
            ema_fast=TARGET_PARAMS["ema_fast"],
            ema_slow=TARGET_PARAMS["ema_slow"],
            breakout_lookback=TARGET_PARAMS["breakout_lookback"],
            atr_sl_multiplier=TARGET_PARAMS["atr_sl_multiplier"],
            rr_ratio=TARGET_PARAMS["rr_ratio"],
            direction=TARGET_PARAMS["direction"],
            d1_source=d1_source,
            regime_filter=regime_filter,
        )
        results[pat_name] = {
            "train": res["train"],
            "val": res["val"],
            "test": res["test"],
        }
        vr = res["val"]
        print(
            f"    {pat_name:<14} | val: trades={vr.trade_count:>3}, "
            f"PF={vr.profit_factor:.3f}, MDD={vr.max_drawdown_pct:.2f}%"
        )

    return results


# ---------------------------------------------------------------------------
# レポート保存
# ---------------------------------------------------------------------------

def save_report(content: str, generated_at: datetime) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    datestr = generated_at.strftime("%Y%m%d")
    path = REPORTS_DIR / f"fx_lb5_regime_diagnostics_{datestr}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("USD/JPY H1/D1 lb=5 regime_filter 診断")
    print("実注文なし・研究用のみ")
    print("=" * 60)

    df_h1, df_d1_direct = load_data()

    print("\n" + "=" * 60)
    print("バックテスト実行（resample D1）")
    print("=" * 60)
    results_resample = run_all_patterns(df_h1, df_d1_direct, d1_source="resample")

    print("\n" + "=" * 60)
    print("バックテスト実行（direct D1）")
    print("=" * 60)
    results_direct = run_all_patterns(df_h1, df_d1_direct, d1_source="direct")

    generated_at = datetime.now(timezone.utc)
    report = render_lb5_regime_report(
        results_resample=results_resample,
        results_direct=results_direct,
        target_params=TARGET_PARAMS,
        generated_at=generated_at,
    )

    path = save_report(report, generated_at)
    print(f"\nレポート保存: {path}")
    print("\n--- レポート先頭 (20行) ---")
    for line in report.splitlines()[:20]:
        print(line)
    print("...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
