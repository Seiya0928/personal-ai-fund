"""
USD/JPY FXバックテストエンジン
実注文なし・検証専用
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class FXBacktestResult:
    symbol: str
    initial_balance: float
    final_balance: float
    total_return_pct: float
    expectancy: float          # 平均PnL（円）
    win_rate: float            # 0.0 〜 1.0
    profit_factor: float
    max_drawdown_pct: float
    max_losing_streak: int
    trade_count: int
    monthly_returns: dict      # "YYYY-MM" -> float (%)
    trades: list[dict] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)
    buy_count: int = 0
    sell_count: int = 0
    avg_mfe_pips: float = 0.0
    avg_mae_pips: float = 0.0
    avg_mfe_win_pips: float = 0.0   # 勝ちトレードの平均MFE
    avg_mfe_lose_pips: float = 0.0  # 負けトレードの平均MFE
    avg_mae_win_pips: float = 0.0   # 勝ちトレードの平均MAE
    avg_mae_lose_pips: float = 0.0  # 負けトレードの平均MAE
    failed_after_half_tp_count: int = 0  # 一度TP50%以上まで順行したのに損切りになったトレード数


class FXBacktestRunner:
    """
    USD/JPY FX バックテストエンジン。実注文なし・検証専用。

    シグナルカラム（signal, entry_price, stop_loss, take_profit）を含む
    DataFrame を受け取り、FXBacktestResult を返す。
    """

    def __init__(
        self,
        initial_balance: float = 1_000_000,
        spread_pips: float = 0.3,
        slippage_pips: float = 0.1,
        commission_pips: float = 0.0,
        pip_value_jpy: float = 100.0,
    ) -> None:
        self.initial_balance = initial_balance
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_pips = commission_pips
        self.pip_value_jpy = pip_value_jpy
        # 片道コスト（pips）
        self._cost_pips = (spread_pips + slippage_pips + commission_pips) / 2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, df: pd.DataFrame, symbol: str = "USD/JPY") -> FXBacktestResult:
        """
        バックテストを実行する。

        Parameters
        ----------
        df : pd.DataFrame
            signal, entry_price, stop_loss, take_profit, high, low, close,
            timestamp カラムを含む DataFrame
        symbol : str
            銘柄識別子（ログ・結果用）

        Returns
        -------
        FXBacktestResult
        """
        df = df.copy().reset_index(drop=True)
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        balance = self.initial_balance
        equity_curve: list[float] = []
        trades: list[dict] = []
        position: Optional[dict] = None  # 現在保有中のポジション

        for i, row in df.iterrows():
            # ポジション保有中: MFE/MAE 更新 & SL/TP チェック
            if position is not None:
                # MFE/MAE 更新（当該足のhigh/lowで計算）
                if position["side"] == "LONG":
                    favorable = float(row["high"]) - position["entry_price"]
                    adverse   = position["entry_price"] - float(row["low"])
                else:  # SHORT
                    favorable = position["entry_price"] - float(row["low"])
                    adverse   = float(row["high"]) - position["entry_price"]
                position["mfe"] = max(position.get("mfe", 0.0), favorable)
                position["mae"] = max(position.get("mae", 0.0), adverse)
                tp_dist = abs(position["take_profit"] - position["entry_price"])
                position["max_favorable_pct"] = position["mfe"] / tp_dist if tp_dist > 0 else 0.0

                pnl, exit_price, exit_reason = self._check_exit(row, position)
                if exit_reason is not None:
                    balance += pnl
                    trade_rec = {
                        "entry_time": position["entry_time"],
                        "exit_time": row["timestamp"],
                        "side": position["side"],
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "stop_loss": position["stop_loss"],
                        "take_profit": position["take_profit"],
                        "pnl_jpy": round(pnl, 2),
                        "exit_reason": exit_reason,
                        "mfe_pips": round(position.get("mfe", 0.0) / 0.01, 2),
                        "mae_pips": round(position.get("mae", 0.0) / 0.01, 2),
                        "max_favorable_pct": round(position.get("max_favorable_pct", 0.0), 4),
                    }
                    trades.append(trade_rec)
                    position = None

            # 新規シグナルの処理（ポジションなし時のみ）
            if position is None:
                sig = int(row.get("signal", 0))
                if sig != 0 and pd.notna(row.get("stop_loss")) and pd.notna(row.get("take_profit")):
                    # lot_size カラムがあればそれを使う（なければ 1.0 固定）
                    lot_size = float(row["lot_size"]) if "lot_size" in row.index and pd.notna(row.get("lot_size")) else 1.0
                    position = {
                        "side": "LONG" if sig == 1 else "SHORT",
                        "signal": sig,
                        "entry_price": float(row["entry_price"]),
                        "stop_loss": float(row["stop_loss"]),
                        "take_profit": float(row["take_profit"]),
                        "entry_time": row["timestamp"],
                        "lot_size": lot_size,
                    }

            equity_curve.append(balance)

        # 未決済ポジションは最終行の close で強制クローズ
        if position is not None and len(df) > 0:
            last = df.iloc[-1]
            close_price = float(last["close"])
            pnl = self._calc_pnl(position, close_price)
            balance += pnl
            tp_dist = abs(position["take_profit"] - position["entry_price"])
            trades.append(
                {
                    "entry_time": position["entry_time"],
                    "exit_time": last["timestamp"],
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": close_price,
                    "stop_loss": position["stop_loss"],
                    "take_profit": position["take_profit"],
                    "pnl_jpy": round(pnl, 2),
                    "exit_reason": "FORCE_EXIT",
                    "mfe_pips": round(position.get("mfe", 0.0) / 0.01, 2),
                    "mae_pips": round(position.get("mae", 0.0) / 0.01, 2),
                    "max_favorable_pct": round(position.get("max_favorable_pct", 0.0), 4),
                }
            )
            equity_curve[-1] = balance

        # --- 指標計算 ---
        total_return_pct = (balance - self.initial_balance) / self.initial_balance * 100

        win_trades = [t for t in trades if t["pnl_jpy"] > 0]
        lose_trades = [t for t in trades if t["pnl_jpy"] <= 0]
        win_rate = len(win_trades) / len(trades) if trades else 0.0
        expectancy = sum(t["pnl_jpy"] for t in trades) / len(trades) if trades else 0.0

        gross_profit = sum(t["pnl_jpy"] for t in win_trades)
        gross_loss = abs(sum(t["pnl_jpy"] for t in lose_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        max_dd_pct = self._calc_max_drawdown(equity_curve)
        max_losing_streak = self._calc_max_losing_streak(trades)
        monthly_returns = self._calc_monthly_returns(trades, df)

        # --- MFE/MAE 集計 ---
        buy_count = sum(1 for t in trades if t["side"] == "LONG")
        sell_count = sum(1 for t in trades if t["side"] == "SHORT")

        all_mfe = [t.get("mfe_pips", 0.0) for t in trades]
        all_mae = [t.get("mae_pips", 0.0) for t in trades]
        avg_mfe_pips = sum(all_mfe) / len(all_mfe) if all_mfe else 0.0
        avg_mae_pips = sum(all_mae) / len(all_mae) if all_mae else 0.0

        win_mfe = [t.get("mfe_pips", 0.0) for t in win_trades]
        win_mae = [t.get("mae_pips", 0.0) for t in win_trades]
        lose_mfe = [t.get("mfe_pips", 0.0) for t in lose_trades]
        lose_mae = [t.get("mae_pips", 0.0) for t in lose_trades]
        avg_mfe_win_pips = sum(win_mfe) / len(win_mfe) if win_mfe else 0.0
        avg_mae_win_pips = sum(win_mae) / len(win_mae) if win_mae else 0.0
        avg_mfe_lose_pips = sum(lose_mfe) / len(lose_mfe) if lose_mfe else 0.0
        avg_mae_lose_pips = sum(lose_mae) / len(lose_mae) if lose_mae else 0.0

        # 負けトレードのうち max_favorable_pct >= 0.5 の件数
        failed_after_half_tp_count = sum(
            1 for t in lose_trades if t.get("max_favorable_pct", 0.0) >= 0.5
        )

        log.info(
            "FXBacktest[%s]: trades=%d, win_rate=%.1f%%, return=%.2f%%, mdd=%.2f%%",
            symbol,
            len(trades),
            win_rate * 100,
            total_return_pct,
            max_dd_pct,
        )

        return FXBacktestResult(
            symbol=symbol,
            initial_balance=self.initial_balance,
            final_balance=round(balance, 2),
            total_return_pct=round(total_return_pct, 4),
            expectancy=round(expectancy, 2),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            max_drawdown_pct=round(max_dd_pct, 4),
            max_losing_streak=max_losing_streak,
            trade_count=len(trades),
            monthly_returns=monthly_returns,
            trades=trades,
            assumptions={
                "spread_pips": self.spread_pips,
                "slippage_pips": self.slippage_pips,
                "commission_pips": self.commission_pips,
                "pip_value_jpy": self.pip_value_jpy,
                "initial_balance": self.initial_balance,
            },
            buy_count=buy_count,
            sell_count=sell_count,
            avg_mfe_pips=round(avg_mfe_pips, 2),
            avg_mae_pips=round(avg_mae_pips, 2),
            avg_mfe_win_pips=round(avg_mfe_win_pips, 2),
            avg_mfe_lose_pips=round(avg_mfe_lose_pips, 2),
            avg_mae_win_pips=round(avg_mae_win_pips, 2),
            avg_mae_lose_pips=round(avg_mae_lose_pips, 2),
            failed_after_half_tp_count=failed_after_half_tp_count,
        )

    @staticmethod
    def split(
        df: pd.DataFrame,
        train: float = 0.6,
        val: float = 0.2,
        test: float = 0.2,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        時系列順（シャッフルなし）で train / val / test に分割する。

        Parameters
        ----------
        df : pd.DataFrame
        train, val, test : float
            各比率の合計が 1.0 になること。

        Returns
        -------
        tuple[DataFrame, DataFrame, DataFrame]
        """
        n = len(df)
        n_train = int(n * train)
        n_val = int(n * val)
        df_train = df.iloc[:n_train].reset_index(drop=True)
        df_val = df.iloc[n_train: n_train + n_val].reset_index(drop=True)
        df_test = df.iloc[n_train + n_val:].reset_index(drop=True)
        return df_train, df_val, df_test

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_exit(
        self,
        row: pd.Series,
        position: dict,
    ) -> tuple[float, float, Optional[str]]:
        """
        当該ローソク足で SL / TP に到達したか確認する。

        Returns
        -------
        (pnl, exit_price, exit_reason)  exit_reason が None なら未決済
        """
        high = float(row["high"])
        low = float(row["low"])
        sl = position["stop_loss"]
        tp = position["take_profit"]
        sig = position["signal"]

        if sig == 1:  # LONG
            if low <= sl:
                return self._calc_pnl(position, sl), sl, "SL"
            if high >= tp:
                return self._calc_pnl(position, tp), tp, "TP"
        else:  # SHORT
            if high >= sl:
                return self._calc_pnl(position, sl), sl, "SL"
            if low <= tp:
                return self._calc_pnl(position, tp), tp, "TP"

        return 0.0, 0.0, None

    def _calc_pnl(self, position: dict, exit_price: float) -> float:
        """
        PnL を円換算で計算する。
        lot_size カラムがあればそれを使う（なければ 1.0 固定）。
        spread + slippage を exit 側にも適用。
        """
        entry = position["entry_price"]
        pip = 0.01  # USD/JPY 1pip
        cost_pips = self._cost_pips  # 片道コスト
        cost = cost_pips * pip
        lot_size = position.get("lot_size", 1.0)

        if position["signal"] == 1:  # LONG
            effective_exit = exit_price - cost
            diff_pips = (effective_exit - entry) / pip
        else:  # SHORT
            effective_exit = exit_price + cost
            diff_pips = (entry - effective_exit) / pip

        pnl = diff_pips * self.pip_value_jpy * lot_size
        return pnl

    @staticmethod
    def _calc_max_drawdown(equity_curve: list[float]) -> float:
        if not equity_curve:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for v in equity_curve:
            peak = max(peak, v)
            dd = (peak - v) / peak * 100 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _calc_max_losing_streak(trades: list[dict]) -> int:
        streak = 0
        max_streak = 0
        for t in trades:
            if t["pnl_jpy"] <= 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        return max_streak

    @staticmethod
    def _calc_monthly_returns(
        trades: list[dict],
        df: pd.DataFrame,
    ) -> dict:
        """月別リターン（%）を計算する。"""
        if not trades:
            return {}

        # 月別 PnL を集計
        monthly_pnl: dict[str, float] = {}
        for t in trades:
            key = pd.Timestamp(t["exit_time"]).strftime("%Y-%m")
            monthly_pnl[key] = monthly_pnl.get(key, 0.0) + t["pnl_jpy"]

        # 月別リターン (%)
        # 簡略化: 各月の開始時点の残高を推算するために累積で計算
        if "initial_balance" in df.columns:
            balance_start = float(df["initial_balance"].iloc[0])
        else:
            # 近似: 全 PnL を時系列順に累積して月初残高を推算
            all_months = sorted(monthly_pnl.keys())
            running = 1_000_000.0  # デフォルト初期残高（FXBacktestRunner のデフォルト）
            result: dict[str, float] = {}
            for m in all_months:
                pnl = monthly_pnl[m]
                ret_pct = pnl / running * 100 if running != 0 else 0.0
                result[m] = round(ret_pct, 4)
                running += pnl
            return result

        all_months = sorted(monthly_pnl.keys())
        running = balance_start
        result = {}
        for m in all_months:
            pnl = monthly_pnl[m]
            ret_pct = pnl / running * 100 if running != 0 else 0.0
            result[m] = round(ret_pct, 4)
            running += pnl
        return result
