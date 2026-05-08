"""
YFinanceFetcher のユニットテスト
実注文なし・yfinance は mock を使用
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.fx.ohlcv_fetcher import YFinanceFetcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_multiindex_df(n: int = 10, price: float = 155.0) -> pd.DataFrame:
    """yfinance が返す MultiIndex カラムの DataFrame をシミュレートする。"""
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    import numpy as np
    data = {
        ("Open", "USDJPY=X"): [price] * n,
        ("High", "USDJPY=X"): [price + 0.05] * n,
        ("Low", "USDJPY=X"): [price - 0.05] * n,
        ("Close", "USDJPY=X"): [price] * n,
        ("Volume", "USDJPY=X"): [1000.0] * n,
    }
    df = pd.DataFrame(data, index=ts)
    df.index.name = "Datetime"
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _make_normalized_df(n: int = 10, price: float = 155.0) -> pd.DataFrame:
    """正規化済みの OHLCV DataFrame を生成する。"""
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

class TestNormalizeColumns:
    def test_normalize_multiindex(self):
        """yfinance の MultiIndex カラムを正規化できる。"""
        raw = _make_multiindex_df(n=10)
        result = YFinanceFetcher._normalize(raw)
        assert "timestamp" in result.columns
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns

    def test_normalize_removes_multiindex(self):
        """正規化後は MultiIndex カラムがない。"""
        raw = _make_multiindex_df(n=10)
        result = YFinanceFetcher._normalize(raw)
        assert not isinstance(result.columns, pd.MultiIndex)

    def test_normalize_timestamp_utc(self):
        """正規化後の timestamp は UTC タイムゾーンである。"""
        raw = _make_multiindex_df(n=10)
        result = YFinanceFetcher._normalize(raw)
        assert result["timestamp"].dt.tz is not None
        assert str(result["timestamp"].dt.tz) in ("UTC", "utc")

    def test_normalize_column_order(self):
        """正規化後のカラム順序は timestamp, open, high, low, close, volume。"""
        raw = _make_multiindex_df(n=10)
        result = YFinanceFetcher._normalize(raw)
        expected_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        assert list(result.columns[:6]) == expected_cols

    def test_normalize_drops_nan_close(self):
        """close が NaN の行は除外される。"""
        raw = _make_multiindex_df(n=5)
        raw.iloc[2, raw.columns.get_level_values(0) == "Close"] = float("nan")
        result = YFinanceFetcher._normalize(raw)
        assert result["close"].isna().sum() == 0


class TestFetch:
    def test_fetch_returns_empty_on_yfinance_error(self, tmp_path):
        """yfinance が例外を投げた場合は空 DataFrame を返す。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        with patch("yfinance.download", side_effect=Exception("network error")):
            result = fetcher.fetch("15m", "60d")
        assert result.empty

    def test_fetch_returns_empty_on_empty_data(self, tmp_path):
        """yfinance が空の DataFrame を返した場合は空 DataFrame を返す。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        with patch("yfinance.download", return_value=pd.DataFrame()):
            result = fetcher.fetch("15m", "60d")
        assert result.empty

    def test_fetch_normalizes_columns(self, tmp_path):
        """yfinance が正常データを返した場合はカラムが正規化される。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        mock_raw = _make_multiindex_df(n=5)
        with patch("yfinance.download", return_value=mock_raw):
            result = fetcher.fetch("15m", "60d")
        assert not result.empty
        assert "timestamp" in result.columns
        assert "close" in result.columns


class TestSaveAndLoad:
    def test_save_creates_file(self, tmp_path):
        """save() がファイルを作成する。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        df = _make_normalized_df(n=10)
        path = fetcher.save(df, timeframe="M15")
        assert path.exists()

    def test_save_and_load_data_matches(self, tmp_path):
        """save() → load_latest() でデータが一致する。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        df = _make_normalized_df(n=10)
        fetcher.save(df, timeframe="M15")
        loaded = fetcher.load_latest("M15")
        assert len(loaded) == len(df)
        # close 値が一致
        assert list(loaded["close"].values) == list(df["close"].values)

    def test_save_empty_df_skips(self, tmp_path):
        """空の DataFrame を save() してもエラーが起きない。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        path = fetcher.save(pd.DataFrame(), timeframe="M15")
        # ファイルは作られるが空ファイルとして返る
        assert path is not None


class TestDuplicateRemoval:
    def test_duplicate_removal_on_save(self, tmp_path):
        """同じデータを2回 save() しても重複しない。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        df = _make_normalized_df(n=10)
        fetcher.save(df, timeframe="M15")
        fetcher.save(df, timeframe="M15")
        loaded = fetcher.load_latest("M15")
        # 重複なし: 10 本のまま
        assert len(loaded) == 10

    def test_merge_different_data_on_save(self, tmp_path):
        """異なる期間のデータを2回 save() すると合計件数になる（重複除去）。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        df1 = _make_normalized_df(n=10, price=155.0)
        # df2 は df1 の続き（タイムスタンプが異なる）
        ts2 = pd.date_range("2024-01-01 02:30:00", periods=10, freq="15min", tz="UTC")
        df2 = df1.copy()
        df2["timestamp"] = ts2

        fetcher.save(df1, timeframe="M15")
        fetcher.save(df2, timeframe="M15")
        loaded = fetcher.load_latest("M15")
        # 合計20本（重複なし）
        assert len(loaded) == 20


class TestLoadEmpty:
    def test_load_empty_when_no_files(self, tmp_path):
        """ファイルがない場合は空 DataFrame を返す。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        result = fetcher.load_latest("M15")
        assert result.empty

    def test_load_empty_when_wrong_timeframe(self, tmp_path):
        """存在しない時間足の場合は空 DataFrame を返す。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        df = _make_normalized_df(n=5)
        fetcher.save(df, timeframe="M15")
        result = fetcher.load_latest("H4")
        assert result.empty


class TestFetchH4:
    def test_fetch_h4_uses_resample(self, tmp_path):
        """fetch_h4() は H1 データを H4 にリサンプルする。"""
        fetcher = YFinanceFetcher(save_dir=tmp_path)
        # H1 データをシミュレート（48本 = 2日分）
        ts = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
        mock_h1_normalized = pd.DataFrame(
            {
                "timestamp": ts,
                "open": [155.0] * 48,
                "high": [155.05] * 48,
                "low": [154.95] * 48,
                "close": [155.0] * 48,
                "volume": [1000.0] * 48,
            }
        )
        with patch.object(fetcher, "fetch", return_value=mock_h1_normalized):
            result = fetcher.fetch_h4(period="730d")
        # 48本の H1 → 最大12本の H4
        assert not result.empty
        assert len(result) <= 12
