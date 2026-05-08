"""
USD/JPY OHLCV データ取得スクリプト
実注文なし・データ取得・保存のみ

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
    print("USD/JPY OHLCV データ取得スクリプト")
    print("READ_ONLY: 実注文 API は一切呼びません")
    print("=" * 60)

    fetcher = YFinanceFetcher()
    validator = OHLCVValidator()

    # --- 1. M15 データ取得 ---
    print("\n[M15] 15分足データ取得中 (period=60d)...")
    df_m15 = fetcher.fetch_m15(period="60d")

    if df_m15.empty:
        print("[ERROR] M15 データの取得に失敗しました")
        sys.exit(1)

    # --- 2. M15 バリデーション ---
    vr_m15 = validator.validate(df_m15, timeframe="M15")
    print(f"[M15] バリデーション: {vr_m15.summary()}")
    for w in vr_m15.warnings:
        log.warning("[M15] %s", w)
    for e in vr_m15.errors:
        log.error("[M15] %s", e)

    # --- 3. M15 保存 ---
    path_m15 = fetcher.save(df_m15, timeframe="M15")
    ts_m15_start = df_m15["timestamp"].min()
    ts_m15_end = df_m15["timestamp"].max()
    print(f"[M15] 取得完了: {len(df_m15)} 本 ({ts_m15_start} 〜 {ts_m15_end})")
    print(f"[M15] 保存先: {path_m15}")

    # --- 4. H4 データ取得（1時間足からリサンプル）---
    print("\n[H4] 4時間足データ取得中 (period=730d, H1→H4リサンプル)...")
    df_h4 = fetcher.fetch_h4(period="730d")

    if df_h4.empty:
        print("[WARNING] H4 データの取得に失敗しました（M15 のみ保存）")
    else:
        # --- 5. H4 バリデーション ---
        vr_h4 = validator.validate(df_h4, timeframe="H4")
        print(f"[H4] バリデーション: {vr_h4.summary()}")
        for w in vr_h4.warnings:
            log.warning("[H4] %s", w)
        for e in vr_h4.errors:
            log.error("[H4] %s", e)

        # --- 6. H4 保存 ---
        path_h4 = fetcher.save(df_h4, timeframe="H4")
        ts_h4_start = df_h4["timestamp"].min()
        ts_h4_end = df_h4["timestamp"].max()
        print(f"[H4] 取得完了: {len(df_h4)} 本 ({ts_h4_start} 〜 {ts_h4_end})")
        print(f"[H4] 保存先: {path_h4}")

    # --- 7. エラー判定 ---
    has_error = not vr_m15.is_valid
    if df_h4 is not None and not df_h4.empty:
        has_error = has_error or not vr_h4.is_valid

    print("\n" + "=" * 60)
    if has_error:
        print("[ERROR] バリデーションエラーがあります。ログを確認してください。")
        sys.exit(1)
    else:
        print("完了: データ取得・保存が正常に終了しました")
    print("=" * 60)


if __name__ == "__main__":
    main()
