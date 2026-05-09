"""
H1BacktestRunner のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.fx.h1_backtest_runner import H1BacktestRunner
from src.fx.market_regime import MarketRegime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_h1(n: int = 2000, seed: int = 42, trend: str = "up") -> pd.DataFrame:
    """テスト用 H1 OHLCV データを生成する。"""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    returns = rng.normal(0, 0.001, size=n)
    if trend == "up":
        bias = np.linspace(0, 0.05, n)
    elif trend == "down":
        bias = np.linspace(0, -0.05, n)
    else:
        bias = np.zeros(n)
    closes = 150.0 * np.exp(np.cumsum(returns) + bias)
    highs = closes * (1 + rng.uniform(0.0005, 0.002, size=n))
    lows = closes * (1 - rng.uniform(0.0005, 0.002, size=n))
    opens = np.roll(closes, 1)
    opens[0] = 150.0
    volumes = rng.integers(1000, 10000, size=n).astype(float)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _make_ohlcv_d1(n: int = 500, seed: int = 42, trend: str = "up") -> pd.DataFrame:
    """テスト用 D1 OHLCV データを生成する。"""
    rng = np.random.default_rng(seed + 100)
    timestamps = pd.date_range("2022-01-01", periods=n, freq="1D", tz="UTC")
    if trend == "up":
        closes = np.linspace(130.0, 160.0, n)
    elif trend == "down":
        closes = np.linspace(160.0, 130.0, n)
    else:
        closes = np.full(n, 150.0)
    closes = closes + rng.normal(0, 0.5, size=n)
    highs = closes * (1 + rng.uniform(0.001, 0.005, size=n))
    lows = closes * (1 - rng.uniform(0.001, 0.005, size=n))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = rng.integers(10000, 100000, size=n).astype(float)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunFullValidation:
    def test_run_full_validation_returns_dict(self):
        """run_full_validation() が正常に dict を返す。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=1000)
        df_d1 = _make_ohlcv_d1(n=300)

        result = runner.run_full_validation(df_h1, df_d1)

        assert isinstance(result, dict)
        assert "params" in result
        assert "data_info" in result
        assert "train" in result
        assert "val" in result
        assert "test" in result
        assert "regime_summary" in result

    def test_data_info_correct(self):
        """data_info に h1_rows, d1_rows, period が含まれる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=500)
        df_d1 = _make_ohlcv_d1(n=200)

        # d1_source="direct" で渡した df_d1 の行数が data_info に反映される
        result = runner.run_full_validation(df_h1, df_d1, d1_source="direct")

        info = result["data_info"]
        assert "h1_rows" in info
        assert "d1_rows" in info
        assert "period" in info
        assert info["h1_rows"] == len(df_h1)
        assert info["d1_rows"] == len(df_d1)

    def test_params_in_result(self):
        """params に主要なパラメータが含まれる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=500)
        df_d1 = _make_ohlcv_d1(n=200)

        result = runner.run_full_validation(df_h1, df_d1, ema_fast=20, ema_slow=100)

        params = result["params"]
        assert params["ema_fast"] == 20
        assert params["ema_slow"] == 100
        assert "direction" in params


class TestSplitRatio:
    def test_split_ratio(self):
        """train/val/test の行数比が約6:2:2。"""
        runner = H1BacktestRunner()
        n = 1000
        df = _make_ohlcv_h1(n=n)

        df_train, df_val, df_test = runner._split(df, train=0.6, val=0.2)

        assert len(df_train) == 600
        assert len(df_val) == 200
        assert len(df_test) == 200

    def test_split_no_overlap(self):
        """train/val/test に時系列の重複がない。"""
        runner = H1BacktestRunner()
        n = 300
        df = _make_ohlcv_h1(n=n)
        df_train, df_val, df_test = runner._split(df)

        train_ts = set(df_train["timestamp"].astype(str))
        val_ts = set(df_val["timestamp"].astype(str))
        test_ts = set(df_test["timestamp"].astype(str))

        assert len(train_ts & val_ts) == 0, "train と val に重複あり"
        assert len(val_ts & test_ts) == 0, "val と test に重複あり"
        assert len(train_ts & test_ts) == 0, "train と test に重複あり"

    def test_split_total_rows(self):
        """分割後の合計行数が元のデータと一致する。"""
        runner = H1BacktestRunner()
        n = 999
        df = _make_ohlcv_h1(n=n)
        df_train, df_val, df_test = runner._split(df)

        total = len(df_train) + len(df_val) + len(df_test)
        assert total == n, f"合計行数が不一致: {total} != {n}"


class TestDirectionFilter:
    def test_direction_long_only(self):
        """long_only で SELL カウントが 0 になる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=2000)
        df_d1 = _make_ohlcv_d1(n=500)

        result = runner.run_full_validation(
            df_h1, df_d1,
            ema_fast=20, ema_slow=100,
            direction="long_only",
        )

        # train + val + test の sell_count がすべて 0
        assert result["train"].sell_count == 0, (
            f"long_only なのに train.sell_count={result['train'].sell_count}"
        )
        assert result["val"].sell_count == 0, (
            f"long_only なのに val.sell_count={result['val'].sell_count}"
        )
        assert result["test"].sell_count == 0, (
            f"long_only なのに test.sell_count={result['test'].sell_count}"
        )

    def test_direction_short_only(self):
        """short_only で BUY カウントが 0 になる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=2000)
        df_d1 = _make_ohlcv_d1(n=500)

        result = runner.run_full_validation(
            df_h1, df_d1,
            ema_fast=20, ema_slow=100,
            direction="short_only",
        )

        assert result["train"].buy_count == 0, (
            f"short_only なのに train.buy_count={result['train'].buy_count}"
        )
        assert result["val"].buy_count == 0, (
            f"short_only なのに val.buy_count={result['val'].buy_count}"
        )
        assert result["test"].buy_count == 0, (
            f"short_only なのに test.buy_count={result['test'].buy_count}"
        )


class TestRegimeSummary:
    def test_regime_summary_keys(self):
        """regime_summary に 'uptrend', 'downtrend', 'range' が含まれる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=1000)
        df_d1 = _make_ohlcv_d1(n=300)

        result = runner.run_full_validation(df_h1, df_d1)

        regime_summary = result["regime_summary"]
        assert MarketRegime.UP.value in regime_summary, "'uptrend' が regime_summary にない"
        assert MarketRegime.DOWN.value in regime_summary, "'downtrend' が regime_summary にない"
        assert MarketRegime.RANGE.value in regime_summary, "'range' が regime_summary にない"

    def test_regime_summary_structure(self):
        """各 regime に trade_count, win_rate, profit_factor が含まれる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=500)
        df_d1 = _make_ohlcv_d1(n=200)

        result = runner.run_full_validation(df_h1, df_d1)

        for regime_val in [MarketRegime.UP.value, MarketRegime.DOWN.value, MarketRegime.RANGE.value]:
            data = result["regime_summary"][regime_val]
            assert "trade_count" in data, f"{regime_val}: trade_count がない"
            assert "win_rate" in data, f"{regime_val}: win_rate がない"
            assert "profit_factor" in data, f"{regime_val}: profit_factor がない"
            assert isinstance(data["trade_count"], int), f"{regime_val}: trade_count が int でない"
            assert 0.0 <= data["win_rate"] <= 1.0, f"{regime_val}: win_rate が範囲外"

    def test_regime_summary_trade_count_total(self):
        """regime 別の trade_count の合計が全トレード数と一致する。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=1000)
        df_d1 = _make_ohlcv_d1(n=300)

        result = runner.run_full_validation(df_h1, df_d1)

        total_from_regime = sum(
            data["trade_count"] for data in result["regime_summary"].values()
        )
        total_from_results = (
            result["train"].trade_count
            + result["val"].trade_count
            + result["test"].trade_count
        )
        assert total_from_regime == total_from_results, (
            f"regime別合計 ({total_from_regime}) != 全トレード数 ({total_from_results})"
        )


class TestD1Source:
    def test_d1_source_resample(self):
        """d1_source="resample" で D1 が H1 から生成される（data_info.d1_rows が yfinance 直接より多い）。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=1000)
        df_d1 = _make_ohlcv_d1(n=300)

        result_resample = runner.run_full_validation(df_h1, df_d1, d1_source="resample")
        result_direct = runner.run_full_validation(df_h1, df_d1, d1_source="direct")

        # resample ではH1データから生成するので d1_rows はH1本数/24に近い
        # direct では渡した df_d1 の行数がそのまま使われる
        assert isinstance(result_resample, dict), "d1_source='resample' で dict が返されない"
        assert isinstance(result_direct, dict), "d1_source='direct' で dict が返されない"

        # resample の d1_rows は H1 データから生成される（約 1000/24 ≈ 41本）
        d1_resample_rows = result_resample["data_info"]["d1_rows"]
        d1_direct_rows = result_direct["data_info"]["d1_rows"]

        assert d1_resample_rows > 0, "resample 後の D1 が空"
        assert d1_direct_rows == len(df_d1), (
            f"direct 時の d1_rows が df_d1 の行数と異なる: {d1_direct_rows} != {len(df_d1)}"
        )
        # resample の行数と direct の行数は通常異なる（H1データ期間の違いによる）
        assert d1_resample_rows != d1_direct_rows, (
            "resample と direct の d1_rows が同じ（予期しない状況）"
        )

    def test_d1_source_direct_uses_passed_d1(self):
        """d1_source="direct" で渡した df_d1 がそのまま使われる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=500)
        df_d1 = _make_ohlcv_d1(n=100)

        result = runner.run_full_validation(df_h1, df_d1, d1_source="direct")
        assert result["data_info"]["d1_rows"] == len(df_d1), (
            "d1_source='direct' なのに data_info.d1_rows が df_d1 の行数と異なる"
        )


class TestRegimeFilter:
    def test_regime_filter_uptrend_only(self):
        """regime_filter=["uptrend"] で downtrend/range のシグナルが除外される（トレード数が減る）。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=2000)
        df_d1 = _make_ohlcv_d1(n=500)

        # フィルターなし
        result_all = runner.run_full_validation(
            df_h1, df_d1, ema_fast=20, ema_slow=100, direction="both",
            regime_filter=None,
        )
        # uptrend のみ
        result_up = runner.run_full_validation(
            df_h1, df_d1, ema_fast=20, ema_slow=100, direction="both",
            regime_filter=["uptrend"],
        )

        total_all = (
            result_all["train"].trade_count
            + result_all["val"].trade_count
            + result_all["test"].trade_count
        )
        total_up = (
            result_up["train"].trade_count
            + result_up["val"].trade_count
            + result_up["test"].trade_count
        )

        # uptrend のみのフィルターを当てればトレード数は減少するか等しい（全部 uptrend の場合）
        assert total_up <= total_all, (
            f"regime_filter=['uptrend'] なのにトレード数が増加: {total_up} > {total_all}"
        )

    def test_regime_filter_none_same_as_no_filter(self):
        """regime_filter=None はフィルターなしと同じ結果になる。"""
        runner = H1BacktestRunner()
        df_h1 = _make_ohlcv_h1(n=1000)
        df_d1 = _make_ohlcv_d1(n=300)

        result_none = runner.run_full_validation(df_h1, df_d1, regime_filter=None)
        result_default = runner.run_full_validation(df_h1, df_d1)

        assert result_none["train"].trade_count == result_default["train"].trade_count, (
            "regime_filter=None とデフォルト呼び出しでトレード数が異なる"
        )
        assert result_none["val"].trade_count == result_default["val"].trade_count, (
            "regime_filter=None とデフォルト呼び出しで val トレード数が異なる"
        )
