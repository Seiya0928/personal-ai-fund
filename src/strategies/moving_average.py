import pandas as pd


class MovingAverageCross:
    """
    シンプルな移動平均クロス戦略。
    短期MAが長期MAを上抜けたら BUY、下抜けたら SELL。
    """

    def __init__(self, short: int = 5, long: int = 20):
        self.short = short
        self.long = long

    def generate_signals(self, rows: list[dict]) -> pd.DataFrame:
        if len(rows) < self.long + 1:
            raise ValueError(f"データが不足しています（必要: {self.long + 1}件以上）")

        df = pd.DataFrame(rows)
        df["close"] = pd.to_numeric(df["close"])
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)

        df["ma_short"] = df["close"].rolling(self.short).mean()
        df["ma_long"] = df["close"].rolling(self.long).mean()

        df["signal"] = 0
        df.loc[df["ma_short"] > df["ma_long"], "signal"] = 1   # BUY
        df.loc[df["ma_short"] < df["ma_long"], "signal"] = -1  # SELL

        df["position"] = df["signal"].diff().fillna(0)
        df["target_position"] = 0.0
        df.loc[df["signal"] > 0, "target_position"] = 1.0
        df["contribution_jpy"] = 0.0
        df["strategy_signal"] = df["signal"].map({1: "LONG", -1: "FLAT", 0: "WAIT"}).fillna("WAIT")
        return df
