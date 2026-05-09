"""
OHLCV データ品質チェック（実注文なし）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone

import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)

# USD/JPY として妥当な価格範囲
_USDJPY_MIN = 50.0
_USDJPY_MAX = 300.0

_REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


@dataclass
class ValidationResult:
    is_valid: bool
    row_count: int
    nan_rows: int
    duplicate_timestamps: int
    future_rows: int
    ohlc_violations: int
    price_range_violations: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ohlc_violation_rows: list[int] = field(default_factory=list)  # 違反行のインデックス

    def summary(self) -> str:
        """ログ出力用のサマリー文字列を返す。"""
        status = "OK" if self.is_valid else "NG"
        parts = [
            f"[{status}] rows={self.row_count}",
            f"nan_rows={self.nan_rows}",
            f"dup_ts={self.duplicate_timestamps}",
            f"future={self.future_rows}",
            f"ohlc_violations={self.ohlc_violations}",
            f"price_range_violations={self.price_range_violations}",
        ]
        s = ", ".join(parts)
        if self.errors:
            s += f" | ERRORS: {'; '.join(self.errors)}"
        if self.warnings:
            s += f" | WARNINGS: {'; '.join(self.warnings)}"
        return s


class OHLCVValidator:
    """
    OHLCV データの品質チェックを行う。実注文なし。

    チェック項目:
    1. 必須カラム存在チェック
    2. 欠損値チェック
    3. 重複タイムスタンプチェック
    4. 時系列逆転チェック
    5. 未来データ混入チェック
    6. OHLCV 整合性チェック
    7. 極端な値チェック（USD/JPY として妥当な範囲）
    """

    def validate(self, df: pd.DataFrame, timeframe: str = "") -> ValidationResult:
        """
        OHLCV データの品質チェックを実施する。

        Parameters
        ----------
        df : pd.DataFrame
            チェック対象の OHLCV DataFrame
        timeframe : str
            時間足識別子（ログ用）

        Returns
        -------
        ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []

        # --- 1. 空チェック ---
        if df is None or df.empty:
            return ValidationResult(
                is_valid=False,
                row_count=0,
                nan_rows=0,
                duplicate_timestamps=0,
                future_rows=0,
                ohlc_violations=0,
                price_range_violations=0,
                warnings=warnings,
                errors=["DataFrame が空です"],
            )

        row_count = len(df)

        # --- 2. 必須カラム存在チェック ---
        missing_cols = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
        if missing_cols:
            errors.append(f"必須カラムが不足: {missing_cols}")
            return ValidationResult(
                is_valid=False,
                row_count=row_count,
                nan_rows=0,
                duplicate_timestamps=0,
                future_rows=0,
                ohlc_violations=0,
                price_range_violations=0,
                warnings=warnings,
                errors=errors,
            )

        # --- 3. 欠損値チェック ---
        ohlcv_cols = ["open", "high", "low", "close", "volume"]
        nan_mask = df[ohlcv_cols].isna().any(axis=1)
        nan_rows = int(nan_mask.sum())
        if nan_rows > 0:
            warnings.append(f"NaN 行数: {nan_rows}")

        # --- 4. 重複タイムスタンプチェック ---
        ts_series = pd.to_datetime(df["timestamp"])
        duplicate_timestamps = int(ts_series.duplicated().sum())
        if duplicate_timestamps > 0:
            warnings.append(f"重複タイムスタンプ: {duplicate_timestamps} 件")

        # --- 5. 時系列逆転チェック ---
        ts_sorted = ts_series.reset_index(drop=True)
        is_monotonic = ts_sorted.is_monotonic_increasing
        if not is_monotonic:
            warnings.append("タイムスタンプが単調増加していません（時系列逆転あり）")

        # --- 6. 未来データ混入チェック ---
        now_utc = pd.Timestamp.now(tz=timezone.utc)
        if ts_series.dt.tz is None:
            ts_aware = ts_series.dt.tz_localize("UTC")
        else:
            ts_aware = ts_series.dt.tz_convert("UTC")
        future_mask = ts_aware > now_utc
        future_rows = int(future_mask.sum())
        if future_rows > 0:
            warnings.append(f"未来のデータ: {future_rows} 件")

        # --- 7. OHLCV 整合性チェック ---
        # high >= low, high >= open, high >= close, low <= open, low <= close
        ohlc_mask = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        )
        ohlc_violations = int(ohlc_mask.sum())
        ohlc_violation_rows: list[int] = list(df.index[ohlc_mask].tolist()) if ohlc_violations > 0 else []
        if ohlc_violations > 0:
            warnings.append(f"OHLCV 整合性違反: {ohlc_violations} 件 (high<low 等)")

        # --- 8. 極端な値チェック（USD/JPY として妥当な範囲: 50〜300円）---
        price_cols = ["open", "high", "low", "close"]
        price_mask = (
            (df[price_cols] < _USDJPY_MIN).any(axis=1)
            | (df[price_cols] > _USDJPY_MAX).any(axis=1)
        )
        price_range_violations = int(price_mask.sum())
        if price_range_violations > 0:
            warnings.append(
                f"USD/JPY 価格範囲外 ({_USDJPY_MIN}〜{_USDJPY_MAX}): {price_range_violations} 件"
            )

        # is_valid 判定: errors がなければ有効
        is_valid = len(errors) == 0

        result = ValidationResult(
            is_valid=is_valid,
            row_count=row_count,
            nan_rows=nan_rows,
            duplicate_timestamps=duplicate_timestamps,
            future_rows=future_rows,
            ohlc_violations=ohlc_violations,
            price_range_violations=price_range_violations,
            warnings=warnings,
            errors=errors,
            ohlc_violation_rows=ohlc_violation_rows,
        )
        log.info("OHLCVValidator[%s]: %s", timeframe, result.summary())
        return result
