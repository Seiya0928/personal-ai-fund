from typing import Optional

import pandas as pd


class DipBuyStrategy:
    """急落時にだけ買い、利確・損切り・タイムアウトで退出する。"""

    def __init__(
        self,
        dip_threshold_pct: float = 3.0,
        take_profit_pct: float = 5.0,
        stop_loss_pct: Optional[float] = None,
        max_holding_days: Optional[float] = None,
        max_position_ratio: float = 0.4,
        cooldown_days: float = 7.0,
        min_drop_from_recent_high_pct: float = 0.0,
        recent_high_lookback_days: int = 30,
        trend_filter: bool = False,
        volatility_filter: str = "none",
        volatility_lookback_days: int = 14,
        min_days_between_entries: float = 0.0,
    ):
        self.dip_threshold_pct = dip_threshold_pct
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_holding_days = max_holding_days
        self.max_position_ratio = max_position_ratio
        self.cooldown_days = cooldown_days
        self.min_drop_from_recent_high_pct = min_drop_from_recent_high_pct
        self.recent_high_lookback_days = recent_high_lookback_days
        self.trend_filter = trend_filter
        self.volatility_filter = volatility_filter
        self.volatility_lookback_days = volatility_lookback_days
        self.min_days_between_entries = min_days_between_entries

    def generate_signals(self, rows: list[dict]) -> pd.DataFrame:
        if len(rows) < 2:
            raise ValueError("データが不足しています（必要: 2件以上）")

        df = pd.DataFrame(rows)
        df["close"] = pd.to_numeric(df["close"])
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)

        df["pct_change"] = df["close"].pct_change() * 100
        df["recent_high"] = (
            df["close"].shift(1).rolling(self.recent_high_lookback_days, min_periods=1).max()
        )
        df["drop_from_recent_high_pct"] = (
            (df["close"] / df["recent_high"] - 1) * 100
        )
        df["sma_200"] = df["close"].rolling(200, min_periods=200).mean()
        df["daily_return"] = df["close"].pct_change()
        df["volatility"] = df["daily_return"].rolling(self.volatility_lookback_days, min_periods=self.volatility_lookback_days).std()
        vol_reference_window = max(self.volatility_lookback_days * 4, 20)
        df["volatility_median"] = df["volatility"].rolling(vol_reference_window, min_periods=self.volatility_lookback_days).median()
        df["volatility_q80"] = df["volatility"].rolling(vol_reference_window, min_periods=self.volatility_lookback_days).quantile(0.8)
        df["contribution_jpy"] = 0.0
        df["target_position"] = 0.0
        df["strategy_signal"] = "WAIT"
        df["exit_reason"] = pd.NA

        in_position = False
        entry_price = None
        entry_time = None
        cooldown_until = None
        last_entry_time = None

        for idx, row in df.iterrows():
            price = float(row["close"])
            timestamp = row["timestamp"]
            signal = "WAIT"
            target_position = self.max_position_ratio if in_position else 0.0
            exit_reason = pd.NA
            exited_this_bar = False

            if in_position and entry_price is not None and entry_time is not None:
                holding_days = (timestamp - entry_time).total_seconds() / 86400
                pnl_pct = (price / entry_price - 1) * 100

                if self.take_profit_pct is not None and pnl_pct >= self.take_profit_pct:
                    in_position = False
                    target_position = 0.0
                    signal = "TAKE_PROFIT"
                    exit_reason = "TAKE_PROFIT"
                    cooldown_until = timestamp + pd.Timedelta(days=self.cooldown_days)
                    entry_price = None
                    entry_time = None
                    exited_this_bar = True
                elif self.stop_loss_pct is not None and pnl_pct <= -abs(self.stop_loss_pct):
                    in_position = False
                    target_position = 0.0
                    signal = "STOP_LOSS"
                    exit_reason = "STOP_LOSS"
                    cooldown_until = timestamp + pd.Timedelta(days=self.cooldown_days)
                    entry_price = None
                    entry_time = None
                    exited_this_bar = True
                elif self.max_holding_days is not None and holding_days >= self.max_holding_days:
                    in_position = False
                    target_position = 0.0
                    signal = "TIMEOUT_EXIT"
                    exit_reason = "TIMEOUT_EXIT"
                    cooldown_until = timestamp + pd.Timedelta(days=self.cooldown_days)
                    entry_price = None
                    entry_time = None
                    exited_this_bar = True
                else:
                    signal = "HOLD_DIP"

            if not in_position:
                cooldown_active = cooldown_until is not None and timestamp < cooldown_until
                enough_gap_since_entry = (
                    last_entry_time is None
                    or (timestamp - last_entry_time).total_seconds() / 86400 >= self.min_days_between_entries
                )
                passes_recent_high_filter = True
                if self.min_drop_from_recent_high_pct > 0:
                    drop_value = row["drop_from_recent_high_pct"]
                    passes_recent_high_filter = pd.notna(drop_value) and float(drop_value) <= -self.min_drop_from_recent_high_pct

                passes_trend_filter = True
                if self.trend_filter:
                    sma_200 = row["sma_200"]
                    passes_trend_filter = pd.notna(sma_200) and price > float(sma_200)

                passes_volatility_filter = True
                if self.volatility_filter != "none":
                    current_vol = row["volatility"]
                    if pd.isna(current_vol):
                        passes_volatility_filter = False
                    elif self.volatility_filter == "high_only":
                        ref = row["volatility_median"]
                        passes_volatility_filter = pd.notna(ref) and float(current_vol) >= float(ref)
                    elif self.volatility_filter == "exclude_extreme_high":
                        ref = row["volatility_q80"]
                        passes_volatility_filter = pd.notna(ref) and float(current_vol) <= float(ref)

                if (
                    not exited_this_bar
                    and not cooldown_active
                    and enough_gap_since_entry
                    and passes_recent_high_filter
                    and passes_trend_filter
                    and passes_volatility_filter
                    and float(row["pct_change"] or 0.0) <= -self.dip_threshold_pct
                ):
                    in_position = True
                    entry_price = price
                    entry_time = timestamp
                    last_entry_time = timestamp
                    target_position = self.max_position_ratio
                    signal = "BUY_DIP"
                    exit_reason = pd.NA

            df.at[idx, "target_position"] = target_position
            df.at[idx, "strategy_signal"] = signal
            df.at[idx, "exit_reason"] = exit_reason

        return df
