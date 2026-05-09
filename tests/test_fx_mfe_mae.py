"""
FXBacktestRunner の MFE/MAE 機能テスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.fx.fx_backtest import FXBacktestRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FREQ = "15min"


def _base_df(n: int = 50, price: float = 155.0) -> pd.DataFrame:
    """シグナル列を含むベース DataFrame を返す。"""
    ts = pd.date_range("2024-01-01", periods=n, freq=_FREQ, tz="UTC")
    return pd.DataFrame({
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
    })


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

class TestLongMFE:
    def test_long_mfe_recorded(self):
        """LONGポジションで high が entry より高い足でMFEが更新される。"""
        price = 155.0
        df = _base_df(30, price)
        sl = price - 0.20
        tp = price + 0.40

        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp

        # row 3: high = entry + 0.20 (20pips 上昇)
        df.at[3, "high"] = price + 0.20
        df.at[3, "low"] = price - 0.02

        # row 5: TP到達
        df.at[5, "high"] = tp + 0.05

        result = _runner().run(df)
        assert result.trade_count >= 1

        tp_trades = [t for t in result.trades if t["exit_reason"] == "TP"]
        assert len(tp_trades) >= 1

        t = tp_trades[0]
        assert "mfe_pips" in t, "mfe_pips がトレードレコードにない"
        # high=155.20, entry=155.0 → favorable=0.20 → 20 pips
        assert t["mfe_pips"] >= 20.0, f"MFE が期待より小さい: {t['mfe_pips']}"


class TestLongMAE:
    def test_long_mae_recorded(self):
        """LONGポジションで low が entry より低い足でMAEが更新される。"""
        price = 155.0
        df = _base_df(30, price)
        sl = price - 0.50  # 50pips SL
        tp = price + 1.00  # 100pips TP

        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp

        # row 3: low = entry - 0.10 (10pips 逆行)
        df.at[3, "low"] = price - 0.10
        df.at[3, "high"] = price + 0.02

        # row 10: TP到達
        df.at[10, "high"] = tp + 0.05

        result = _runner().run(df)
        assert result.trade_count >= 1

        tp_trades = [t for t in result.trades if t["exit_reason"] == "TP"]
        assert len(tp_trades) >= 1

        t = tp_trades[0]
        assert "mae_pips" in t, "mae_pips がトレードレコードにない"
        # entry=155.0, low=154.90 → adverse=0.10 → 10 pips
        assert t["mae_pips"] >= 10.0, f"MAE が期待より小さい: {t['mae_pips']}"


class TestShortMFE:
    def test_short_mfe_recorded(self):
        """SHORTポジションで low が entry より低い足でMFEが更新される。"""
        price = 155.0
        df = _base_df(30, price)
        sl = price + 0.20
        tp = price - 0.40

        df.at[0, "signal"] = -1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp

        # row 3: low = entry - 0.15 (15pips 順行)
        df.at[3, "low"] = price - 0.15
        df.at[3, "high"] = price + 0.02

        # row 5: TP到達
        df.at[5, "low"] = tp - 0.05

        result = _runner().run(df)
        assert result.trade_count >= 1

        tp_trades = [t for t in result.trades if t["exit_reason"] == "TP"]
        assert len(tp_trades) >= 1

        t = tp_trades[0]
        assert "mfe_pips" in t, "mfe_pips がトレードレコードにない"
        # SHORT: favorable = entry(155.0) - low(154.85) = 0.15 → 15 pips
        assert t["mfe_pips"] >= 15.0, f"SHORT MFE が期待より小さい: {t['mfe_pips']}"


class TestFailedAfterHalfTP:
    def test_failed_after_half_tp_counted(self):
        """TP50%到達後に損切りになったトレードが failed_after_half_tp_count にカウントされる。"""
        price = 155.0
        df = _base_df(50, price)
        sl = price - 0.20  # 20pips SL
        tp = price + 0.40  # 40pips TP (RR=2)

        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp

        # row 3: TPの60%まで到達（favorable = 0.24 > 0.5 * 0.40 = 0.20）
        df.at[3, "high"] = price + 0.24  # 24pips 順行 → max_favorable_pct = 0.24/0.40 = 0.60
        df.at[3, "low"] = price - 0.02

        # row 10: SL到達（損切り）
        df.at[10, "low"] = sl - 0.05

        result = _runner().run(df)
        assert result.trade_count >= 1

        sl_trades = [t for t in result.trades if t["exit_reason"] == "SL"]
        assert len(sl_trades) >= 1, "SLトレードがない"

        t = sl_trades[0]
        assert "max_favorable_pct" in t, "max_favorable_pct がトレードレコードにない"
        assert t["max_favorable_pct"] >= 0.5, (
            f"max_favorable_pct が 0.5 未満: {t['max_favorable_pct']}"
        )

        # FXBacktestResultのfailed_after_half_tp_countもカウントされる
        assert result.failed_after_half_tp_count >= 1, (
            f"failed_after_half_tp_count が 0: {result.failed_after_half_tp_count}"
        )


class TestMFEMAEInTradeRecord:
    def test_mfe_mae_in_trade_record(self):
        """クローズ後のトレードレコードに mfe_pips, mae_pips, max_favorable_pct が含まれる。"""
        price = 155.0
        df = _base_df(30, price)
        sl = price - 0.20
        tp = price + 0.40

        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        df.at[5, "high"] = tp + 0.05  # TP到達

        result = _runner().run(df)
        assert result.trade_count >= 1

        for t in result.trades:
            assert "mfe_pips" in t, f"mfe_pips がない: {list(t.keys())}"
            assert "mae_pips" in t, f"mae_pips がない: {list(t.keys())}"
            assert "max_favorable_pct" in t, f"max_favorable_pct がない: {list(t.keys())}"
            assert isinstance(t["mfe_pips"], float), f"mfe_pips の型が不正: {type(t['mfe_pips'])}"
            assert isinstance(t["mae_pips"], float), f"mae_pips の型が不正: {type(t['mae_pips'])}"
            assert isinstance(t["max_favorable_pct"], float), f"max_favorable_pct の型が不正"
            assert t["mfe_pips"] >= 0.0, f"mfe_pips が負: {t['mfe_pips']}"
            assert t["mae_pips"] >= 0.0, f"mae_pips が負: {t['mae_pips']}"
            assert t["max_favorable_pct"] >= 0.0, f"max_favorable_pct が負: {t['max_favorable_pct']}"

    def test_mfe_mae_in_result_aggregates(self):
        """FXBacktestResultのMFE/MAE集計フィールドが正しく計算される。"""
        price = 155.0
        n = 100
        ts = pd.date_range("2024-01-01", periods=n, freq=_FREQ, tz="UTC")
        df = pd.DataFrame({
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
        })

        sl = price - 0.20
        tp = price + 0.40

        # トレード1: TP到達（勝ち）
        df.at[0, "signal"] = 1
        df.at[0, "entry_price"] = price
        df.at[0, "stop_loss"] = sl
        df.at[0, "take_profit"] = tp
        df.at[5, "high"] = tp + 0.05

        # トレード2: SL到達（負け）
        df.at[20, "signal"] = 1
        df.at[20, "entry_price"] = price
        df.at[20, "stop_loss"] = sl
        df.at[20, "take_profit"] = tp
        df.at[25, "low"] = sl - 0.05

        result = _runner().run(df)
        assert result.trade_count >= 2

        # 集計フィールドの存在確認
        assert hasattr(result, "avg_mfe_pips")
        assert hasattr(result, "avg_mae_pips")
        assert hasattr(result, "avg_mfe_win_pips")
        assert hasattr(result, "avg_mfe_lose_pips")
        assert hasattr(result, "avg_mae_win_pips")
        assert hasattr(result, "avg_mae_lose_pips")
        assert hasattr(result, "failed_after_half_tp_count")
        assert hasattr(result, "buy_count")
        assert hasattr(result, "sell_count")

        assert result.avg_mfe_pips >= 0.0
        assert result.avg_mae_pips >= 0.0
        assert result.buy_count >= 0
        assert result.sell_count >= 0
        assert result.buy_count + result.sell_count == result.trade_count
