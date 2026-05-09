"""
USD/JPY H1足 長期バックテストランナー
実注文なし・研究用のみ
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from src.fx.fx_backtest import FXBacktestResult, FXBacktestRunner
from src.fx.market_regime import MarketRegime, RegimeClassifier
from src.fx.strategy import MultiTimeframeEMAStrategy
from src.utils.logger import get_logger

log = get_logger(__name__)


class H1BacktestRunner:
    """
    H1足データで EMA トレンドフォロー戦略を検証する。
    上位足は D1 を使う。
    実注文なし。
    """

    def __init__(
        self,
        initial_balance: float = 1_000_000,
        spread_pips: float = 0.3,
        slippage_pips: float = 0.1,
        pip_value_jpy: float = 100.0,
    ) -> None:
        self.initial_balance = initial_balance
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.pip_value_jpy = pip_value_jpy

    def run_full_validation(
        self,
        df_h1: pd.DataFrame,
        df_d1: pd.DataFrame,
        ema_fast: int = 50,
        ema_slow: int = 200,
        breakout_lookback: int = 20,
        atr_sl_multiplier: float = 1.5,
        rr_ratio: float = 2.0,
        risk_pct: float = 0.01,
        direction: str = "both",
        d1_source: str = "resample",
        regime_filter: Optional[list[str]] = None,
    ) -> dict:
        """
        1. MultiTimeframeEMAStrategy で H1/D1 を使ってシグナル生成
           - df_trend = df_d1 または H1 からリサンプル（d1_source で選択）
           - df_entry = df_h1（H1でエントリー）
        2. train(60%)/val(20%)/test(20%) に分割
        3. 各セットで FXBacktestRunner.run() を実行
        4. RegimeClassifier で相場環境を分類
        5. 相場環境別の集計を実施
        6. 結果を dict で返す

        Parameters
        ----------
        d1_source : str
            "resample": H1データからD1をresampleして使用（デフォルト）
            "direct":   渡されたdf_d1をそのまま使用
        regime_filter : list[str] or None
            None: 全環境（フィルターなし）
            ["uptrend"]: 上昇トレンド期のシグナルのみ残す
            ["downtrend"]: 下降トレンド期のシグナルのみ残す
            ["range"]: レンジ期のシグナルのみ残す
            ["downtrend", "range"]: 上昇以外のシグナルを残す など

        戻り値の構造:
        {
            "params": {...},
            "data_info": {"h1_rows": N, "d1_rows": N, "period": "..."},
            "train": FXBacktestResult,
            "val": FXBacktestResult,
            "test": FXBacktestResult,
            "regime_summary": {
                "uptrend":   {"trade_count": N, "win_rate": X, "profit_factor": X},
                "downtrend": {...},
                "range":     {...},
            }
        }
        """
        params = {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "breakout_lookback": breakout_lookback,
            "atr_sl_multiplier": atr_sl_multiplier,
            "rr_ratio": rr_ratio,
            "risk_pct": risk_pct,
            "direction": direction,
        }

        # --- データ情報 ---
        df_h1 = df_h1.copy()
        df_h1["timestamp"] = pd.to_datetime(df_h1["timestamp"], utc=True)
        df_h1 = df_h1.sort_values("timestamp").reset_index(drop=True)

        # d1_source に従って D1 データを決定
        if d1_source == "resample":
            from src.fx.data_loader import FXDataLoader
            loader = FXDataLoader()
            df_d1_used = loader.resample(df_h1, to="1D")
            # resample 後のタイムスタンプを UTC に統一
            df_d1_used["timestamp"] = pd.to_datetime(df_d1_used["timestamp"], utc=True)
            log.info("H1BacktestRunner: d1_source=resample, d1_rows=%d", len(df_d1_used))
        else:
            df_d1_used = df_d1.copy()
            df_d1_used["timestamp"] = pd.to_datetime(df_d1_used["timestamp"], utc=True)
            df_d1_used = df_d1_used.sort_values("timestamp").reset_index(drop=True)
            log.info("H1BacktestRunner: d1_source=direct, d1_rows=%d", len(df_d1_used))

        h1_start = df_h1["timestamp"].min()
        h1_end = df_h1["timestamp"].max()
        data_info = {
            "h1_rows": len(df_h1),
            "d1_rows": len(df_d1_used),
            "period": f"{h1_start.date()} 〜 {h1_end.date()}",
        }
        log.info("H1BacktestRunner.run_full_validation: h1=%d, d1=%d", len(df_h1), len(df_d1_used))

        # --- ストラテジー生成 ---
        strategy = MultiTimeframeEMAStrategy(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            breakout_lookback=breakout_lookback,
            atr_sl_multiplier=atr_sl_multiplier,
            rr_ratio=rr_ratio,
            risk_pct=risk_pct,
            spread_pips=self.spread_pips,
            slippage_pips=self.slippage_pips,
            pip_value_jpy=self.pip_value_jpy,
            entry_timeframe="H1",
            trend_timeframe="D1",
        )

        # --- H1 を train/val/test に分割 ---
        df_h1_train, df_h1_val, df_h1_test = self._split(df_h1)

        # --- バックテストランナー ---
        runner = FXBacktestRunner(
            initial_balance=self.initial_balance,
            spread_pips=self.spread_pips,
            slippage_pips=self.slippage_pips,
            pip_value_jpy=self.pip_value_jpy,
        )

        # --- RegimeClassifier で相場環境を事前分類（regime_filter 適用のため先に行う） ---
        classifier = RegimeClassifier(ema_fast=ema_fast, ema_slow=ema_slow)
        df_d1_classified = classifier.classify(df_d1_used)
        df_h1_with_regime = classifier.align_to_entry(df_d1_classified, df_h1)

        # H1 train/val/test に対応する regime 付き分割データを用意
        n_h1 = len(df_h1)
        n_train_h1 = int(n_h1 * 0.6)
        n_val_h1 = int(n_h1 * 0.2)
        df_h1_train_regime = df_h1_with_regime.iloc[:n_train_h1].reset_index(drop=True)
        df_h1_val_regime = df_h1_with_regime.iloc[n_train_h1: n_train_h1 + n_val_h1].reset_index(drop=True)
        df_h1_test_regime = df_h1_with_regime.iloc[n_train_h1 + n_val_h1:].reset_index(drop=True)

        # --- 各セットでシグナル生成・バックテスト ---
        def _run_set(df_h1_set: pd.DataFrame, df_h1_regime: pd.DataFrame) -> FXBacktestResult:
            df_d1_sliced = self._d1_slice_for_period(df_d1_used, df_h1_set, ema_slow)
            try:
                df_sig = strategy.generate_signals(df_d1_sliced, df_h1_set.copy())
            except Exception as exc:
                log.warning("シグナル生成失敗: %s", exc)
                # 空シグナルで返す
                df_h1_set = df_h1_set.copy()
                df_h1_set["signal"] = 0
                df_h1_set["entry_price"] = df_h1_set["close"]
                df_h1_set["stop_loss"] = float("nan")
                df_h1_set["take_profit"] = float("nan")
                df_sig = df_h1_set

            df_filtered = self._apply_direction_filter(df_sig.copy(), direction)
            # regime 列をシグナルデータにアタッチしてからフィルター適用
            if regime_filter is not None and "regime" in df_h1_regime.columns:
                if len(df_filtered) == len(df_h1_regime):
                    df_filtered = df_filtered.copy()
                    df_filtered["regime"] = df_h1_regime["regime"].values
            df_filtered = self._apply_regime_filter(df_filtered, regime_filter)
            return runner.run(df_filtered, symbol="USD/JPY H1")

        result_train = _run_set(df_h1_train, df_h1_train_regime)
        result_val = _run_set(df_h1_val, df_h1_val_regime)
        result_test = _run_set(df_h1_test, df_h1_test_regime)

        # --- 全トレードを結合して regime 別集計 ---
        all_trades = (
            result_train.trades + result_val.trades + result_test.trades
        )
        regime_summary = self._summarize_by_regime(all_trades, df_h1_with_regime)

        return {
            "params": params,
            "data_info": data_info,
            "train": result_train,
            "val": result_val,
            "test": result_test,
            "regime_summary": regime_summary,
        }

    def _split(
        self,
        df: pd.DataFrame,
        train: float = 0.6,
        val: float = 0.2,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """時系列順で train/val/test に分割"""
        n = len(df)
        n_train = int(n * train)
        n_val = int(n * val)
        df_train = df.iloc[:n_train].reset_index(drop=True)
        df_val = df.iloc[n_train: n_train + n_val].reset_index(drop=True)
        df_test = df.iloc[n_train + n_val:].reset_index(drop=True)
        return df_train, df_val, df_test

    def _summarize_by_regime(
        self,
        trades: list[dict],
        df_h1_with_regime: pd.DataFrame,
    ) -> dict:
        """
        各トレードのエントリー時刻に対応する regime を照合して集計。
        """
        # timestamp -> regime のマッピングを構築
        ts_to_regime: dict = {}
        if "regime" in df_h1_with_regime.columns and "timestamp" in df_h1_with_regime.columns:
            for _, row in df_h1_with_regime.iterrows():
                ts_to_regime[pd.Timestamp(row["timestamp"])] = row["regime"]

        # 各 regime の初期値
        regime_data: dict[str, dict] = {
            MarketRegime.UP.value: {"pnl_list": [], "win_count": 0, "trade_count": 0},
            MarketRegime.DOWN.value: {"pnl_list": [], "win_count": 0, "trade_count": 0},
            MarketRegime.RANGE.value: {"pnl_list": [], "win_count": 0, "trade_count": 0},
        }

        for trade in trades:
            entry_ts = pd.Timestamp(trade["entry_time"])
            # 最近傍の timestamp を探す（H1足なので±1時間以内を許容）
            regime = MarketRegime.RANGE.value
            if entry_ts in ts_to_regime:
                regime = ts_to_regime[entry_ts]
            else:
                # 最も近い timestamp を探す
                if ts_to_regime:
                    closest = min(ts_to_regime.keys(), key=lambda t: abs((t - entry_ts).total_seconds()))
                    if abs((closest - entry_ts).total_seconds()) <= 3600:  # 1時間以内
                        regime = ts_to_regime[closest]

            pnl = trade.get("pnl_jpy", 0.0)
            regime_data[regime]["pnl_list"].append(pnl)
            regime_data[regime]["trade_count"] += 1
            if pnl > 0:
                regime_data[regime]["win_count"] += 1

        # サマリーを計算
        summary: dict[str, dict] = {}
        for reg_val, data in regime_data.items():
            tc = data["trade_count"]
            win_rate = data["win_count"] / tc if tc > 0 else 0.0
            pnl_list = data["pnl_list"]
            gross_profit = sum(p for p in pnl_list if p > 0)
            gross_loss = abs(sum(p for p in pnl_list if p <= 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            summary[reg_val] = {
                "trade_count": tc,
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 4),
            }

        return summary

    def _apply_regime_filter(
        self,
        df: pd.DataFrame,
        regime_filter: Optional[list[str]],
    ) -> pd.DataFrame:
        """
        regime_filter で指定した環境のシグナルのみ残す。
        regime_filter が None または空の場合はそのまま返す。
        df に 'regime' 列がない場合もそのまま返す。

        例: regime_filter=["uptrend"] → uptrend 以外のシグナルを 0 にする
        """
        if not regime_filter or "regime" not in df.columns:
            return df
        exclude_mask = ~df["regime"].isin(regime_filter) & (df["signal"] != 0)
        df.loc[exclude_mask, "signal"] = 0
        if "stop_loss" in df.columns:
            df.loc[exclude_mask, "stop_loss"] = float("nan")
        if "take_profit" in df.columns:
            df.loc[exclude_mask, "take_profit"] = float("nan")
        return df

    def _apply_direction_filter(self, df: pd.DataFrame, direction: str) -> pd.DataFrame:
        """
        "long_only" → signal=-1 を 0 に変換
        "short_only" → signal=1 を 0 に変換
        "both" → そのまま
        """
        if direction == "long_only":
            mask = df["signal"] == -1
            df.loc[mask, "signal"] = 0
            if "stop_loss" in df.columns:
                df.loc[mask, "stop_loss"] = float("nan")
            if "take_profit" in df.columns:
                df.loc[mask, "take_profit"] = float("nan")
        elif direction == "short_only":
            mask = df["signal"] == 1
            df.loc[mask, "signal"] = 0
            if "stop_loss" in df.columns:
                df.loc[mask, "stop_loss"] = float("nan")
            if "take_profit" in df.columns:
                df.loc[mask, "take_profit"] = float("nan")
        return df

    def _d1_slice_for_period(
        self,
        df_d1: pd.DataFrame,
        df_h1: pd.DataFrame,
        ema_slow: int = 200,
    ) -> pd.DataFrame:
        """
        df_h1 の期間に合わせて df_d1 をスライス（EMAウォームアップのため前方バッファ付き）。
        """
        if df_h1.empty or df_d1.empty:
            return df_d1.copy()

        h1_start = pd.to_datetime(df_h1["timestamp"].min(), utc=True)
        h1_end = pd.to_datetime(df_h1["timestamp"].max(), utc=True)

        df_d1 = df_d1.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_d1["timestamp"]):
            df_d1["timestamp"] = pd.to_datetime(df_d1["timestamp"], utc=True)
        df_d1 = df_d1.sort_values("timestamp").reset_index(drop=True)

        before_idx = df_d1[df_d1["timestamp"] < h1_start].index
        if len(before_idx) >= ema_slow:
            buf_start_idx = before_idx[-ema_slow]
        elif len(before_idx) > 0:
            buf_start_idx = before_idx[0]
        else:
            buf_start_idx = df_d1.index[0]

        sliced = df_d1.loc[buf_start_idx:].copy()
        sliced = sliced[sliced["timestamp"] <= h1_end].reset_index(drop=True)
        return sliced
