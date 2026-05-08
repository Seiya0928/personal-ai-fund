"""
USD/JPY EMAトレンドフォロー戦略
実注文なし・研究用シグナル生成のみ
"""
from __future__ import annotations

import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


class MultiTimeframeEMAStrategy:
    """
    4時間足EMAトレンドと15分足ブレイクアウトを組み合わせたシグナル生成器。
    実注文なし・研究用のみ。
    """

    def __init__(
        self,
        ema_fast: int = 50,
        ema_slow: int = 200,
        breakout_lookback: int = 20,
        atr_period: int = 14,
        atr_sl_multiplier: float = 1.5,
        rr_ratio: float = 2.0,
        risk_pct: float = 0.01,
        spread_pips: float = 0.3,
        slippage_pips: float = 0.1,
        account_balance: float = 1_000_000.0,
        pip_value_jpy: float = 100.0,
    ) -> None:
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.breakout_lookback = breakout_lookback
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.rr_ratio = rr_ratio
        self.risk_pct = risk_pct
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.account_balance = account_balance
        self.pip_value_jpy = pip_value_jpy
        # USD/JPY: 1pip = 0.01
        self._pip = 0.01

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        df_h4: pd.DataFrame,
        df_m15: pd.DataFrame,
        account_balance: float | None = None,
    ) -> pd.DataFrame:
        """
        入力:
            df_h4: 4時間足 OHLCV (timestamp, open, high, low, close, volume)
            df_m15: 15分足 OHLCV
            account_balance: 口座残高（円）。None の場合は self.account_balance を使用。
        出力:
            df_m15 に以下カラムを追加した DataFrame:
            trend, ema_fast, ema_slow, recent_high, recent_low,
            signal (1=BUY, -1=SELL, 0=FLAT),
            stop_loss, take_profit, atr,
            entry_price (終値 + spread/slippage込み),
            lot_size (FXPositionSizer によるロットサイズ)
        """
        df_h4 = df_h4.copy()
        df_m15 = df_m15.copy()

        # --- Step 1: 4時間足 EMA 計算 ---
        df_h4["ema_fast"] = self._compute_ema(df_h4["close"], self.ema_fast)
        df_h4["ema_slow"] = self._compute_ema(df_h4["close"], self.ema_slow)
        df_h4["trend"] = "FLAT"
        df_h4.loc[df_h4["ema_fast"] > df_h4["ema_slow"], "trend"] = "UP"
        df_h4.loc[df_h4["ema_fast"] < df_h4["ema_slow"], "trend"] = "DOWN"

        # --- Step 2: H4 の値を M15 に前向き伝播 ---
        h4_cols = self._align_h4_to_m15(df_h4, df_m15)
        df_m15 = df_m15.join(h4_cols)

        # --- Step 3: 15分足 ブレイクアウトレベル ---
        df_m15["recent_high"] = df_m15["high"].rolling(self.breakout_lookback).max().shift(1)
        df_m15["recent_low"] = df_m15["low"].rolling(self.breakout_lookback).min().shift(1)

        # --- Step 4 & 5: シグナル生成 ---
        df_m15["signal"] = 0

        buy_cond = (
            (df_m15["close"] > df_m15["recent_high"])
            & (df_m15["trend"] == "UP")
        )
        sell_cond = (
            (df_m15["close"] < df_m15["recent_low"])
            & (df_m15["trend"] == "DOWN")
        )
        df_m15.loc[buy_cond, "signal"] = 1
        df_m15.loc[sell_cond, "signal"] = -1

        # --- Step 6: ATR 計算 ---
        df_m15["atr"] = self._compute_atr(df_m15, self.atr_period)

        # --- Step 7: SL / TP / entry_price ---
        cost_pips = (self.spread_pips + self.slippage_pips) * self._pip

        # BUY: entry は close + cost
        # SELL: entry は close - cost
        df_m15["entry_price"] = df_m15["close"].copy().astype(float)
        df_m15.loc[df_m15["signal"] == 1, "entry_price"] = (
            df_m15.loc[df_m15["signal"] == 1, "close"] + cost_pips
        )
        df_m15.loc[df_m15["signal"] == -1, "entry_price"] = (
            df_m15.loc[df_m15["signal"] == -1, "close"] - cost_pips
        )

        sl_dist = df_m15["atr"] * self.atr_sl_multiplier
        tp_dist = sl_dist * self.rr_ratio

        # BUY
        df_m15.loc[df_m15["signal"] == 1, "stop_loss"] = (
            df_m15.loc[df_m15["signal"] == 1, "entry_price"] - sl_dist[df_m15["signal"] == 1]
        )
        df_m15.loc[df_m15["signal"] == 1, "take_profit"] = (
            df_m15.loc[df_m15["signal"] == 1, "entry_price"] + tp_dist[df_m15["signal"] == 1]
        )
        # SELL
        df_m15.loc[df_m15["signal"] == -1, "stop_loss"] = (
            df_m15.loc[df_m15["signal"] == -1, "entry_price"] + sl_dist[df_m15["signal"] == -1]
        )
        df_m15.loc[df_m15["signal"] == -1, "take_profit"] = (
            df_m15.loc[df_m15["signal"] == -1, "entry_price"] - tp_dist[df_m15["signal"] == -1]
        )

        # FLAT: fill NaN
        for col in ("stop_loss", "take_profit"):
            if col not in df_m15.columns:
                df_m15[col] = float("nan")

        # --- Step 8: lot_size 計算 ---
        df_m15["lot_size"] = 1.0  # デフォルト: 1ロット固定
        try:
            from src.fx.position_sizer import FXPositionSizer
            sizer = FXPositionSizer()
            bal = account_balance if account_balance is not None else self.account_balance

            signal_mask = df_m15["signal"].isin([1, -1])
            for idx in df_m15.index[signal_mask]:
                row = df_m15.loc[idx]
                if pd.notna(row.get("entry_price")) and pd.notna(row.get("stop_loss")):
                    # stop_loss_pips = |entry_price - stop_loss| / pip
                    sl_pips = abs(float(row["entry_price"]) - float(row["stop_loss"])) / self._pip
                    if sl_pips > 0:
                        sizing = sizer.calc_lot_size(
                            account_balance=bal,
                            risk_pct=self.risk_pct,
                            stop_loss_pips=sl_pips,
                            pip_value_jpy=self.pip_value_jpy,
                        )
                        df_m15.at[idx, "lot_size"] = sizing["lots"]
        except Exception as exc:
            log.warning("lot_size 計算に失敗しました（デフォルト 1.0 を使用）: %s", exc)

        log.debug(
            "generate_signals: total=%d, BUY=%d, SELL=%d",
            len(df_m15),
            (df_m15["signal"] == 1).sum(),
            (df_m15["signal"] == -1).sum(),
        )
        return df_m15

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _compute_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    def _align_h4_to_m15(
        self,
        df_h4: pd.DataFrame,
        df_m15: pd.DataFrame,
    ) -> pd.DataFrame:
        """H4 の ema_fast, ema_slow, trend を M15 インデックスに前向き伝播（ffill）する。"""
        h4 = df_h4[["timestamp", "ema_fast", "ema_slow", "trend"]].copy()
        h4 = h4.set_index("timestamp").sort_index()

        m15_ts = pd.Series(df_m15["timestamp"].values, index=df_m15.index)

        # M15 の各タイムスタンプに対して H4 の直近値を取得
        combined = h4.reindex(
            h4.index.union(pd.DatetimeIndex(m15_ts.values))
        ).ffill()

        result = pd.DataFrame(index=df_m15.index)
        result["ema_fast"] = m15_ts.map(lambda t: combined.at[t, "ema_fast"] if t in combined.index else float("nan"))
        result["ema_slow"] = m15_ts.map(lambda t: combined.at[t, "ema_slow"] if t in combined.index else float("nan"))
        result["trend"] = m15_ts.map(lambda t: combined.at[t, "trend"] if t in combined.index else "FLAT")

        return result
