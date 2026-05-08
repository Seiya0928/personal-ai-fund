"""
FXPositionSizer のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import pytest

from src.fx.position_sizer import FXPositionSizer


class TestFXPositionSizer:
    def setup_method(self):
        self.sizer = FXPositionSizer()

    def test_basic_lot_calc(self):
        """
        balance=1,000,000, risk=1%, sl=20pips, pip_value=100
        → risk_jpy = 10,000
        → lots = 10,000 / (20 * 100) = 5.0

        ※ pip_value_jpy=100 は「1万通貨で1pip=100円」の想定。
          sl=20pips で1ロットあたりリスク = 20 * 100 = 2,000円。
          許容リスク 10,000円 / 2,000円 = 5.0ロット。
        """
        result = self.sizer.calc_lot_size(
            account_balance=1_000_000,
            risk_pct=0.01,
            stop_loss_pips=20.0,
            pip_value_jpy=100.0,
        )
        assert abs(result["lots"] - 5.0) < 1e-6, f"lots={result['lots']}, expected=5.0"

    def test_zero_sl_returns_zero(self):
        """stop_loss_pips=0 のとき lots=0 かつ例外を発生させない。"""
        result = self.sizer.calc_lot_size(
            account_balance=1_000_000,
            risk_pct=0.01,
            stop_loss_pips=0.0,
        )
        assert result["lots"] == 0.0, f"lots={result['lots']}, expected=0.0"

    def test_risk_jpy_is_correct(self):
        """risk_jpy = account_balance * risk_pct。"""
        balance = 2_000_000
        risk_pct = 0.02
        result = self.sizer.calc_lot_size(
            account_balance=balance,
            risk_pct=risk_pct,
            stop_loss_pips=10.0,
        )
        expected_risk = balance * risk_pct
        assert abs(result["risk_jpy"] - expected_risk) < 0.01, (
            f"risk_jpy={result['risk_jpy']}, expected={expected_risk}"
        )

    def test_negative_sl_returns_zero(self):
        """stop_loss_pips < 0 のとき lots=0 かつ例外なし。"""
        result = self.sizer.calc_lot_size(
            account_balance=1_000_000,
            risk_pct=0.01,
            stop_loss_pips=-5.0,
        )
        assert result["lots"] == 0.0

    def test_stop_pips_in_result(self):
        """戻り値に stop_pips が含まれる。"""
        result = self.sizer.calc_lot_size(
            account_balance=500_000,
            risk_pct=0.005,
            stop_loss_pips=15.0,
        )
        assert "stop_pips" in result
        assert result["stop_pips"] == 15.0

    def test_small_balance(self):
        """残高が小さくてもエラーなし。"""
        result = self.sizer.calc_lot_size(
            account_balance=100.0,
            risk_pct=0.01,
            stop_loss_pips=10.0,
        )
        assert result["lots"] >= 0
        assert result["risk_jpy"] == pytest.approx(1.0)
