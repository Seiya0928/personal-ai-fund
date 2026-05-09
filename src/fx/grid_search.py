"""
USD/JPY EMAトレンドフォロー戦略 パラメータグリッドサーチ
実注文なし・研究用のみ
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.fx.fx_backtest import FXBacktestResult, FXBacktestRunner
from src.fx.strategy import MultiTimeframeEMAStrategy
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class GridSearchConfig:
    ema_fast_list: list = field(default_factory=lambda: [20, 50, 75])
    ema_slow_list: list = field(default_factory=lambda: [100, 150, 200])
    breakout_lookback_list: list = field(default_factory=lambda: [5, 10, 20])
    atr_sl_multiplier_list: list = field(default_factory=lambda: [1.0, 1.5, 2.0])
    rr_ratio_list: list = field(default_factory=lambda: [1.5, 2.0, 2.5])
    direction_list: list = field(default_factory=lambda: ["both", "long_only", "short_only"])
    min_trade_count: int = 30
    val_min_profit_factor: float = 1.1
    val_max_drawdown_pct: float = 10.0
    initial_balance: float = 1_000_000.0


@dataclass
class GridSearchResult:
    params: dict          # パラメータの辞書
    direction: str        # "both" / "long_only" / "short_only"
    train: FXBacktestResult
    val: FXBacktestResult
    test: Optional[FXBacktestResult] = None
    passes_val_filter: bool = False


class FXGridSearch:
    """
    USD/JPY EMAトレンドフォロー戦略のパラメータグリッドサーチ。
    実注文なし・研究用のみ。
    """

    def __init__(self, config: GridSearchConfig = None) -> None:
        self.config = config or GridSearchConfig()

    def run(
        self,
        df_m15_train: pd.DataFrame = None,
        df_m15_val: pd.DataFrame = None,
        df_h4_full: pd.DataFrame = None,
        df_m15_test: Optional[pd.DataFrame] = None,
        # 汎化引数（H1/D1 対応）
        df_entry_train: pd.DataFrame = None,
        df_entry_val: pd.DataFrame = None,
        df_trend_full: pd.DataFrame = None,
        df_entry_test: Optional[pd.DataFrame] = None,
        timeframe: str = "M15",
    ) -> list[GridSearchResult]:
        """
        全パラメータ組み合わせでバックテストを実行。
        fast >= slow の組み合わせは除外。
        結果を val profit_factor 降順でソートして返す。

        後方互換: df_m15_train, df_m15_val, df_h4_full の引数名はそのまま使える。
        汎化引数: df_entry_train, df_entry_val, df_trend_full を使うと H1/D1 にも対応。
        timeframe: "M15" または "H1"（ログ用）
        """
        # 後方互換: 汎化引数が指定された場合は優先して使用
        if df_entry_train is not None:
            df_m15_train = df_entry_train
        if df_entry_val is not None:
            df_m15_val = df_entry_val
        if df_trend_full is not None:
            df_h4_full = df_trend_full
        if df_entry_test is not None:
            df_m15_test = df_entry_test
        cfg = self.config
        results: list[GridSearchResult] = []

        # パラメータ組み合わせを生成（directionを除く）
        param_combos = list(itertools.product(
            cfg.ema_fast_list,
            cfg.ema_slow_list,
            cfg.breakout_lookback_list,
            cfg.atr_sl_multiplier_list,
            cfg.rr_ratio_list,
        ))

        total_combos = len(param_combos) * len(cfg.direction_list)
        skipped_invalid = 0
        skipped_trade_count = 0
        evaluated = 0

        print(f"[GridSearch] パラメータ組み合わせ総数（direction含む）: {total_combos}")

        runner = FXBacktestRunner(
            initial_balance=cfg.initial_balance,
            spread_pips=0.3,
            slippage_pips=0.1,
            commission_pips=0.0,
            pip_value_jpy=100.0,
        )

        for combo_idx, (ema_fast, ema_slow, lookback, atr_sl, rr) in enumerate(param_combos):
            # fast >= slow は無効な組み合わせとして除外
            if ema_fast >= ema_slow:
                skipped_invalid += len(cfg.direction_list)
                continue

            params = {
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "breakout_lookback": lookback,
                "atr_sl_multiplier": atr_sl,
                "rr_ratio": rr,
            }

            # ストラテジーインスタンス生成
            strategy = MultiTimeframeEMAStrategy(
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                breakout_lookback=lookback,
                atr_sl_multiplier=atr_sl,
                rr_ratio=rr,
            )

            # H4スライス（trainとvalとtestにバッファ付きでH4を準備）
            df_h4_train = self._h4_slice_for_period(df_h4_full, df_m15_train, ema_slow)
            df_h4_val = self._h4_slice_for_period(df_h4_full, df_m15_val, ema_slow)

            # シグナル生成（train）
            try:
                df_sig_train = strategy.generate_signals(df_h4_train, df_m15_train.copy())
                df_sig_val = strategy.generate_signals(df_h4_val, df_m15_val.copy())
            except Exception as exc:
                log.warning("シグナル生成失敗 (params=%s): %s", params, exc)
                continue

            # direction別に処理
            for direction in cfg.direction_list:
                evaluated += 1

                df_train_filtered = self._apply_direction_filter(df_sig_train.copy(), direction)
                df_val_filtered = self._apply_direction_filter(df_sig_val.copy(), direction)

                # trainバックテスト
                result_train = runner.run(df_train_filtered, symbol="USD/JPY")

                # train trade_count < min_trade_count は除外
                if result_train.trade_count < cfg.min_trade_count:
                    skipped_trade_count += 1
                    continue

                # valバックテスト
                result_val = runner.run(df_val_filtered, symbol="USD/JPY")

                # valフィルター判定（val trade_count >= min_trade_count も必要）
                passes = (
                    result_val.trade_count >= cfg.min_trade_count
                    and result_val.profit_factor >= cfg.val_min_profit_factor
                    and result_val.max_drawdown_pct <= cfg.val_max_drawdown_pct
                )

                # testバックテスト（df_m15_testがある場合）
                result_test = None
                if df_m15_test is not None and passes:
                    df_h4_test = self._h4_slice_for_period(df_h4_full, df_m15_test, ema_slow)
                    try:
                        df_sig_test = strategy.generate_signals(df_h4_test, df_m15_test.copy())
                        df_test_filtered = self._apply_direction_filter(df_sig_test, direction)
                        result_test = runner.run(df_test_filtered, symbol="USD/JPY")
                    except Exception as exc:
                        log.warning("test シグナル生成失敗 (params=%s): %s", params, exc)

                gs_result = GridSearchResult(
                    params=params.copy(),
                    direction=direction,
                    train=result_train,
                    val=result_val,
                    test=result_test,
                    passes_val_filter=passes,
                )
                results.append(gs_result)

            if (combo_idx + 1) % 20 == 0:
                valid_combos = combo_idx + 1 - skipped_invalid // len(cfg.direction_list)
                print(f"  [{combo_idx + 1}/{len(param_combos)}] 処理中... 評価済={evaluated}, 除外(invalid)={skipped_invalid}, 除外(trade数不足)={skipped_trade_count}")

        print(f"[GridSearch] 完了: 評価={evaluated}, 除外(invalid)={skipped_invalid}, 除外(trade数不足)={skipped_trade_count}")
        print(f"[GridSearch] valフィルター通過: {sum(1 for r in results if r.passes_val_filter)} / {len(results)}")

        # val profit_factor 降順でソート
        results.sort(key=lambda r: r.val.profit_factor, reverse=True)
        return results

    def _apply_direction_filter(self, df: pd.DataFrame, direction: str) -> pd.DataFrame:
        """
        "long_only" → signal=-1 を 0 に変換
        "short_only" → signal=1 を 0 に変換
        "both" → そのまま
        """
        if direction == "long_only":
            mask = df["signal"] == -1
            df.loc[mask, "signal"] = 0
            df.loc[mask, "stop_loss"] = float("nan")
            df.loc[mask, "take_profit"] = float("nan")
        elif direction == "short_only":
            mask = df["signal"] == 1
            df.loc[mask, "signal"] = 0
            df.loc[mask, "stop_loss"] = float("nan")
            df.loc[mask, "take_profit"] = float("nan")
        # "both" はそのまま
        return df

    def _h4_slice_for_period(
        self,
        df_h4: pd.DataFrame,
        df_m15: pd.DataFrame,
        ema_slow: int = 200,
    ) -> pd.DataFrame:
        """
        df_m15 の期間に合わせて df_h4 をスライス（EMAウォームアップのため前後バッファ付き）。
        slow EMA分のバッファ（ema_slow本）を前方に追加する。
        """
        if df_m15.empty or df_h4.empty:
            return df_h4.copy()

        m15_start = pd.to_datetime(df_m15["timestamp"].min())
        m15_end = pd.to_datetime(df_m15["timestamp"].max())

        df_h4 = df_h4.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_h4["timestamp"]):
            df_h4["timestamp"] = pd.to_datetime(df_h4["timestamp"])

        # H4ソート
        df_h4 = df_h4.sort_values("timestamp").reset_index(drop=True)

        # m15_start 以前のH4行を取得してバッファとして使う
        before_idx = df_h4[df_h4["timestamp"] < m15_start].index
        if len(before_idx) >= ema_slow:
            buf_start_idx = before_idx[-ema_slow]
        elif len(before_idx) > 0:
            buf_start_idx = before_idx[0]
        else:
            buf_start_idx = df_h4.index[0]

        sliced = df_h4.loc[buf_start_idx:].copy()
        sliced = sliced[sliced["timestamp"] <= m15_end].reset_index(drop=True)
        return sliced

    def summarize(self, results: list[GridSearchResult]) -> str:
        """
        グリッドサーチ結果のサマリーを生成。
        """
        if not results:
            return "結果がありません。"

        total = len(results)
        passes = [r for r in results if r.passes_val_filter]
        n_pass = len(passes)

        # direction別の通過数
        direction_pass: dict[str, int] = {}
        for r in passes:
            direction_pass[r.direction] = direction_pass.get(r.direction, 0) + 1

        # 上位5候補（val pf順・既にソート済み）
        top5 = results[:5]

        lines: list[str] = []
        lines.append(f"- 評価した組み合わせ総数: {total}")
        lines.append(f"- val フィルター通過: {n_pass} / {total}  ※val trade_count < {self.config.min_trade_count} で除外")
        lines.append(f"- direction 別通過数: {direction_pass}")
        lines.append("")
        lines.append("### 上位5候補（val profit_factor 順）")
        lines.append(
            "| rank | direction | ema_fast | ema_slow | lookback | atr_sl | rr | "
            "train_pf | val_pf | val_mdd | val_trades | val_win_rate |"
        )
        lines.append(
            "|------|-----------|----------|----------|----------|--------|----|"
            "----------|--------|---------|------------|--------------|"
        )
        for rank, r in enumerate(top5, 1):
            p = r.params
            lines.append(
                f"| {rank} | {r.direction} | {p['ema_fast']} | {p['ema_slow']} | "
                f"{p['breakout_lookback']} | {p['atr_sl_multiplier']} | {p['rr_ratio']} | "
                f"{r.train.profit_factor:.2f} | {r.val.profit_factor:.2f} | "
                f"{r.val.max_drawdown_pct:.2f}% | {r.val.trade_count} | "
                f"{r.val.win_rate * 100:.1f}% |"
            )

        lines.append("")
        lines.append("### MFE/MAE 分析（全候補の平均）")

        # 全候補のMFE/MAE集計
        all_results_flat = results
        if all_results_flat:
            avg_win_mfe = _safe_mean([r.val.avg_mfe_win_pips for r in all_results_flat if r.val.trade_count > 0])
            avg_win_mae = _safe_mean([r.val.avg_mae_win_pips for r in all_results_flat if r.val.trade_count > 0])
            avg_lose_mfe = _safe_mean([r.val.avg_mfe_lose_pips for r in all_results_flat if r.val.trade_count > 0])
            avg_lose_mae = _safe_mean([r.val.avg_mae_lose_pips for r in all_results_flat if r.val.trade_count > 0])
            total_lose = sum(r.val.trade_count - int(r.val.win_rate * r.val.trade_count) for r in all_results_flat)
            total_failed_half = sum(r.val.failed_after_half_tp_count for r in all_results_flat)
            pct_failed = total_failed_half / total_lose * 100 if total_lose > 0 else 0.0

            lines.append(f"- 勝ちトレード: 平均MFE={avg_win_mfe:.1f}pips, 平均MAE={avg_win_mae:.1f}pips")
            lines.append(f"- 負けトレード: 平均MFE={avg_lose_mfe:.1f}pips, 平均MAE={avg_lose_mae:.1f}pips")
            lines.append(
                f"- 一度TP50%以上まで届いて損切りになったトレード: {total_failed_half}件 "
                f"(全負けの {pct_failed:.1f}%)"
            )

        return "\n".join(lines)


def _safe_mean(values: list[float]) -> float:
    """リストの平均を計算する（空の場合は0.0）。"""
    return sum(values) / len(values) if values else 0.0
