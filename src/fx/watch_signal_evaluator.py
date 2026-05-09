"""
FX Watch Candidate シグナルの事後評価モジュール。
実注文なし・研究用のみ。
OrderProposal・DRY_RUN注文には一切昇格しない。

評価ルール:
- buy : high >= take_profit → tp_hit, low <= stop_loss → sl_hit
- sell: low  <= take_profit → tp_hit, high >= stop_loss → sl_hit
- 同一足でTP/SL両方に到達 → ambiguous (勝率計算からは除外)
- timeout_bars 本経過しても未到達 → timeout
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from src.fx.strategy_candidate import WatchSignal

JST = ZoneInfo("Asia/Tokyo")
_PIP = 0.01  # USD/JPY: 1pip = 0.01


# ---------------------------------------------------------------------------
# 単一シグナル評価
# ---------------------------------------------------------------------------

def _to_pips(diff: float) -> float:
    return round(diff / _PIP, 2)


def evaluate_signal(
    sig: WatchSignal,
    df_h1: pd.DataFrame,
    timeout_bars: int = 24,
) -> WatchSignal:
    """
    open な単一シグナルを H1 データで評価し、status/resolution を更新して返す。
    既に resolved のシグナルはそのまま返す。
    実注文なし・研究用のみ。
    """
    if sig.status == "resolved":
        return sig

    if sig.action not in ("buy", "sell"):
        return replace(sig, status="no_signal", resolution="no_trade")

    if sig.stop_loss is None or sig.take_profit is None:
        return replace(sig, status="open", resolution="unresolved")

    if not sig.data_timestamp:
        return replace(sig, status="open", resolution="unresolved")

    # 参照エントリー価格: metadata["entry_price"] > current_price
    entry_price: float = sig.metadata.get("entry_price") or sig.current_price

    # H1 データのタイムスタンプを UTC 統一
    df = df_h1.copy()
    if df.empty or "timestamp" not in df.columns:
        return sig  # データ不足: 変更なし
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    try:
        data_ts = pd.Timestamp(sig.data_timestamp, tz="UTC")
    except Exception:
        return replace(sig, status="open", resolution="unresolved")

    bars_after = df[df["timestamp"] > data_ts].head(timeout_bars)

    if bars_after.empty:
        return sig  # データ不足: 変更なし

    tp = sig.take_profit
    sl = sig.stop_loss

    mfe_pips = 0.0
    mae_pips = 0.0
    resolution = "unresolved"
    resolution_bar_count: Optional[int] = None

    for bar_idx, (_, bar) in enumerate(bars_after.iterrows()):
        high = float(bar["high"])
        low = float(bar["low"])

        if sig.action == "buy":
            mfe_pips = max(mfe_pips, _to_pips(high - entry_price))
            mae_pips = max(mae_pips, _to_pips(entry_price - low))
            tp_hit = high >= tp
            sl_hit = low <= sl
        else:  # sell
            mfe_pips = max(mfe_pips, _to_pips(entry_price - low))
            mae_pips = max(mae_pips, _to_pips(high - entry_price))
            tp_hit = low <= tp
            sl_hit = high >= sl

        if tp_hit and sl_hit:
            resolution = "ambiguous"
            resolution_bar_count = bar_idx + 1
            break
        elif tp_hit:
            resolution = "tp_hit"
            resolution_bar_count = bar_idx + 1
            break
        elif sl_hit:
            resolution = "sl_hit"
            resolution_bar_count = bar_idx + 1
            break
    else:
        # ループが break なしで終了 = timeout_bars 本経過
        if len(bars_after) >= timeout_bars:
            resolution = "timeout"
            resolution_bar_count = timeout_bars

    status = (
        "resolved"
        if resolution in ("tp_hit", "sl_hit", "ambiguous", "timeout")
        else "open"
    )

    return replace(
        sig,
        status=status,
        resolution=resolution,
        resolution_bar_count=resolution_bar_count,
        mfe_pips=round(mfe_pips, 2),
        mae_pips=round(mae_pips, 2),
    )


# ---------------------------------------------------------------------------
# 全シグナル一括評価
# ---------------------------------------------------------------------------

def evaluate_all_signals(
    signals: list[WatchSignal],
    df_h1: pd.DataFrame,
    timeout_bars: int = 24,
) -> list[WatchSignal]:
    """
    全シグナルを評価して返す。
    - no_signal / skip → status="no_signal", resolution="no_trade"
    - 既に resolved → 変更なし
    - buy / sell / open → evaluate_signal() で評価
    実注文なし・研究用のみ。
    """
    results: list[WatchSignal] = []
    for sig in signals:
        if sig.status == "resolved":
            results.append(sig)
        elif sig.action not in ("buy", "sell"):
            results.append(replace(sig, status="no_signal", resolution="no_trade"))
        else:
            results.append(evaluate_signal(sig, df_h1, timeout_bars=timeout_bars))
    return results


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------

def _safe_avg(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def aggregate_evaluation(signals: list[WatchSignal]) -> dict:
    """集計統計辞書を返す。"""
    actionable = [s for s in signals if s.action in ("buy", "sell")]
    buy_sigs = [s for s in actionable if s.action == "buy"]
    sell_sigs = [s for s in actionable if s.action == "sell"]

    tp_list = [s for s in actionable if s.resolution == "tp_hit"]
    sl_list = [s for s in actionable if s.resolution == "sl_hit"]
    to_list = [s for s in actionable if s.resolution == "timeout"]
    amb_list = [s for s in actionable if s.resolution == "ambiguous"]
    open_list = [s for s in actionable if s.status == "open"]

    decisive = len(tp_list) + len(sl_list) + len(amb_list)
    win_rate = round(len(tp_list) / decisive, 4) if decisive > 0 else None

    mfe_vals = [s.mfe_pips for s in actionable if s.mfe_pips is not None]
    mae_vals = [s.mae_pips for s in actionable if s.mae_pips is not None]
    res_bars = [
        float(s.resolution_bar_count)
        for s in actionable
        if s.resolution_bar_count is not None
    ]

    return {
        "total_signals": len(signals),
        "actionable_signals": len(actionable),
        "buy_count": len(buy_sigs),
        "sell_count": len(sell_sigs),
        "tp_hit": len(tp_list),
        "sl_hit": len(sl_list),
        "timeout": len(to_list),
        "ambiguous": len(amb_list),
        "open": len(open_list),
        "win_rate": win_rate,
        "avg_mfe": _safe_avg(mfe_vals),
        "avg_mae": _safe_avg(mae_vals),
        "avg_time_to_resolution": _safe_avg(res_bars),
    }


def monthly_summary(signals: list[WatchSignal]) -> list[dict]:
    """月次サマリーリストを返す。"""
    months: dict[str, list[WatchSignal]] = defaultdict(list)
    for s in signals:
        if s.action not in ("buy", "sell"):
            continue
        month = s.created_at[:7]  # "YYYY-MM"
        months[month].append(s)

    rows = []
    for month in sorted(months.keys()):
        group = months[month]
        tp = sum(1 for s in group if s.resolution == "tp_hit")
        sl = sum(1 for s in group if s.resolution == "sl_hit")
        amb = sum(1 for s in group if s.resolution == "ambiguous")
        denom = tp + sl + amb
        wr = round(tp / denom, 4) if denom > 0 else None
        rows.append({
            "month": month,
            "trades": len(group),
            "tp_hit": tp,
            "sl_hit": sl,
            "ambiguous": amb,
            "win_rate": wr,
        })
    return rows


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------

def render_evaluation_report(
    signals: list[WatchSignal],
    generated_at: datetime,
    timeout_bars: int = 24,
) -> str:
    """
    FX Watch Candidate 評価レポートを Markdown 文字列で返す。
    実注文なし・研究用のみ。
    """
    stats = aggregate_evaluation(signals)
    monthly = monthly_summary(signals)

    def _pct(v: Optional[float]) -> str:
        return f"{v * 100:.1f}%" if v is not None else "n/a"

    def _fmt(v: Optional[float], d: int = 2) -> str:
        return f"{v:.{d}f}" if v is not None else "n/a"

    lines: list[str] = [
        "# FX Watch Candidate 評価レポート",
        "",
        f"- 生成日時: {generated_at.astimezone(JST).isoformat()}",
        f"- 戦略: usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all",
        f"- timeout_bars: {timeout_bars}",
        "- 実注文なし・研究用のみ",
        "",
        "## 集計サマリー",
        "",
        "| 項目 | 値 |",
        "|------|----|",
        f"| total_signals | {stats['total_signals']} |",
        f"| actionable_signals (buy+sell) | {stats['actionable_signals']} |",
        f"| buy_count | {stats['buy_count']} |",
        f"| sell_count | {stats['sell_count']} |",
        f"| tp_hit | {stats['tp_hit']} |",
        f"| sl_hit | {stats['sl_hit']} |",
        f"| timeout | {stats['timeout']} |",
        f"| ambiguous | {stats['ambiguous']} |",
        f"| open (未解決) | {stats['open']} |",
        f"| win_rate (TP / TP+SL+ambiguous) | {_pct(stats['win_rate'])} |",
        f"| avg_mfe | {_fmt(stats['avg_mfe'])} pips |",
        f"| avg_mae | {_fmt(stats['avg_mae'])} pips |",
        f"| avg_time_to_resolution | {_fmt(stats['avg_time_to_resolution'])} bars |",
        "",
    ]

    # 月次サマリー
    lines += ["## 月次サマリー", ""]
    if monthly:
        lines += [
            "| 月 | trades | tp_hit | sl_hit | ambiguous | win_rate |",
            "|---|--------|--------|--------|-----------|----------|",
        ]
        for row in monthly:
            lines.append(
                f"| {row['month']} | {row['trades']} | {row['tp_hit']}"
                f" | {row['sl_hit']} | {row['ambiguous']} | {_pct(row['win_rate'])} |"
            )
    else:
        lines += ["- none"]
    lines.append("")

    # シグナル詳細（actionable のみ、新しい順）
    actionable = [s for s in signals if s.action in ("buy", "sell")]
    if actionable:
        lines += ["## シグナル詳細", ""]
        lines += [
            "| signal_id | created_at | action | status | resolution | mfe_pips | mae_pips | bars |",
            "|-----------|------------|--------|--------|------------|----------|----------|------|",
        ]
        for s in sorted(actionable, key=lambda x: x.created_at, reverse=True):
            bars_str = str(s.resolution_bar_count) if s.resolution_bar_count is not None else "n/a"
            lines.append(
                f"| {s.signal_id} | {s.created_at[:10]} | {s.action}"
                f" | {s.status} | {s.resolution}"
                f" | {_fmt(s.mfe_pips)} | {_fmt(s.mae_pips)} | {bars_str} |"
            )
        lines.append("")

    lines += [
        "---",
        "実注文なし・研究用のみ。OrderProposal・DRY_RUN注文には昇格しない。",
    ]

    return "\n".join(lines) + "\n"
