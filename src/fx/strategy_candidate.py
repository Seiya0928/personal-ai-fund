# 実注文なし・研究用 watch-only シグナル候補
# このモジュールは取引所APIを一切呼びません。注文提案にも昇格しません。
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields as _dc_fields
from pathlib import Path
from typing import Optional

DEFAULT_WATCH_SIGNALS_PATH = (
    Path(__file__).resolve().parents[2] / "state" / "fx_watch_signals.json"
)


@dataclass(frozen=True)
class StrategyCandidateConfig:
    """
    watch_candidate として固定した戦略パラメータ。
    実注文なし・研究用のみ。
    """
    strategy_name: str = "usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all"
    timeframe_entry: str = "H1"
    timeframe_trend: str = "D1"
    ema_fast: int = 20
    ema_slow: int = 200
    breakout_lookback: int = 5
    atr_sl_multiplier: float = 1.5
    rr_ratio: float = 1.5
    direction: str = "both"    # "both" | "long_only" | "short_only"
    regime_filter: str = "all"  # 全環境フィルターなし
    status: str = "watch_candidate"


# シングルトン: 第一候補として固定された戦略
USDJPY_PRIMARY_CANDIDATE = StrategyCandidateConfig()


@dataclass
class WatchSignal:
    """
    watch_candidate の現在シグナル。
    実注文・OrderProposal・DRY_RUN注文には一切昇格しない。
    """
    # --- シグナル本体 ---
    signal_id: str
    strategy_name: str
    created_at: str            # ISO JST
    data_timestamp: str        # 最後の H1 バーの timestamp (UTC)
    action: str                # "buy" | "sell" | "no_signal" | "skip"
    current_price: float
    trend_direction: str       # "UP" | "DOWN" | "FLAT"
    breakout_level: Optional[float]   # recent_high (buy) / recent_low (sell)
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_pips: Optional[float]
    reward_pips: Optional[float]
    rr_ratio: Optional[float]
    reason: str

    # --- 評価フィールド（デフォルト付き） ---
    instrument: str = "USD_JPY"
    status: str = "open"          # "open" | "resolved" | "no_signal"
    resolution: str = "unresolved"  # "tp_hit" | "sl_hit" | "timeout" | "no_trade" | "unresolved" | "ambiguous"
    resolution_bar_count: Optional[int] = None   # 解決までの H1 本数
    mfe_pips: Optional[float] = None             # Maximum Favorable Excursion
    mae_pips: Optional[float] = None             # Maximum Adverse Excursion

    metadata: dict = field(default_factory=dict)


def watch_signal_to_dict(sig: WatchSignal) -> dict:
    return asdict(sig)


def watch_signal_from_dict(d: dict) -> WatchSignal:
    """
    旧フォーマット (instrument/status/resolution フィールドなし) とも互換。
    未知フィールドは無視し、既知フィールドのデフォルトを維持する。
    """
    known = {f.name for f in _dc_fields(WatchSignal)}
    return WatchSignal(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Storage: state/fx_watch_signals.json
# ---------------------------------------------------------------------------

def load_watch_signals(path: Path = DEFAULT_WATCH_SIGNALS_PATH) -> dict:
    if not path.exists():
        return {"signals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("signals"), list):
        raise ValueError("fx_watch_signals.json の形式が不正です。")
    return payload


def save_watch_signals(payload: dict, path: Path = DEFAULT_WATCH_SIGNALS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_watch_signals(path: Path = DEFAULT_WATCH_SIGNALS_PATH) -> list[dict]:
    return load_watch_signals(path)["signals"]


def save_watch_signal(
    sig: WatchSignal,
    path: Path = DEFAULT_WATCH_SIGNALS_PATH,
) -> tuple[dict, bool]:
    """重複（同じ signal_id）はスキップ。(stored, is_new) を返す。"""
    payload = load_watch_signals(path)
    stored = watch_signal_to_dict(sig)
    for existing in payload["signals"]:
        if existing.get("signal_id") == sig.signal_id:
            return existing, False
    payload["signals"].append(stored)
    save_watch_signals(payload, path)
    return stored, True


def update_watch_signal(
    sig: WatchSignal,
    path: Path = DEFAULT_WATCH_SIGNALS_PATH,
) -> None:
    """signal_id が一致するシグナルを上書き更新する。存在しない場合は追加。"""
    payload = load_watch_signals(path)
    updated = watch_signal_to_dict(sig)
    for i, existing in enumerate(payload["signals"]):
        if existing.get("signal_id") == sig.signal_id:
            payload["signals"][i] = updated
            save_watch_signals(payload, path)
            return
    # 存在しない場合は追加
    payload["signals"].append(updated)
    save_watch_signals(payload, path)
