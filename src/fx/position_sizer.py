"""
実注文なし・ポジションサイズ計算のみ
"""
from __future__ import annotations

from src.utils.logger import get_logger

log = get_logger(__name__)


class FXPositionSizer:
    """
    FXのポジションサイズを計算する。実注文は行わない。
    """

    def calc_lot_size(
        self,
        account_balance: float,
        risk_pct: float,
        stop_loss_pips: float,
        pip_value_jpy: float = 100.0,
    ) -> dict:
        """
        ロットサイズを計算する。

        Parameters
        ----------
        account_balance : float
            口座残高（円）
        risk_pct : float
            リスク割合 (0.01 = 1%)
        stop_loss_pips : float
            損切り幅（pips）
        pip_value_jpy : float
            1pip あたりの損益（円）。1万通貨・USD/JPY 想定で 100 円。

        Returns
        -------
        dict
            {"lots": float, "risk_jpy": float, "stop_pips": float}
        """
        risk_jpy = account_balance * risk_pct

        if stop_loss_pips <= 0:
            log.warning("stop_loss_pips=%s <= 0: ロットサイズを 0 とする", stop_loss_pips)
            return {
                "lots": 0.0,
                "risk_jpy": risk_jpy,
                "stop_pips": stop_loss_pips,
            }

        lots = risk_jpy / (stop_loss_pips * pip_value_jpy)

        log.debug(
            "calc_lot_size: balance=%.0f, risk_pct=%.4f, sl_pips=%.2f → lots=%.4f, risk_jpy=%.0f",
            account_balance,
            risk_pct,
            stop_loss_pips,
            lots,
            risk_jpy,
        )
        return {
            "lots": round(lots, 6),
            "risk_jpy": round(risk_jpy, 2),
            "stop_pips": stop_loss_pips,
        }
