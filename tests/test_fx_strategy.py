"""
MultiTimeframeEMAStrategy のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.fx.strategy import MultiTimeframeEMAStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_h4(n: int, close_series: list[float]) -> pd.DataFrame:
    """簡易 H4 DataFrame を生成する。"""
    timestamps = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = np.array(close_series[:n], dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close * 0.999,
            "high": close * 1.001,
            "low": close * 0.998,
            "close": close,
            "volume": np.ones(n) * 1000,
        }
    )


def _make_m15(n: int, close_series: list[float]) -> pd.DataFrame:
    """簡易 M15 DataFrame を生成する。"""
    timestamps = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = np.array(close_series[:n], dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.997,
            "close": close,
            "volume": np.ones(n) * 500,
        }
    )


def _make_uptrend_h4(n: int = 300) -> pd.DataFrame:
    """EMA50 > EMA200 となるような上昇トレンドデータを生成する。"""
    # 単調増加 + 初期値を高めに設定して EMA50 > EMA200 が確実に成立するよう仕掛ける
    base = np.linspace(100.0, 160.0, n)
    return _make_h4(n, base.tolist())


def _make_downtrend_h4(n: int = 300) -> pd.DataFrame:
    """EMA50 < EMA200 となるような下降トレンドデータを生成する。"""
    base = np.linspace(160.0, 100.0, n)
    return _make_h4(n, base.tolist())


def _make_flat_m15(n: int = 500, price: float = 155.0) -> pd.DataFrame:
    """フラットな M15 データ（ブレイクアウトが起きない）。"""
    return _make_m15(n, [price] * n)


def _default_strategy(**kwargs) -> MultiTimeframeEMAStrategy:
    defaults = dict(
        ema_fast=10,
        ema_slow=30,
        breakout_lookback=5,
        atr_period=5,
        atr_sl_multiplier=1.5,
        rr_ratio=2.0,
    )
    defaults.update(kwargs)
    return MultiTimeframeEMAStrategy(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEMATrend:
    def test_ema_uptrend(self):
        """EMA50 > EMA200 の合成データで trend='UP' が現れる。"""
        strategy = _default_strategy()
        df_h4 = _make_uptrend_h4(300)
        df_m15 = _make_flat_m15(500, price=130.0)
        result = strategy.generate_signals(df_h4, df_m15)
        # 十分に EMA が収束した後半の行で UP が存在すること
        assert (result["trend"] == "UP").any(), "UP トレンドが検出されなかった"

    def test_ema_downtrend(self):
        """EMA50 < EMA200 の合成データで trend='DOWN' が現れる。"""
        strategy = _default_strategy()
        df_h4 = _make_downtrend_h4(300)
        df_m15 = _make_flat_m15(500, price=130.0)
        result = strategy.generate_signals(df_h4, df_m15)
        assert (result["trend"] == "DOWN").any(), "DOWN トレンドが検出されなかった"


class TestSignalGeneration:
    def test_buy_signal_on_breakout(self):
        """UP トレンド中に高値ブレイクアウト → signal=1 が生成される。"""
        strategy = _default_strategy(breakout_lookback=5)
        df_h4 = _make_uptrend_h4(300)

        # 前半は安定した価格、後半で急騰させて高値ブレイクを作る
        prices = [130.0] * 480 + [170.0] * 20
        df_m15 = _make_m15(500, prices)

        result = strategy.generate_signals(df_h4, df_m15)
        # UP トレンド中にシグナルが少なくとも 1 件あること
        up_mask = result["trend"] == "UP"
        assert (result.loc[up_mask, "signal"] == 1).any(), "UP トレンド中に BUY シグナルが生成されなかった"

    def test_sell_signal_on_breakout(self):
        """DOWN トレンド中に安値ブレイクアウト → signal=-1 が生成される。"""
        strategy = _default_strategy(breakout_lookback=5)
        df_h4 = _make_downtrend_h4(300)

        # 前半は安定した価格、後半で急落させて安値ブレイクを作る
        prices = [130.0] * 480 + [90.0] * 20
        df_m15 = _make_m15(500, prices)

        result = strategy.generate_signals(df_h4, df_m15)
        down_mask = result["trend"] == "DOWN"
        assert (result.loc[down_mask, "signal"] == -1).any(), "DOWN トレンド中に SELL シグナルが生成されなかった"

    def test_no_signal_counter_trend(self):
        """UP トレンドで安値ブレイクしてもシグナルなし（カウンタートレードは無視）。"""
        strategy = _default_strategy(breakout_lookback=5)
        df_h4 = _make_uptrend_h4(300)

        # 後半で急落させるが、H4 トレンドは UP のまま
        prices = [130.0] * 480 + [90.0] * 20
        df_m15 = _make_m15(500, prices)

        result = strategy.generate_signals(df_h4, df_m15)
        up_mask = result["trend"] == "UP"
        # UP トレンド中に -1 シグナルがないこと
        assert not (result.loc[up_mask, "signal"] == -1).any(), "UP トレンド中に SELL シグナルが生成された（想定外）"


class TestATRAndLevels:
    def test_atr_computed(self):
        """atr カラムが存在し、すべて正の値である（NaN 除く）。"""
        strategy = _default_strategy()
        df_h4 = _make_uptrend_h4(300)
        df_m15 = _make_flat_m15(500)
        result = strategy.generate_signals(df_h4, df_m15)
        assert "atr" in result.columns
        valid_atr = result["atr"].dropna()
        assert len(valid_atr) > 0
        assert (valid_atr > 0).all(), "ATR に非正の値が含まれる"

    def test_stop_loss_and_tp_set(self):
        """signal=1 のとき stop_loss < entry_price かつ take_profit > entry_price。"""
        strategy = _default_strategy(breakout_lookback=5)
        df_h4 = _make_uptrend_h4(300)
        prices = [130.0] * 480 + [170.0] * 20
        df_m15 = _make_m15(500, prices)
        result = strategy.generate_signals(df_h4, df_m15)

        buy_rows = result[result["signal"] == 1]
        if len(buy_rows) == 0:
            pytest.skip("BUY シグナルがなかったためスキップ")

        for _, row in buy_rows.iterrows():
            assert row["stop_loss"] < row["entry_price"], (
                f"stop_loss ({row['stop_loss']}) >= entry_price ({row['entry_price']})"
            )
            assert row["take_profit"] > row["entry_price"], (
                f"take_profit ({row['take_profit']}) <= entry_price ({row['entry_price']})"
            )
