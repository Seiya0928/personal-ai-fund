"""
相場環境分類モジュール（実注文なし・研究用）
上昇トレンド / 下降トレンド / レンジ を分類する
"""
from __future__ import annotations

from enum import Enum

import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


class MarketRegime(str, Enum):
    UP = "uptrend"
    DOWN = "downtrend"
    RANGE = "range"


class RegimeClassifier:
    """
    D1または長期足の EMA を使って相場環境を分類する。

    ルール:
    - EMA50 > EMA200 かつ 価格が EMA50 より上 → UP
    - EMA50 < EMA200 かつ 価格が EMA50 より下 → DOWN
    - それ以外 → RANGE
    """

    def __init__(self, ema_fast: int = 50, ema_slow: int = 200) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        df に 'regime' 列（MarketRegime の値）を追加して返す。
        df は D1 または長期足の OHLCV DataFrame。
        """
        df = df.copy()
        df["_ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["_ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()

        def _classify_row(row: pd.Series) -> str:
            ema_f = row["_ema_fast"]
            ema_s = row["_ema_slow"]
            price = row["close"]
            if ema_f > ema_s and price > ema_f:
                return MarketRegime.UP.value
            elif ema_f < ema_s and price < ema_f:
                return MarketRegime.DOWN.value
            else:
                return MarketRegime.RANGE.value

        df["regime"] = df.apply(_classify_row, axis=1)
        df = df.drop(columns=["_ema_fast", "_ema_slow"])

        counts = df["regime"].value_counts().to_dict()
        log.info("RegimeClassifier.classify: rows=%d, regime_counts=%s", len(df), counts)
        return df

    def align_to_entry(
        self,
        df_regime: pd.DataFrame,
        df_entry: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        df_regime の regime を df_entry の各行にアライン（前向き伝播）して返す。
        df_entry に 'regime' 列を追加する。

        未来データの混入を防ぐため、df_regime の各行の timestamp 時点でのみ
        regime 値を確定し、df_entry の各 H1 timestamp に対して直前の regime を
        前向き伝播（ffill）する。
        """
        df_regime = df_regime.copy()
        df_entry = df_entry.copy()

        # timestamp を datetime 型に統一
        df_regime["timestamp"] = pd.to_datetime(df_regime["timestamp"], utc=True)
        df_entry["timestamp"] = pd.to_datetime(df_entry["timestamp"], utc=True)

        # regime のみ抽出してインデックス化
        regime_series = (
            df_regime[["timestamp", "regime"]]
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .set_index("timestamp")["regime"]
        )

        # pd.merge_asof で前向き伝播（各エントリー足に直近の D1 regime を適用）
        df_regime_sorted = regime_series.reset_index().rename(columns={"timestamp": "_ts_regime"})
        df_entry_sorted = df_entry.sort_values("timestamp").reset_index(drop=False)

        merged = pd.merge_asof(
            df_entry_sorted,
            df_regime_sorted.rename(columns={"_ts_regime": "timestamp"}),
            on="timestamp",
            direction="backward",
        )

        # 元のインデックス順に戻す
        merged = merged.sort_values("index").drop(columns=["index"]).reset_index(drop=True)

        # regime が存在しない場合は RANGE で埋める
        if "regime" not in merged.columns:
            merged["regime"] = MarketRegime.RANGE.value
        else:
            merged["regime"] = merged["regime"].fillna(MarketRegime.RANGE.value)

        log.info(
            "RegimeClassifier.align_to_entry: entry_rows=%d, regime_rows=%d",
            len(df_entry),
            len(df_regime),
        )
        return merged
