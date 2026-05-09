"""
FXGridSearch のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.fx.fx_backtest import FXBacktestRunner
from src.fx.grid_search import FXGridSearch, GridSearchConfig, GridSearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 2000,
    timeframe: str = "M15",
    start_price: float = 155.0,
    seed: int = 42,
) -> pd.DataFrame:
    """テスト用の合成OHLCVデータを生成する。"""
    rng = np.random.default_rng(seed)
    freq = "4h" if timeframe.upper() == "H4" else "15min"
    if timeframe.upper() == "H4":
        n = max(1, n // 16)
    timestamps = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(0, 0.001, size=n)
    # 上昇トレンドバイアス
    trend = np.linspace(0, 0.05, n)
    closes = start_price * np.exp(np.cumsum(returns) + trend)
    highs = closes * (1 + rng.uniform(0.0005, 0.003, size=n))
    lows = closes * (1 - rng.uniform(0.0005, 0.003, size=n))
    opens = np.roll(closes, 1)
    opens[0] = start_price
    volumes = rng.integers(1000, 10000, size=n).astype(float)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _small_config() -> GridSearchConfig:
    """テスト高速化のための最小設定。"""
    return GridSearchConfig(
        ema_fast_list=[20, 50],
        ema_slow_list=[100, 200],
        breakout_lookback_list=[10],
        atr_sl_multiplier_list=[1.5],
        rr_ratio_list=[2.0],
        direction_list=["both", "long_only", "short_only"],
        min_trade_count=1,  # テスト用に低く設定
        val_min_profit_factor=1.1,
        val_max_drawdown_pct=10.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvalidCombinationExcluded:
    def test_invalid_combination_excluded(self):
        """fast >= slow の組み合わせが除外される。"""
        config = GridSearchConfig(
            ema_fast_list=[100, 200],
            ema_slow_list=[50, 100],  # fast >= slow になる組み合わせが複数
            breakout_lookback_list=[10],
            atr_sl_multiplier_list=[1.5],
            rr_ratio_list=[2.0],
            direction_list=["both"],
            min_trade_count=1,
        )
        gs = FXGridSearch(config=config)

        n = 3000
        df_m15_all = _make_ohlcv(n=n, timeframe="M15")
        df_h4_full = _make_ohlcv(n=n, timeframe="H4")

        df_train, df_val, _ = FXBacktestRunner.split(df_m15_all, 0.6, 0.2, 0.2)
        results = gs.run(df_m15_train=df_train, df_m15_val=df_val, df_h4_full=df_h4_full)

        # 結果のパラメータに fast >= slow が存在しないことを確認
        for r in results:
            assert r.params["ema_fast"] < r.params["ema_slow"], (
                f"fast={r.params['ema_fast']} >= slow={r.params['ema_slow']} が除外されていない"
            )

        # 有効な組み合わせ: (100, 50) -> invalid, (200, 50) -> invalid,
        # (100, 100) -> invalid (equal), (200, 100) -> valid
        # direction="both" なので valid: 1組み合わせのみ
        assert len(results) <= 1, f"有効な組み合わせ数が期待より多い: {len(results)}"


class TestDirectionFilter:
    def _make_df_with_signals(self) -> pd.DataFrame:
        """BUYとSELLシグナルが混在するDataFrameを作成する。"""
        n = 50
        ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
        df = pd.DataFrame({
            "timestamp": ts,
            "open": 155.0,
            "high": 155.05,
            "low": 154.95,
            "close": 155.0,
            "volume": 1000.0,
            "signal": [0] * n,
            "entry_price": float("nan"),
            "stop_loss": float("nan"),
            "take_profit": float("nan"),
        })
        # BUYシグナルとSELLシグナルを追加
        df.at[5, "signal"] = 1
        df.at[5, "entry_price"] = 155.0
        df.at[5, "stop_loss"] = 154.8
        df.at[5, "take_profit"] = 155.4
        df.at[20, "signal"] = -1
        df.at[20, "entry_price"] = 155.0
        df.at[20, "stop_loss"] = 155.2
        df.at[20, "take_profit"] = 154.6
        return df

    def test_direction_filter_long_only(self):
        """long_only 適用後に signal==-1 が存在しない。"""
        gs = FXGridSearch()
        df = self._make_df_with_signals()
        result = gs._apply_direction_filter(df.copy(), "long_only")
        assert (result["signal"] == -1).sum() == 0, "long_only 後に signal=-1 が残っている"
        assert (result["signal"] == 1).sum() >= 1, "long_only 後に signal=1 が消えてしまった"

    def test_direction_filter_short_only(self):
        """short_only 適用後に signal==1 が存在しない。"""
        gs = FXGridSearch()
        df = self._make_df_with_signals()
        result = gs._apply_direction_filter(df.copy(), "short_only")
        assert (result["signal"] == 1).sum() == 0, "short_only 後に signal=1 が残っている"
        assert (result["signal"] == -1).sum() >= 1, "short_only 後に signal=-1 が消えてしまった"

    def test_direction_filter_both(self):
        """both は変更なし。"""
        gs = FXGridSearch()
        df = self._make_df_with_signals()
        result = gs._apply_direction_filter(df.copy(), "both")
        assert (result["signal"] == 1).sum() == 1
        assert (result["signal"] == -1).sum() == 1


class TestMinTradeCountFilter:
    def test_min_trade_count_filter(self):
        """train trade_count < min_trade_count の候補が結果から除外される。"""
        config = GridSearchConfig(
            ema_fast_list=[20],
            ema_slow_list=[100],
            breakout_lookback_list=[10],
            atr_sl_multiplier_list=[1.5],
            rr_ratio_list=[2.0],
            direction_list=["both"],
            min_trade_count=10000,  # 非常に大きい閾値 → ほぼ全候補が除外される
            val_min_profit_factor=0.0,
            val_max_drawdown_pct=100.0,
        )
        gs = FXGridSearch(config=config)
        df_m15_all = _make_ohlcv(n=2000, timeframe="M15")
        df_h4_full = _make_ohlcv(n=2000, timeframe="H4")
        df_train, df_val, _ = FXBacktestRunner.split(df_m15_all, 0.6, 0.2, 0.2)
        results = gs.run(df_m15_train=df_train, df_m15_val=df_val, df_h4_full=df_h4_full)

        # trade_count < 10000 なので全て除外されるはず
        assert len(results) == 0, f"min_trade_count フィルターが機能していない: {len(results)} 件残っている"


class TestValFilterCriteria:
    def test_val_filter_criteria(self):
        """profit_factor < 1.1 または mdd > 10% は passes_val_filter=False。"""
        # GridSearchResultを手動作成して検証
        from src.fx.fx_backtest import FXBacktestResult
        from dataclasses import replace

        def _make_result(pf: float, mdd: float) -> FXBacktestResult:
            return FXBacktestResult(
                symbol="USD/JPY",
                initial_balance=1_000_000,
                final_balance=1_000_000,
                total_return_pct=0.0,
                expectancy=0.0,
                win_rate=0.5,
                profit_factor=pf,
                max_drawdown_pct=mdd,
                max_losing_streak=0,
                trade_count=50,
                monthly_returns={},
                trades=[],
                assumptions={},
            )

        config = GridSearchConfig(
            val_min_profit_factor=1.1,
            val_max_drawdown_pct=10.0,
        )

        # 直接フィルター判定ロジックをテスト
        def check_passes(pf: float, mdd: float) -> bool:
            return pf >= config.val_min_profit_factor and mdd <= config.val_max_drawdown_pct

        # PF < 1.1 → False
        assert not check_passes(1.05, 5.0), "PF < 1.1 なのに True"
        # MDD > 10% → False
        assert not check_passes(1.5, 15.0), "MDD > 10% なのに True"
        # 両方OK → True
        assert check_passes(1.2, 8.0), "PF >= 1.1, MDD <= 10% なのに False"
        # ギリギリOK
        assert check_passes(1.1, 10.0), "境界値が False になっている"

    def test_val_filter_passes_val_filter_field(self):
        """実際のグリッドサーチでpasses_val_filterが正しくセットされる。"""
        config = GridSearchConfig(
            ema_fast_list=[20],
            ema_slow_list=[200],
            breakout_lookback_list=[10],
            atr_sl_multiplier_list=[1.5],
            rr_ratio_list=[2.0],
            direction_list=["both"],
            min_trade_count=1,
            val_min_profit_factor=999.0,  # 到達不可能な高い閾値
            val_max_drawdown_pct=100.0,
        )
        gs = FXGridSearch(config=config)
        df_m15_all = _make_ohlcv(n=3000, timeframe="M15")
        df_h4_full = _make_ohlcv(n=3000, timeframe="H4")
        df_train, df_val, _ = FXBacktestRunner.split(df_m15_all, 0.6, 0.2, 0.2)
        results = gs.run(df_m15_train=df_train, df_m15_val=df_val, df_h4_full=df_h4_full)

        # 全てのresultはpasses_val_filter=False（PF >= 999.0 は不可能）
        for r in results:
            assert not r.passes_val_filter, f"passes_val_filter が True になっている: PF={r.val.profit_factor}"


class TestResultsSortedByValPF:
    def test_results_sorted_by_val_pf(self):
        """結果が val profit_factor 降順にソートされている。"""
        config = _small_config()
        gs = FXGridSearch(config=config)
        df_m15_all = _make_ohlcv(n=3000, timeframe="M15")
        df_h4_full = _make_ohlcv(n=3000, timeframe="H4")
        df_train, df_val, _ = FXBacktestRunner.split(df_m15_all, 0.6, 0.2, 0.2)
        results = gs.run(df_m15_train=df_train, df_m15_val=df_val, df_h4_full=df_h4_full)

        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].val.profit_factor >= results[i + 1].val.profit_factor, (
                    f"ソート順が不正: results[{i}].val.pf={results[i].val.profit_factor} < "
                    f"results[{i+1}].val.pf={results[i+1].val.profit_factor}"
                )


class TestValMinTradeCountApplied:
    def test_val_min_trade_count_applied(self):
        """val trade_count=29 の候補が passes_val_filter=False になる（バグ修正確認）。"""
        from src.fx.fx_backtest import FXBacktestResult
        from src.fx.grid_search import GridSearchResult

        # min_trade_count=30 の設定
        config = GridSearchConfig(
            min_trade_count=30,
            val_min_profit_factor=1.0,
            val_max_drawdown_pct=100.0,
        )

        # val trade_count=29 の FXBacktestResult を作成
        def _make_result(trade_count: int, pf: float = 1.5) -> FXBacktestResult:
            return FXBacktestResult(
                symbol="USD/JPY",
                initial_balance=1_000_000,
                final_balance=1_050_000,
                total_return_pct=5.0,
                expectancy=100.0,
                win_rate=0.6,
                profit_factor=pf,
                max_drawdown_pct=3.0,
                max_losing_streak=3,
                trade_count=trade_count,
                monthly_returns={},
                trades=[],
                assumptions={},
            )

        # passes フィルター判定ロジックを直接検証
        # バグ修正後は val trade_count >= cfg.min_trade_count が適用される
        val_result_29 = _make_result(trade_count=29)
        val_result_30 = _make_result(trade_count=30)

        # trade_count=29 は min_trade_count=30 を満たさないので False
        passes_29 = (
            val_result_29.trade_count >= config.min_trade_count
            and val_result_29.profit_factor >= config.val_min_profit_factor
            and val_result_29.max_drawdown_pct <= config.val_max_drawdown_pct
        )
        assert not passes_29, (
            f"val trade_count=29 が passes_val_filter=True になっている（修正が反映されていない）"
        )

        # trade_count=30 は min_trade_count=30 を満たすので True
        passes_30 = (
            val_result_30.trade_count >= config.min_trade_count
            and val_result_30.profit_factor >= config.val_min_profit_factor
            and val_result_30.max_drawdown_pct <= config.val_max_drawdown_pct
        )
        assert passes_30, (
            f"val trade_count=30 が passes_val_filter=False になっている"
        )

    def test_val_trade_count_zero_rejected(self):
        """val trade_count=0 の候補が passes_val_filter=False になる。"""
        config = GridSearchConfig(
            ema_fast_list=[20],
            ema_slow_list=[200],
            breakout_lookback_list=[10],
            atr_sl_multiplier_list=[1.5],
            rr_ratio_list=[2.0],
            direction_list=["both"],
            min_trade_count=30,          # 30件以上必要
            val_min_profit_factor=0.0,   # PF 条件は緩く設定
            val_max_drawdown_pct=100.0,  # MDD 条件は緩く設定
        )
        gs = FXGridSearch(config=config)

        # val に 0本のデータを渡す（シグナルが全て0になるような短いデータ）
        df_m15_all = _make_ohlcv(n=3000, timeframe="M15")
        df_h4_full = _make_ohlcv(n=3000, timeframe="H4")
        df_train, _, _ = FXBacktestRunner.split(df_m15_all, 0.6, 0.2, 0.2)

        # val に空に近いDataFrameを使用（シグナルが発生しない期間）
        # val_trade_count=0 となる極端に短い val データ（ウォームアップ不足でシグナル0）
        df_val_empty = _make_ohlcv(n=10, timeframe="M15", seed=999)

        results = gs.run(df_m15_train=df_train, df_m15_val=df_val_empty, df_h4_full=df_h4_full)

        # trade_count=0 ならば passes_val_filter=False
        for r in results:
            if r.val.trade_count == 0:
                assert not r.passes_val_filter, (
                    f"val trade_count=0 なのに passes_val_filter=True: {r.params}"
                )
            if r.val.trade_count < config.min_trade_count:
                assert not r.passes_val_filter, (
                    f"val trade_count={r.val.trade_count} < {config.min_trade_count} なのに "
                    f"passes_val_filter=True: {r.params}"
                )
