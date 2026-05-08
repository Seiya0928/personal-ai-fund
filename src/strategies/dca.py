import pandas as pd


class DollarCostAveragingStrategy:
    """一定間隔で定額購入する。売却は行わず、最終バーで評価する。"""

    def __init__(self, amount_jpy: float = 5_000.0, every_n_bars: int = 24):
        self.amount_jpy = amount_jpy
        self.every_n_bars = every_n_bars

    def generate_signals(self, rows: list[dict]) -> pd.DataFrame:
        if len(rows) < 2:
            raise ValueError("データが不足しています（必要: 2件以上）")

        df = pd.DataFrame(rows)
        df["close"] = pd.to_numeric(df["close"])
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)

        df["contribution_jpy"] = 0.0
        df.loc[df.index % self.every_n_bars == 0, "contribution_jpy"] = self.amount_jpy
        df["target_position"] = pd.NA
        df["strategy_signal"] = "BUY_DCA"
        return df
