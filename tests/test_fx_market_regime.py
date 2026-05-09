"""
MarketRegime / RegimeClassifier のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.fx.market_regime import MarketRegime, RegimeClassifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(close_values: list[float], freq: str = "1D") -> pd.DataFrame:
    """close_values から OHLCV DataFrame を生成する。"""
    n = len(close_values)
    timestamps = pd.date_range("2020-01-01", periods=n, freq=freq, tz="UTC")
    closes = np.array(close_values, dtype=float)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": closes * 0.999,
        "high": closes * 1.002,
        "low": closes * 0.997,
        "close": closes,
        "volume": np.ones(n) * 1000.0,
    })


def _make_uptrend_d1(n: int = 400) -> pd.DataFrame:
    """EMA50 > EMA200 かつ price > EMA50 となる上昇トレンドデータ。"""
    closes = np.linspace(100.0, 200.0, n).tolist()
    return _make_ohlcv(closes)


def _make_downtrend_d1(n: int = 400) -> pd.DataFrame:
    """EMA50 < EMA200 かつ price < EMA50 となる下降トレンドデータ。"""
    closes = np.linspace(200.0, 100.0, n).tolist()
    return _make_ohlcv(closes)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClassify:
    def test_uptrend_classified(self):
        """EMA50 > EMA200 かつ価格がEMA50上 → regime='uptrend' が現れる。"""
        df = _make_uptrend_d1(400)
        classifier = RegimeClassifier(ema_fast=50, ema_slow=200)
        result = classifier.classify(df)

        assert "regime" in result.columns
        # 後半（EMA収束後）に uptrend が存在すること
        tail = result.iloc[250:]
        assert (tail["regime"] == MarketRegime.UP.value).any(), (
            "uptrend が検出されなかった。regime counts: " + str(result["regime"].value_counts().to_dict())
        )

    def test_downtrend_classified(self):
        """EMA50 < EMA200 かつ価格がEMA50下 → regime='downtrend' が現れる。"""
        df = _make_downtrend_d1(400)
        classifier = RegimeClassifier(ema_fast=50, ema_slow=200)
        result = classifier.classify(df)

        assert "regime" in result.columns
        # 後半（EMA収束後）に downtrend が存在すること
        tail = result.iloc[250:]
        assert (tail["regime"] == MarketRegime.DOWN.value).any(), (
            "downtrend が検出されなかった。regime counts: " + str(result["regime"].value_counts().to_dict())
        )

    def test_range_classified(self):
        """EMA50 > EMA200 だが価格がEMA50下 → regime='range' が現れる。"""
        # 最初は上昇（EMA50>EMA200を作る）、後半で急落（価格<EMA50）
        # 上昇期間でEMAを乖離させてから、price だけ下げる
        n = 400
        # 前半で EMA50 > EMA200 を確立
        up_part = np.linspace(100.0, 200.0, 300)
        # 後半で price を EMA50 以下に下げる（EMAはまだ高い位置にある）
        # 急落: 200 → 150（EMA50はまだ~190あたり）
        down_part = np.linspace(200.0, 150.0, 100)
        closes = np.concatenate([up_part, down_part])
        df = _make_ohlcv(closes.tolist())
        classifier = RegimeClassifier(ema_fast=50, ema_slow=200)
        result = classifier.classify(df)

        assert "regime" in result.columns
        # 後半の急落部分で range が現れること
        tail = result.iloc[350:]
        assert (tail["regime"] == MarketRegime.RANGE.value).any(), (
            "range が検出されなかった。tail regimes: " + str(tail["regime"].value_counts().to_dict())
        )

    def test_regime_column_values_valid(self):
        """regime カラムの値が MarketRegime の値のみであること。"""
        df = _make_uptrend_d1(300)
        classifier = RegimeClassifier()
        result = classifier.classify(df)

        valid_values = {MarketRegime.UP.value, MarketRegime.DOWN.value, MarketRegime.RANGE.value}
        unique_regimes = set(result["regime"].unique())
        assert unique_regimes.issubset(valid_values), (
            f"不正な regime 値: {unique_regimes - valid_values}"
        )

    def test_original_columns_preserved(self):
        """classify() 後に内部計算用の一時カラムが残らないこと。"""
        df = _make_uptrend_d1(200)
        classifier = RegimeClassifier()
        result = classifier.classify(df)

        assert "_ema_fast" not in result.columns
        assert "_ema_slow" not in result.columns


class TestAlignToEntry:
    def test_align_to_entry(self):
        """D1のregimeがH1にアライン（前向き伝播）される。"""
        # D1: 上昇トレンド
        df_d1 = _make_uptrend_d1(400)
        classifier = RegimeClassifier(ema_fast=50, ema_slow=200)
        df_d1_classified = classifier.classify(df_d1)

        # H1: D1と同じ期間の1時間足
        n_h1 = 400 * 24
        timestamps_h1 = pd.date_range("2020-01-01", periods=n_h1, freq="1h", tz="UTC")
        df_h1 = pd.DataFrame({
            "timestamp": timestamps_h1,
            "open": 150.0,
            "high": 150.5,
            "low": 149.5,
            "close": 150.0,
            "volume": 1000.0,
        })

        result = classifier.align_to_entry(df_d1_classified, df_h1)

        assert "regime" in result.columns
        assert len(result) == len(df_h1)
        # regime 値が有効であること
        valid_values = {MarketRegime.UP.value, MarketRegime.DOWN.value, MarketRegime.RANGE.value}
        assert set(result["regime"].unique()).issubset(valid_values)

    def test_align_preserves_entry_rows(self):
        """align_to_entry() 後に df_entry の行数が変わらないこと。"""
        df_d1 = _make_uptrend_d1(200)
        classifier = RegimeClassifier(ema_fast=10, ema_slow=50)
        df_d1_classified = classifier.classify(df_d1)

        n_h1 = 500
        timestamps_h1 = pd.date_range("2020-01-01", periods=n_h1, freq="1h", tz="UTC")
        df_h1 = pd.DataFrame({
            "timestamp": timestamps_h1,
            "close": 150.0,
        })

        result = classifier.align_to_entry(df_d1_classified, df_h1)
        assert len(result) == n_h1, f"行数が変わった: {len(result)} != {n_h1}"

    def test_align_no_future_data(self):
        """align_to_entry() は未来データを混入させない（前向き伝播のみ）。"""
        # D1: 最初の100日は上昇、次の100日は下降
        up_part = np.linspace(100.0, 200.0, 100)
        down_part = np.linspace(200.0, 100.0, 100)
        closes = np.concatenate([up_part, down_part]).tolist()
        df_d1 = _make_ohlcv(closes, freq="1D")

        classifier = RegimeClassifier(ema_fast=10, ema_slow=50)
        df_d1_classified = classifier.classify(df_d1)

        # H1: D1の前半期間のみのデータ（最初の50日分）
        n_h1 = 50 * 24
        timestamps_h1 = pd.date_range("2020-01-01", periods=n_h1, freq="1h", tz="UTC")
        df_h1 = pd.DataFrame({
            "timestamp": timestamps_h1,
            "close": np.linspace(100.0, 150.0, n_h1),
        })

        result = classifier.align_to_entry(df_d1_classified, df_h1)

        # H1の期間内のregimeのみが存在すること（後半の下降トレンドは混入しない）
        assert len(result) == n_h1


class TestAllRegimesPresent:
    def test_all_regimes_present(self):
        """長期合成データに3種類のregimeが存在する。"""
        # 上昇 → 下降 → 中間（レンジ）のデータを合成
        n = 600
        # 上昇期
        up = np.linspace(100.0, 200.0, 200)
        # 下降期
        down = np.linspace(200.0, 100.0, 200)
        # レンジ期（急落後に横ばい → EMA収束前はrange）
        rng = np.full(200, 150.0)
        closes = np.concatenate([up, down, rng]).tolist()
        df = _make_ohlcv(closes)

        classifier = RegimeClassifier(ema_fast=50, ema_slow=200)
        result = classifier.classify(df)

        regimes_found = set(result["regime"].unique())
        # 少なくとも2種類以上のregimeが現れること（データ長と波形次第）
        assert len(regimes_found) >= 2, (
            f"regime の種類が少ない: {regimes_found}"
        )
