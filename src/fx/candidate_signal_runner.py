"""
watch_candidate 戦略の現在シグナルを生成するモジュール。
実注文なし・研究用のみ。
OrderProposal・DRY_RUN注文には昇格しない。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.fx.strategy import MultiTimeframeEMAStrategy
from src.fx.strategy_candidate import (
    USDJPY_PRIMARY_CANDIDATE,
    StrategyCandidateConfig,
    WatchSignal,
)
from src.utils.logger import get_logger

JST = ZoneInfo("Asia/Tokyo")
_PIP = 0.01   # USD/JPY: 1pip = 0.01

log = get_logger(__name__)


def _jst_now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _action_from_signal(signal_val: int, direction: str) -> str:
    """
    signal 値 (1/-1/0) と direction から WatchSignal.action を決定する。
    """
    if signal_val == 1:
        if direction in ("both", "long_only"):
            return "buy"
        return "skip"     # short_only のため除外
    if signal_val == -1:
        if direction in ("both", "short_only"):
            return "sell"
        return "skip"     # long_only のため除外
    return "no_signal"


def _build_reason(action: str, last: pd.Series, config: StrategyCandidateConfig) -> str:
    trend = last.get("trend", "FLAT")
    ema_f = last.get("ema_fast", float("nan"))
    ema_s = last.get("ema_slow", float("nan"))
    if action == "buy":
        bl = last.get("recent_high", float("nan"))
        return (
            f"EMA{config.ema_fast}({ema_f:.3f}) > EMA{config.ema_slow}({ema_s:.3f}) "
            f"上昇トレンド確認 + {config.breakout_lookback}本高値({bl:.3f})ブレイクアウト"
        )
    if action == "sell":
        bl = last.get("recent_low", float("nan"))
        return (
            f"EMA{config.ema_fast}({ema_f:.3f}) < EMA{config.ema_slow}({ema_s:.3f}) "
            f"下降トレンド確認 + {config.breakout_lookback}本安値({bl:.3f})ブレイクアウト"
        )
    if action == "skip":
        return f"direction={config.direction} のため除外"
    return f"シグナルなし（trend={trend}, signal=0）"


def _pips(val: Optional[float]) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    return round(val / _PIP, 2)


def run_candidate_signal(
    df_h1: pd.DataFrame,
    df_d1: pd.DataFrame,
    config: StrategyCandidateConfig = USDJPY_PRIMARY_CANDIDATE,
    created_at: Optional[str] = None,
) -> WatchSignal:
    """
    最新の H1 データから watch_candidate のシグナルを生成して返す。
    実注文・OrderProposal・DRY_RUN注文には昇格しない。

    Parameters
    ----------
    df_h1 : pd.DataFrame
        H1 OHLCV データ（エントリー足）
    df_d1 : pd.DataFrame
        D1 OHLCV データ（トレンド判定足）
    config : StrategyCandidateConfig
        戦略パラメータ（デフォルト: USDJPY_PRIMARY_CANDIDATE）
    created_at : str or None
        シグナル生成時刻（省略時は現在の JST）

    Returns
    -------
    WatchSignal
    """
    if created_at is None:
        created_at = _jst_now()

    if df_h1.empty:
        return _empty_signal(config, created_at, reason="H1データが空です")
    if df_d1.empty:
        return _empty_signal(config, created_at, reason="D1データが空です")

    # --- データ準備 ---
    df_h1 = df_h1.copy()
    df_h1["timestamp"] = pd.to_datetime(df_h1["timestamp"], utc=True)
    df_h1 = df_h1.sort_values("timestamp").reset_index(drop=True)

    df_d1 = df_d1.copy()
    df_d1["timestamp"] = pd.to_datetime(df_d1["timestamp"], utc=True)
    df_d1 = df_d1.sort_values("timestamp").reset_index(drop=True)

    # --- ストラテジーでシグナル生成 ---
    strategy = MultiTimeframeEMAStrategy(
        ema_fast=config.ema_fast,
        ema_slow=config.ema_slow,
        breakout_lookback=config.breakout_lookback,
        atr_sl_multiplier=config.atr_sl_multiplier,
        rr_ratio=config.rr_ratio,
        entry_timeframe=config.timeframe_entry,
        trend_timeframe=config.timeframe_trend,
    )

    try:
        df_sig = strategy.generate_signals(df_d1, df_h1)
    except Exception as exc:
        log.warning("generate_signals 失敗: %s", exc)
        return _empty_signal(config, created_at, reason=f"シグナル生成エラー: {exc}")

    last = df_sig.iloc[-1]
    signal_val = int(last.get("signal", 0))
    action = _action_from_signal(signal_val, config.direction)
    reason = _build_reason(action, last, config)

    # --- 各フィールド抽出 ---
    current_price = float(last.get("close", float("nan")))
    trend_direction = str(last.get("trend", "FLAT"))

    if action == "buy":
        breakout_level = _optional_float(last.get("recent_high"))
    elif action == "sell":
        breakout_level = _optional_float(last.get("recent_low"))
    else:
        breakout_level = None

    entry_price = _optional_float(last.get("entry_price"))
    sl = _optional_float(last.get("stop_loss"))
    tp = _optional_float(last.get("take_profit"))

    if entry_price is not None and sl is not None:
        risk_pips = _pips(abs(entry_price - sl))
    else:
        risk_pips = None

    if entry_price is not None and tp is not None:
        reward_pips = _pips(abs(tp - entry_price))
    else:
        reward_pips = None

    rr = round(reward_pips / risk_pips, 2) if (risk_pips and risk_pips > 0 and reward_pips) else None

    data_ts = str(last.get("timestamp", ""))

    signal_id = (
        f"watch_{config.strategy_name}_{created_at[:10].replace('-', '')}"
        f"_{action}"
    )

    log.info(
        "run_candidate_signal: action=%s, price=%.3f, sl=%s, tp=%s, trend=%s",
        action, current_price, sl, tp, trend_direction,
    )

    _status = "no_signal" if action in ("no_signal", "skip") else "open"
    _resolution = "no_trade" if action in ("no_signal", "skip") else "unresolved"

    return WatchSignal(
        signal_id=signal_id,
        strategy_name=config.strategy_name,
        created_at=created_at,
        data_timestamp=data_ts,
        action=action,
        current_price=current_price,
        trend_direction=trend_direction,
        breakout_level=breakout_level,
        stop_loss=sl,
        take_profit=tp,
        risk_pips=risk_pips,
        reward_pips=reward_pips,
        rr_ratio=rr,
        reason=reason,
        instrument="USD_JPY",
        status=_status,
        resolution=_resolution,
        metadata={
            "ema_fast_value": _optional_float(last.get("ema_fast")),
            "ema_slow_value": _optional_float(last.get("ema_slow")),
            "atr": _optional_float(last.get("atr")),
            "recent_high": _optional_float(last.get("recent_high")),
            "recent_low": _optional_float(last.get("recent_low")),
            "entry_price": entry_price,
            "config_status": config.status,
        },
    )


def _optional_float(val: object) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
        return f if not pd.isna(f) else None
    except (TypeError, ValueError):
        return None


def _empty_signal(
    config: StrategyCandidateConfig,
    created_at: str,
    reason: str,
) -> WatchSignal:
    signal_id = (
        f"watch_{config.strategy_name}_{created_at[:10].replace('-', '')}_skip"
    )
    return WatchSignal(
        signal_id=signal_id,
        strategy_name=config.strategy_name,
        created_at=created_at,
        data_timestamp="",
        action="skip",
        current_price=0.0,
        trend_direction="FLAT",
        breakout_level=None,
        stop_loss=None,
        take_profit=None,
        risk_pips=None,
        reward_pips=None,
        rr_ratio=None,
        reason=reason,
        instrument="USD_JPY",
        status="no_signal",
        resolution="no_trade",
    )
