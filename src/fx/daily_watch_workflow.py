# 日次 FX Watch Candidate ワークフロー — 純粋関数群。実注文なし・研究用のみ。
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd

from src.fx.strategy_candidate import (
    DEFAULT_WATCH_SIGNALS_PATH,
    list_watch_signals,
    watch_signal_from_dict,
)
from src.fx.watch_signal_evaluator import aggregate_evaluation

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_safety_flags(root: Optional[Path] = None) -> tuple[bool, bool, bool]:
    """
    安全フラグを読み込む。

    Returns
    -------
    (stop_trading_active, dry_run, read_only)
    """
    if root is None:
        root = _PROJECT_ROOT

    stop_trading_active = (root / "STOP_TRADING").exists()
    dry_run = os.getenv("DRY_RUN", "true").lower() not in ("false", "0", "no")
    read_only = os.getenv("READ_ONLY", "true").lower() not in ("false", "0", "no")

    return stop_trading_active, dry_run, read_only


def get_ohlcv_data(fetcher=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    H1/D1 データを読み込む。
    D1 が空の場合は H1 からリサンプル。

    Parameters
    ----------
    fetcher : YFinanceFetcher or None
        省略時は YFinanceFetcher() を生成する。

    Returns
    -------
    (df_h1, df_d1)
    """
    if fetcher is None:
        from src.fx.ohlcv_fetcher import YFinanceFetcher
        fetcher = YFinanceFetcher()

    df_h1 = fetcher.load_latest("H1")
    df_d1 = fetcher.load_latest("D1")

    if df_d1.empty and not df_h1.empty:
        from src.fx.data_loader import FXDataLoader
        loader = FXDataLoader()
        df_d1 = loader.resample(df_h1, to="1D")

    return df_h1, df_d1


def compute_watch_eval_stats(
    signals_path: Optional[Path] = None,
) -> dict:
    """
    保存済みシグナルを読み込み aggregate_evaluation を返す。
    シグナルがなければ空の stats dict を返す。

    Parameters
    ----------
    signals_path : Path or None
        省略時は DEFAULT_WATCH_SIGNALS_PATH を使用。

    Returns
    -------
    dict  (aggregate_evaluation の戻り値と同じ形式)
    """
    path = signals_path or DEFAULT_WATCH_SIGNALS_PATH
    raw_list = list_watch_signals(path)

    if not raw_list:
        return {}

    signals = [watch_signal_from_dict(d) for d in raw_list]
    return aggregate_evaluation(signals)


def compute_unresolved_count(signals_path: Optional[Path] = None) -> int:
    """
    status == "open" のシグナル数を返す。

    Parameters
    ----------
    signals_path : Path or None
        省略時は DEFAULT_WATCH_SIGNALS_PATH を使用。

    Returns
    -------
    int
    """
    path = signals_path or DEFAULT_WATCH_SIGNALS_PATH
    raw_list = list_watch_signals(path)
    return sum(1 for d in raw_list if d.get("status") == "open")
