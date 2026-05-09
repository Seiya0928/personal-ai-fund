"""
USD/JPY OHLCVデータローダー（読み込み専用）
実注文なし
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)

_REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


class FXDataLoader:
    """CSV または合成データから OHLCV DataFrame を読み込む。実注文なし。"""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_csv(self, path: Path, timeframe: str) -> pd.DataFrame:
        """
        CSV ファイルを読み込む。

        Parameters
        ----------
        path : Path
            CSV ファイルパス
        timeframe : str
            時間足識別子（ログ用）

        Returns
        -------
        pd.DataFrame
            timestamp が datetime 型で昇順ソート済みの OHLCV DataFrame
        """
        df = pd.read_csv(path)
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"CSV に必須カラムが不足: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        log.info("load_csv: %s, timeframe=%s, rows=%d", path, timeframe, len(df))
        return df

    def load_synthetic(
        self,
        n_bars: int = 1000,
        timeframe: str = "M15",
        start_price: float = 155.0,
        seed: int = 42,
    ) -> pd.DataFrame:
        """
        テスト・デモ用の合成 OHLCV データを生成する。

        ランダムウォーク + 弱いトレンド成分を含む。
        timeframe が "H4" の場合、n_bars を 1/16 に間引く（15分 vs 4時間）。

        Parameters
        ----------
        n_bars : int
            生成本数
        timeframe : str
            "M15" または "H4"
        start_price : float
            開始価格（円）
        seed : int
            乱数シード

        Returns
        -------
        pd.DataFrame
        """
        rng = np.random.default_rng(seed)

        effective_bars = n_bars
        if timeframe.upper() == "H4":
            effective_bars = max(1, n_bars // 16)

        # 15分足ベースでタイムスタンプを生成
        freq = "4h" if timeframe.upper() == "H4" else "15min"
        timestamps = pd.date_range(
            start="2024-01-01 00:00:00",
            periods=effective_bars,
            freq=freq,
            tz="UTC",
        )

        # ランダムウォーク + 緩やかなトレンド
        returns = rng.normal(0, 0.001, size=effective_bars)
        # 弱いトレンド成分（上昇バイアス）
        trend = np.linspace(0, 0.05, effective_bars)
        closes = start_price * np.exp(np.cumsum(returns) + trend)

        # OHLCV 生成
        highs = closes * (1 + rng.uniform(0, 0.002, size=effective_bars))
        lows = closes * (1 - rng.uniform(0, 0.002, size=effective_bars))
        opens = np.roll(closes, 1)
        opens[0] = start_price
        volumes = rng.integers(1000, 10000, size=effective_bars).astype(float)

        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )
        log.info(
            "load_synthetic: timeframe=%s, n_bars=%d (effective=%d), start_price=%.3f",
            timeframe,
            n_bars,
            effective_bars,
            start_price,
        )
        return df

    def resample(self, df: pd.DataFrame = None, to: str = "4H", df_m15: pd.DataFrame = None) -> pd.DataFrame:
        """
        任意時間足の DataFrame を指定時間足にリサンプルする。
        M15, H1 など、どの時間足でも入力として使用可能。

        Parameters
        ----------
        df : pd.DataFrame
            入力 OHLCV（timestamp 列を持つ）。M15・H1 など任意の時間足。
        to : str
            pandas offset alias（例: "4H", "1H", "1D"）
        df_m15 : pd.DataFrame
            後方互換用エイリアス。df が None の場合に使用される。

        Returns
        -------
        pd.DataFrame
        """
        # 後方互換: df_m15 引数が渡された場合は df として使う
        if df is None and df_m15 is not None:
            df = df_m15
        if df is None:
            raise ValueError("df または df_m15 を指定してください")

        src_timeframe = "input"
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()

        resampled = df.resample(to).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()
        resampled = resampled.reset_index()
        log.info("resample: %s → %s, rows=%d", src_timeframe, to, len(resampled))
        return resampled
