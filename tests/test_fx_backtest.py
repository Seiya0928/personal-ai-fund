"""
FXBacktestRunner のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from src.fx.fx_backtest import FXBacktestResult, FXBacktestRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FREQ = "15min"


def _base_df(n: int = 100, price: float = 155.0) -> pd.DataFrame:
    """シグナル列を含むベース DataFrame を返す。"""
    ts = pd.date_range("2024-01-01", periods=n, freq=_FREQ, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": price,
            "high": price + 0.05,
            "low": price - 0.05,
            "close": price,
            "volume": 1000.0,
            "signal": 0,
            "entry_price": float("nan"),
            "stop_loss": float("nan"),
            "take_profit": float("nan"),
        }
    )


def _runner(**kwargs) -> FXBacktestRunner:
    defaults = dict(
        initial_balance=1_000_000,
        spread_pips=0.3,
        slippage_pips=0.1,
        commission_pips=0.0,
        pip_value_jpy=100.0,
    )
    defaults.update(kwargs)
    return FXBacktestRunner(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNoTrades:
    def test_no_trades_flat_signal(self):
        """signal=0 のみのデータ → trade_count=0。"""
        df = _base_df(200)
        result = _runner().run(df)
        assert result.trade_count == 0
        assert result.final_balance == result.initial_balance


class TestLongTrades:
    def _make_long_win_df(self, price: float = 155.0) -> pd.DataFrame:
        """BUY シグナル後に TP 到達するデータを生成する。"""
        df = _base_df(50, price)
        # row 0: BUY シグナル
        sl = price - 0.20   # 20 pips SL
        tp = price + 0.40   # 40 pips TP
        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        # row 5: high が TP を超える
        df.at[5, "high"] = tp + 0.10
        return df

    def _make_long_loss_df(self, price: float = 155.0) -> pd.DataFrame:
        """BUY シグナル後に SL 到達するデータを生成する。"""
        df = _base_df(50, price)
        sl = price - 0.20
        tp = price + 0.40
        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        # row 5: low が SL を下回る
        df.at[5, "low"] = sl - 0.05
        return df

    def test_long_trade_win(self):
        """BUY シグナル後に TP 到達 → PnL > 0。"""
        df = self._make_long_win_df()
        result = _runner().run(df)
        assert result.trade_count >= 1
        tp_trades = [t for t in result.trades if t["exit_reason"] == "TP"]
        assert len(tp_trades) >= 1, f"TP トレードがない: {result.trades}"
        assert tp_trades[0]["pnl_jpy"] > 0

    def test_long_trade_loss(self):
        """BUY シグナル後に SL 到達 → PnL < 0。"""
        df = self._make_long_loss_df()
        result = _runner().run(df)
        assert result.trade_count >= 1
        sl_trades = [t for t in result.trades if t["exit_reason"] == "SL"]
        assert len(sl_trades) >= 1, f"SL トレードがない: {result.trades}"
        assert sl_trades[0]["pnl_jpy"] < 0


class TestShortTrades:
    def _make_short_win_df(self, price: float = 155.0) -> pd.DataFrame:
        """SELL シグナル後に TP 到達するデータを生成する。"""
        df = _base_df(50, price)
        sl = price + 0.20
        tp = price - 0.40
        df.at[0, "signal"] = -1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        # row 5: low が TP を下回る
        df.at[5, "low"] = tp - 0.05
        return df

    def test_short_trade_win(self):
        """SELL シグナル後に TP 到達 → PnL > 0。"""
        df = self._make_short_win_df()
        result = _runner().run(df)
        assert result.trade_count >= 1
        tp_trades = [t for t in result.trades if t["exit_reason"] == "TP"]
        assert len(tp_trades) >= 1
        assert tp_trades[0]["pnl_jpy"] > 0


class TestSplit:
    def test_split_ratio(self):
        """split() で時系列順が保たれ合計行数が一致する。"""
        n = 100
        df = _base_df(n)
        train, val, test = FXBacktestRunner.split(df, train=0.6, val=0.2, test=0.2)
        # 合計行数が元の行数と一致
        assert len(train) + len(val) + len(test) == n
        # 時系列順: train の最終 timestamp < val の先頭 timestamp
        if len(train) > 0 and len(val) > 0:
            assert train["timestamp"].iloc[-1] < val["timestamp"].iloc[0]
        if len(val) > 0 and len(test) > 0:
            assert val["timestamp"].iloc[-1] < test["timestamp"].iloc[0]
        # おおよその比率確認
        assert abs(len(train) - 60) <= 2
        assert abs(len(val) - 20) <= 2


class TestMetrics:
    def _make_mixed_trades_df(self, price: float = 155.0) -> pd.DataFrame:
        """勝ちと負けのトレードが混在するデータを生成する。"""
        n = 200
        ts = pd.date_range("2024-01-01", periods=n, freq=_FREQ, tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "volume": 1000.0,
                "signal": 0,
                "entry_price": float("nan"),
                "stop_loss": float("nan"),
                "take_profit": float("nan"),
            }
        )
        # トレード 1: ロング → TP（勝ち）
        sl1 = price - 0.20
        tp1 = price + 0.40
        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl1
        df.at[0, "take_profit"] = tp1
        df.at[5, "high"] = tp1 + 0.10  # TP 到達

        # トレード 2: ロング → SL（負け）
        df.at[20, "signal"] = 1
        df.at[20, "entry_price"] = price
        df.at[20, "stop_loss"] = sl1
        df.at[20, "take_profit"] = tp1
        df.at[25, "low"] = sl1 - 0.05  # SL 到達

        # トレード 3: ロング → SL（負け）
        df.at[40, "signal"] = 1
        df.at[40, "entry_price"] = price
        df.at[40, "stop_loss"] = sl1
        df.at[40, "take_profit"] = tp1
        df.at[45, "low"] = sl1 - 0.05  # SL 到達

        return df

    def test_profit_factor(self):
        """profit_factor = 総利益 / |総損失| が正しく計算される。"""
        df = self._make_mixed_trades_df()
        result = _runner().run(df)
        assert result.trade_count >= 2
        win_total = sum(t["pnl_jpy"] for t in result.trades if t["pnl_jpy"] > 0)
        loss_total = abs(sum(t["pnl_jpy"] for t in result.trades if t["pnl_jpy"] <= 0))
        expected_pf = win_total / loss_total if loss_total > 0 else float("inf")
        assert abs(result.profit_factor - expected_pf) < 0.01, (
            f"profit_factor={result.profit_factor}, expected={expected_pf}"
        )

    def test_max_losing_streak(self):
        """連続負けトレードが正しくカウントされる。"""
        df = self._make_mixed_trades_df()
        result = _runner().run(df)
        # 勝ち→負け→負け の順なので max_losing_streak = 2
        assert result.max_losing_streak >= 2

    def test_monthly_returns_keys(self):
        """monthly_returns のキーが 'YYYY-MM' 形式である。"""
        # 複数月にまたがるデータを生成（勝ちトレードのみ）
        n = 200
        ts = pd.date_range("2024-01-01", periods=n, freq="12h", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": 155.0,
                "high": 155.05,
                "low": 154.95,
                "close": 155.0,
                "volume": 1000.0,
                "signal": 0,
                "entry_price": float("nan"),
                "stop_loss": float("nan"),
                "take_profit": float("nan"),
            }
        )
        sl = 154.80
        tp = 155.40
        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = 155.0
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        df.at[3, "high"] = tp + 0.05

        result = _runner().run(df)
        if result.monthly_returns:
            pattern = re.compile(r"^\d{4}-\d{2}$")
            for key in result.monthly_returns:
                assert pattern.match(key), f"キー '{key}' が YYYY-MM 形式でない"
