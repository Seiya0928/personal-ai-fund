"""
USD/JPY EMAトレンドフォロー バックテスト（実データ版）
実注文なし・研究用のみ

DRY_RUN / READ_ONLY 設計:
  - 実注文 API は一切呼ばない
  - yfinance からデータを読み込んでバックテストのみ実行
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
from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.ohlcv_validator import OHLCVValidator
from src.fx.strategy import MultiTimeframeEMAStrategy
from src.fx.fx_backtest import FXBacktestResult, FXBacktestRunner
from src.utils.logger import get_logger

log = get_logger(__name__)


def _print_result(label: str, result: FXBacktestResult) -> None:
    print(f"\n=== {label} ===")
    print(f"  total_return={result.total_return_pct:+.2f}%")
    print(f"  win_rate={result.win_rate * 100:.1f}%")
    print(f"  profit_factor={result.profit_factor:.2f}")
    print(f"  max_drawdown={result.max_drawdown_pct:.2f}%")
    print(f"  expectancy={result.expectancy:+.0f}円")
    print(f"  trades={result.trade_count}")
    print(f"  max_losing_streak={result.max_losing_streak}")


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


def main() -> None:
    print("=" * 60)
    print("[REAL DATA] USD/JPY EMA Strategy Backtest")
    print("READ_ONLY: 実注文 API は一切呼びません")
    print("=" * 60)

    fetcher = YFinanceFetcher()
    validator = OHLCVValidator()
    loader = FXDataLoader()

    # --- 1. M15 データ読み込み（なければ取得・保存）---
    print("\n[M15] データ読み込み中...")
    df_m15 = fetcher.load_latest("M15")

    if df_m15.empty:
        print("[M15] 保存済みデータなし → yfinance から取得します")
        df_m15 = fetcher.fetch_m15(period="60d")
        if df_m15.empty:
            print("[ERROR] M15 データの取得に失敗しました")
            sys.exit(1)
        fetcher.save(df_m15, timeframe="M15")
        print(f"[M15] 取得・保存完了: {len(df_m15)} 本")
    else:
        print(f"[M15] キャッシュから読み込み: {len(df_m15)} 本")

    # --- 2. H4 データを M15 からリサンプル生成 ---
    print("\n[H4] M15 → H4 リサンプル中...")
    df_h4 = loader.resample(df_m15, to="4h")
    print(f"[H4] リサンプル完了: {len(df_h4)} 本")

    # --- 3. データ範囲を表示 ---
    ts_m15_start = df_m15["timestamp"].min()
    ts_m15_end = df_m15["timestamp"].max()
    ts_h4_start = df_h4["timestamp"].min()
    ts_h4_end = df_h4["timestamp"].max()

    print(f"\nM15データ: {len(df_m15)}本 ({ts_m15_start} 〜 {ts_m15_end})")
    print(f"H4データ:  {len(df_h4)}本 ({ts_h4_start} 〜 {ts_h4_end})")

    # --- 4. バリデーション ---
    print("\n[バリデーション]")
    vr_m15 = validator.validate(df_m15, timeframe="M15")
    vr_h4 = validator.validate(df_h4, timeframe="H4")
    print(f"  M15: {vr_m15.summary()}")
    print(f"  H4:  {vr_h4.summary()}")

    if not vr_m15.is_valid:
        print("[ERROR] M15 データにエラーがあります。終了します。")
        for e in vr_m15.errors:
            print(f"  - {e}")
        sys.exit(1)

    if not vr_h4.is_valid:
        print("[ERROR] H4 データにエラーがあります。終了します。")
        for e in vr_h4.errors:
            print(f"  - {e}")
        sys.exit(1)

    # --- 5. シグナル生成 ---
    print("\n[シグナル生成]")
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
        account_balance=1_000_000.0,
        pip_value_jpy=100.0,
    )

    df_signals = strategy.generate_signals(df_h4, df_m15)
    n_buy = (df_signals["signal"] == 1).sum()
    n_sell = (df_signals["signal"] == -1).sum()
    n_flat = len(df_signals) - n_buy - n_sell
    print(f"  BUY={n_buy}, SELL={n_sell}, FLAT={n_flat}")

    # --- 6. Train / Val / Test 分割 ---
    runner = FXBacktestRunner(
        initial_balance=1_000_000,
        spread_pips=0.3,
        slippage_pips=0.1,
        commission_pips=0.0,
        pip_value_jpy=100.0,
    )
    df_train, df_val, df_test = FXBacktestRunner.split(df_signals, train=0.6, val=0.2, test=0.2)
    print(f"\nデータ分割: train={len(df_train)}, val={len(df_val)}, test={len(df_test)}")

    # --- 7. バックテスト実行 ---
    result_train = runner.run(df_train, symbol="USD/JPY")
    result_val = runner.run(df_val, symbol="USD/JPY")
    result_test = runner.run(df_test, symbol="USD/JPY")

    _print_result("TRAIN (60%)", result_train)
    _print_result("VALIDATION (20%)", result_val)
    _print_result("TEST (20%)", result_test)

    # --- 8. 月別リターン（テストセット）---
    if result_test.monthly_returns:
        print("\n月別リターン (test):")
        for month in sorted(result_test.monthly_returns.keys()):
            pct = result_test.monthly_returns[month]
            print(f"  {month}: {pct:+.2f}%")

    # --- 9. JSON 保存 ---
    reports_dir = Path(__file__).resolve().parents[1] / "reports"
    reports_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    output_path = reports_dir / f"fx_backtest_real_{today}.json"

    report = {
        "generated_at": datetime.now().isoformat(),
        "dry_run": True,
        "data_source": "yfinance (real data)",
        "m15_rows": len(df_m15),
        "h4_rows": len(df_h4),
        "m15_start": str(ts_m15_start),
        "m15_end": str(ts_m15_end),
        "h4_start": str(ts_h4_start),
        "h4_end": str(ts_h4_end),
        "train": _to_dict(result_train),
        "val": _to_dict(result_val),
        "test": _to_dict(result_test),
    }

    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果を保存しました: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
