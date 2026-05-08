"""
USD/JPY EMAトレンドフォロー バックテスト実行スクリプト
実注文なし・研究用のみ

DRY_RUN / READ_ONLY 設計:
  - 実注文 API は一切呼ばない
  - 結果は reports/ ディレクトリに JSON で保存するのみ
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fx.data_loader import FXDataLoader
from src.fx.strategy import MultiTimeframeEMAStrategy
from src.fx.fx_backtest import FXBacktestResult, FXBacktestRunner
from src.utils.logger import get_logger

log = get_logger(__name__)


def _print_result(label: str, result: FXBacktestResult) -> None:
    print(
        f"  {label}: "
        f"total_return={result.total_return_pct:+.2f}%, "
        f"win_rate={result.win_rate * 100:.1f}%, "
        f"pf={result.profit_factor:.2f}, "
        f"mdd={result.max_drawdown_pct:.2f}%, "
        f"expectancy={result.expectancy:+.0f}円, "
        f"trades={result.trade_count}"
    )
    if result.monthly_returns:
        keys = sorted(result.monthly_returns.keys())
        print("    monthly_returns:")
        for k in keys:
            print(f"      {k}: {result.monthly_returns[k]:+.4f}%")


def main() -> None:
    print("=" * 60)
    print("USD/JPY EMAトレンドフォロー バックテスト")
    print("DRY_RUN / READ_ONLY: 実注文APIは一切呼びません")
    print("=" * 60)

    # --- 1. 合成データ生成 ---
    loader = FXDataLoader()
    df_h4 = loader.load_synthetic(n_bars=500, timeframe="H4", start_price=155.0, seed=42)
    df_m15 = loader.load_synthetic(n_bars=8000, timeframe="M15", start_price=155.0, seed=42)
    print(f"\nデータ生成完了: H4={len(df_h4)}本, M15={len(df_m15)}本")

    # --- 2. シグナル生成 ---
    strategy = MultiTimeframeEMAStrategy(
        ema_fast=50,
        ema_slow=200,
        breakout_lookback=20,
        atr_period=14,
        atr_sl_multiplier=1.5,
        rr_ratio=2.0,
        risk_pct=0.01,
        spread_pips=0.3,
        slippage_pips=0.1,
    )
    df_signals = strategy.generate_signals(df_h4, df_m15)
    n_buy = (df_signals["signal"] == 1).sum()
    n_sell = (df_signals["signal"] == -1).sum()
    print(f"シグナル生成完了: BUY={n_buy}, SELL={n_sell}, FLAT={len(df_signals) - n_buy - n_sell}")

    # --- 3. Train / Val / Test 分割 ---
    runner = FXBacktestRunner(
        initial_balance=1_000_000,
        spread_pips=0.3,
        slippage_pips=0.1,
        commission_pips=0.0,
        pip_value_jpy=100.0,
    )
    df_train, df_val, df_test = FXBacktestRunner.split(df_signals, train=0.6, val=0.2, test=0.2)
    print(
        f"\nデータ分割: train={len(df_train)}, val={len(df_val)}, test={len(df_test)}"
    )

    # --- 4. 各セットでバックテスト ---
    print("\n--- バックテスト結果 ---")
    result_train = runner.run(df_train, symbol="USD/JPY")
    result_val = runner.run(df_val, symbol="USD/JPY")
    result_test = runner.run(df_test, symbol="USD/JPY")

    _print_result("train", result_train)
    _print_result("val  ", result_val)
    _print_result("test ", result_test)

    # --- 5. JSON 保存 ---
    reports_dir = Path(__file__).resolve().parents[1] / "reports"
    reports_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_path = reports_dir / f"fx_backtest_{today}.json"

    def _to_dict(r: FXBacktestResult) -> dict:
        return {
            "symbol": r.symbol,
            "initial_balance": r.initial_balance,
            "final_balance": r.final_balance,
            "total_return_pct": r.total_return_pct,
            "expectancy": r.expectancy,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor if r.profit_factor != float("inf") else None,
            "max_drawdown_pct": r.max_drawdown_pct,
            "max_losing_streak": r.max_losing_streak,
            "trade_count": r.trade_count,
            "monthly_returns": r.monthly_returns,
            "assumptions": r.assumptions,
        }

    report = {
        "generated_at": datetime.now().isoformat(),
        "dry_run": True,
        "train": _to_dict(result_train),
        "val": _to_dict(result_val),
        "test": _to_dict(result_test),
    }

    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果を保存しました: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
