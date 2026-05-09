"""
USD/JPY 長期 OHLCV データ取得スクリプト（H1・D1）
実注文なし・データ取得・保存のみ

取得制限:
- M15: 最大60日（yfinance制限）
- H1:  最大約730日（約2年）
- D1:  最大5年以上

DRY_RUN / READ_ONLY 設計:
  - 実注文 API は一切呼ばない
  - yfinance からデータを読み込んで CSV に保存するのみ
"""
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fx.ohlcv_fetcher import YFinanceFetcher
from src.fx.ohlcv_validator import OHLCVValidator
from src.utils.logger import get_logger

log = get_logger(__name__)


def main() -> None:
    print("=" * 60)
    print("USD/JPY 長期 OHLCV データ取得スクリプト")
    print("READ_ONLY: 実注文 API は一切呼びません")
    print("=" * 60)

    print("\n[制限] M15データは最大60日（yfinance制限）。長期検証にはH1を使用します。")

    fetcher = YFinanceFetcher()
    validator = OHLCVValidator()

    has_error = False

    # --- 1. H1 データ取得 ---
    print("\n[H1] 1時間足データ取得中 (period=730d)...")
    df_h1 = fetcher.fetch_h1(period="730d")

    if df_h1.empty:
        print("[ERROR] H1 データの取得に失敗しました")
        has_error = True
    else:
        # --- 2. H1 バリデーション ---
        vr_h1 = validator.validate(df_h1, timeframe="H1")
        print(f"[H1] バリデーション: {vr_h1.summary()}")
        for w in vr_h1.warnings:
            log.warning("[H1] %s", w)
        for e in vr_h1.errors:
            log.error("[H1] %s", e)
            has_error = True

        # --- 3. H1 保存 ---
        path_h1 = fetcher.save(df_h1, timeframe="H1")
        ts_h1_start = df_h1["timestamp"].min().date()
        ts_h1_end = df_h1["timestamp"].max().date()
        print(f"[H1] 取得: {len(df_h1)}本 ({ts_h1_start} 〜 {ts_h1_end}) → {path_h1}")

    # --- 4. D1 データ取得 ---
    print("\n[D1] 日足データ取得中 (period=5y)...")
    df_d1 = fetcher.fetch_d1(period="5y")

    if df_d1.empty:
        print("[ERROR] D1 データの取得に失敗しました")
        has_error = True
    else:
        # --- 5. D1 バリデーション ---
        vr_d1 = validator.validate(df_d1, timeframe="D1")
        print(f"[D1] バリデーション: {vr_d1.summary()}")
        for w in vr_d1.warnings:
            log.warning("[D1] %s", w)
        for e in vr_d1.errors:
            log.error("[D1] %s", e)
            has_error = True

        # --- 6. D1 保存 ---
        path_d1 = fetcher.save(df_d1, timeframe="D1")
        ts_d1_start = df_d1["timestamp"].min().date()
        ts_d1_end = df_d1["timestamp"].max().date()
        print(f"[D1] 取得: {len(df_d1)}本 ({ts_d1_start} 〜 {ts_d1_end}) → {path_d1}")

    print("\n" + "=" * 60)
    if has_error:
        print("[ERROR] エラーが発生しました。ログを確認してください。")
        sys.exit(1)
    else:
        print("完了: H1・D1 データ取得・保存が正常に終了しました")
    print("=" * 60)


if __name__ == "__main__":
    main()
