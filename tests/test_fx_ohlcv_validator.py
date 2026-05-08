"""
OHLCVValidator のユニットテスト
実注文なし
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.fx.ohlcv_validator import OHLCVValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_df(n: int = 20, price: float = 155.0) -> pd.DataFrame:
    """正常な OHLCV DataFrame を生成する。"""
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [price] * n,
            "high": [price + 0.05] * n,
            "low": [price - 0.05] * n,
            "close": [price] * n,
            "volume": [1000.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidDataframe:
    def test_valid_dataframe(self):
        """正常な OHLCV データ → is_valid=True。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=20)
        result = validator.validate(df, timeframe="M15")
        assert result.is_valid is True
        assert result.row_count == 20
        assert result.nan_rows == 0
        assert result.duplicate_timestamps == 0
        assert result.ohlc_violations == 0
        assert result.price_range_violations == 0
        assert len(result.errors) == 0

    def test_valid_summary_contains_ok(self):
        """正常データのサマリーは [OK] を含む。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5)
        result = validator.validate(df)
        assert "[OK]" in result.summary()


class TestMissingColumn:
    def test_missing_column_timestamp(self):
        """timestamp カラムなし → is_valid=False。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5).drop(columns=["timestamp"])
        result = validator.validate(df, timeframe="M15")
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_missing_column_close(self):
        """close カラムなし → is_valid=False。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5).drop(columns=["close"])
        result = validator.validate(df, timeframe="M15")
        assert result.is_valid is False

    def test_missing_multiple_columns(self):
        """複数の必須カラムなし → is_valid=False。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5).drop(columns=["open", "high", "low"])
        result = validator.validate(df, timeframe="M15")
        assert result.is_valid is False

    def test_summary_contains_ng_on_error(self):
        """エラーがある場合のサマリーは [NG] を含む。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5).drop(columns=["close"])
        result = validator.validate(df)
        assert "[NG]" in result.summary()


class TestNaNRows:
    def test_nan_rows_detected(self):
        """NaN 行がある → nan_rows > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[3, "close"] = float("nan")
        df.at[7, "open"] = float("nan")
        result = validator.validate(df, timeframe="M15")
        assert result.nan_rows > 0

    def test_nan_rows_count(self):
        """NaN 行数が正確にカウントされる。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[2, "close"] = float("nan")
        df.at[5, "high"] = float("nan")
        result = validator.validate(df, timeframe="M15")
        assert result.nan_rows == 2

    def test_nan_rows_generate_warning(self):
        """NaN 行がある → warnings に含まれる。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[0, "close"] = float("nan")
        result = validator.validate(df)
        assert any("NaN" in w for w in result.warnings)


class TestDuplicateTimestamps:
    def test_duplicate_timestamps_detected(self):
        """重複タイムスタンプ → duplicate_timestamps > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        # row 5 の timestamp を row 3 と同じにする
        df.at[5, "timestamp"] = df.at[3, "timestamp"]
        result = validator.validate(df, timeframe="M15")
        assert result.duplicate_timestamps > 0

    def test_duplicate_timestamps_count(self):
        """重複件数が正確にカウントされる。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[4, "timestamp"] = df.at[1, "timestamp"]
        df.at[8, "timestamp"] = df.at[2, "timestamp"]
        result = validator.validate(df)
        assert result.duplicate_timestamps == 2

    def test_no_duplicates_returns_zero(self):
        """重複なし → duplicate_timestamps=0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        result = validator.validate(df)
        assert result.duplicate_timestamps == 0


class TestTimeSeriesReversal:
    def test_time_series_reversal_warning(self):
        """時系列逆転 → warnings に含まれる。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        # 意図的に逆順にする
        df = df.iloc[::-1].reset_index(drop=True)
        result = validator.validate(df, timeframe="M15")
        reversal_warnings = [w for w in result.warnings if "単調増加" in w or "逆転" in w]
        assert len(reversal_warnings) > 0

    def test_sorted_timestamps_no_reversal_warning(self):
        """正しく昇順ソートされている場合は逆転 warning なし。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        result = validator.validate(df)
        reversal_warnings = [w for w in result.warnings if "単調増加" in w or "逆転" in w]
        assert len(reversal_warnings) == 0


class TestFutureData:
    def test_future_data_detected(self):
        """未来のタイムスタンプ → future_rows > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5)
        # 未来の日付を設定
        df.at[2, "timestamp"] = pd.Timestamp("2099-01-01", tz="UTC")
        result = validator.validate(df, timeframe="M15")
        assert result.future_rows > 0

    def test_no_future_data(self):
        """過去データのみ → future_rows=0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        result = validator.validate(df)
        assert result.future_rows == 0

    def test_future_data_generates_warning(self):
        """未来データがある → warnings に含まれる。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=5)
        df.at[0, "timestamp"] = pd.Timestamp("2099-12-31", tz="UTC")
        result = validator.validate(df)
        assert any("未来" in w for w in result.warnings)


class TestOHLCViolation:
    def test_ohlc_violation_high_lt_low(self):
        """high < low → ohlc_violations > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        # high < low に設定
        df.at[3, "high"] = 154.0
        df.at[3, "low"] = 156.0
        result = validator.validate(df, timeframe="M15")
        assert result.ohlc_violations > 0

    def test_ohlc_violation_high_lt_close(self):
        """high < close → ohlc_violations > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[5, "high"] = 154.0
        df.at[5, "close"] = 156.0
        df.at[5, "low"] = 153.0
        result = validator.validate(df)
        assert result.ohlc_violations > 0

    def test_valid_ohlc_no_violation(self):
        """正常な OHLCV → ohlc_violations=0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        result = validator.validate(df)
        assert result.ohlc_violations == 0


class TestPriceRangeViolation:
    def test_price_range_violation_too_high(self):
        """価格が1000円 → price_range_violations > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[4, "close"] = 1000.0
        df.at[4, "high"] = 1000.5
        df.at[4, "low"] = 999.5
        df.at[4, "open"] = 1000.0
        result = validator.validate(df, timeframe="M15")
        assert result.price_range_violations > 0

    def test_price_range_violation_too_low(self):
        """価格が10円（範囲外）→ price_range_violations > 0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10)
        df.at[1, "close"] = 10.0
        df.at[1, "high"] = 10.5
        df.at[1, "low"] = 9.5
        df.at[1, "open"] = 10.0
        result = validator.validate(df)
        assert result.price_range_violations > 0

    def test_normal_price_range_no_violation(self):
        """正常な USD/JPY 価格範囲 → price_range_violations=0。"""
        validator = OHLCVValidator()
        df = _make_valid_df(n=10, price=155.0)
        result = validator.validate(df)
        assert result.price_range_violations == 0


class TestEmptyDataframe:
    def test_empty_dataframe_is_invalid(self):
        """空の DataFrame → is_valid=False。"""
        validator = OHLCVValidator()
        result = validator.validate(pd.DataFrame())
        assert result.is_valid is False
        assert result.row_count == 0

    def test_none_like_empty_handling(self):
        """空の DataFrame でも例外が起きない。"""
        validator = OHLCVValidator()
        result = validator.validate(pd.DataFrame(), timeframe="M15")
        assert result is not None
