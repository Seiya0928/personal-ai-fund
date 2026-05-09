"""
FX ペーパートレード（BTCのpaper_tradesと同じ思想、FX固有の差異あり）。
実注文なし・研究用のみ。

主な差異:
- BUY or SELL（BTCはBUYのみ）
- SL/TPは絶対価格（パーセンテージではない）
- P&L はpip計算: BUY=(exit-entry)*units, SELL=(entry-exit)*units
- 保有時間は時間単位（H1タイムフレーム）
- max_holding_deadline はISOタイムスタンプ（日付ではない）
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_FX_PAPER_TRADES_PATH = Path(__file__).resolve().parents[2] / "state" / "fx_paper_trades.json"
JST = ZoneInfo("Asia/Tokyo")

FX_PAPER_TRADE_RULES = (
    {"rule_id": "Conservative", "max_holding_hours": 24},
    {"rule_id": "Current",      "max_holding_hours": 48},
    {"rule_id": "Wide",         "max_holding_hours": 96},
)

# USD/JPY: 1 pip = 0.01
_PIP_SIZE = 0.01


@dataclass
class FXPaperTrade:
    paper_trade_id: str
    source_signal_id: str
    source_order_proposal_id: str
    rule_id: str
    symbol: str                    # "USD/JPY"
    side: str                      # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    take_profit: float
    usd_units: float               # e.g. 1000.0
    max_loss_jpy: float
    opened_at: str                 # ISO JST
    max_holding_hours: int
    max_holding_deadline: str      # ISO JST
    status: str                    # "open" / "closed"
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # "TAKE_PROFIT" / "STOP_LOSS" / "TIMEOUT"
    closed_at: Optional[str] = None
    pnl_jpy: float = 0.0
    holding_hours: float = 0.0
    max_favorable_pips: float = 0.0
    max_adverse_pips: float = 0.0


def _pips(price_diff: float) -> float:
    """価格差をpipsに変換する（USD/JPY: 1 pip = 0.01）。"""
    return round(price_diff / _PIP_SIZE, 2)


def _add_hours(iso_str: str, hours: int) -> str:
    """ISOタイムスタンプに時間を加算する。"""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    result = dt + timedelta(hours=hours)
    return result.isoformat(timespec="seconds")


def load_fx_paper_trades(path: Path = DEFAULT_FX_PAPER_TRADES_PATH) -> dict:
    if not path.exists():
        return {"paper_trades": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades = payload.get("paper_trades")
    if not isinstance(trades, list):
        raise ValueError("fx_paper_trades.json の形式が不正です。")
    return {"paper_trades": trades}


def save_fx_paper_trades(payload: dict, path: Path = DEFAULT_FX_PAPER_TRADES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_fx_paper_trades(
    path: Path = DEFAULT_FX_PAPER_TRADES_PATH,
    status: Optional[str] = None,
    rule_id: Optional[str] = None,
) -> list[dict]:
    trades = load_fx_paper_trades(path)["paper_trades"]
    if status:
        trades = [t for t in trades if t.get("status") == status]
    if rule_id:
        trades = [t for t in trades if t.get("rule_id") == rule_id]
    return trades


def create_fx_paper_trades_from_proposal(
    signal_record: dict,
    proposal: Optional[dict],
    path: Path = DEFAULT_FX_PAPER_TRADES_PATH,
) -> tuple[list[dict], str]:
    """
    FX order proposal から3ルール分のペーパートレードを作成する。
    重複はスキップ（既存のpaper_trade_idがあればスキップ）。
    """
    if not proposal:
        return [], "order_proposal_not_found"
    side = proposal.get("side")
    if side not in ("BUY", "SELL"):
        return [], f"side={side} は BUY/SELL のみ対応"
    stop_loss = proposal.get("stop_loss")
    take_profit = proposal.get("take_profit")
    if stop_loss is None or take_profit is None:
        return [], "stop_loss/take_profit がないため作成できません"

    entry_price = float(proposal.get("suggested_price", 0.0))
    usd_units = float(proposal.get("suggested_size", 1000.0))
    max_loss_jpy = float(proposal.get("max_loss_jpy", 0.0))
    opened_at = signal_record.get("created_at", datetime.now(JST).isoformat(timespec="seconds"))
    proposal_id = proposal.get("proposal_id", "")
    source_signal_id = signal_record.get("signal_id", "")

    payload = load_fx_paper_trades(path)
    existing_ids = {t["paper_trade_id"] for t in payload["paper_trades"]}

    created = []
    for rule in FX_PAPER_TRADE_RULES:
        trade_id = f"fx_{proposal_id}_{rule['rule_id'].lower()}"
        if trade_id in existing_ids:
            # 既存のものを返す
            for t in payload["paper_trades"]:
                if t["paper_trade_id"] == trade_id:
                    created.append(t)
                    break
            continue
        deadline = _add_hours(opened_at, rule["max_holding_hours"])
        trade = FXPaperTrade(
            paper_trade_id=trade_id,
            source_signal_id=source_signal_id,
            source_order_proposal_id=proposal_id,
            rule_id=rule["rule_id"],
            symbol=proposal.get("symbol", "USD/JPY"),
            side=side,
            entry_price=entry_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            usd_units=usd_units,
            max_loss_jpy=max_loss_jpy,
            opened_at=opened_at,
            max_holding_hours=rule["max_holding_hours"],
            max_holding_deadline=deadline,
            status="open",
        )
        trade_dict = asdict(trade)
        payload["paper_trades"].append(trade_dict)
        existing_ids.add(trade_id)
        created.append(trade_dict)

    if created:
        save_fx_paper_trades(payload, path)

    return created, "created"


def update_open_fx_paper_trades(
    current_price: float,
    as_of_jst: str,
    path: Path = DEFAULT_FX_PAPER_TRADES_PATH,
) -> tuple[list[dict], int]:
    """
    オープンなFXペーパートレードを現在価格で更新し、
    TP/SL/TIMEOUTに達した場合はクローズする。
    更新されたトレードのリストと更新件数を返す。
    """
    payload = load_fx_paper_trades(path)
    updated = []
    changed = 0

    now = datetime.fromisoformat(as_of_jst)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)

    for trade in payload["paper_trades"]:
        if trade.get("status") != "open":
            continue

        entry = float(trade["entry_price"])
        side = trade["side"]
        units = float(trade["usd_units"])

        # P&L 計算
        if side == "BUY":
            pnl_jpy = round((current_price - entry) * units, 2)
            favorable_diff = current_price - entry
            adverse_diff = entry - current_price
        else:  # SELL
            pnl_jpy = round((entry - current_price) * units, 2)
            favorable_diff = entry - current_price
            adverse_diff = current_price - entry

        trade["pnl_jpy"] = pnl_jpy

        # holding_hours
        opened_at = datetime.fromisoformat(trade["opened_at"])
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=JST)
        holding_hours = round((now - opened_at).total_seconds() / 3600, 2)
        trade["holding_hours"] = holding_hours

        # max favorable/adverse pips 追跡
        fav_pips = _pips(max(favorable_diff, 0.0))
        adv_pips = _pips(max(adverse_diff, 0.0))
        trade["max_favorable_pips"] = round(max(float(trade.get("max_favorable_pips", 0.0)), fav_pips), 2)
        trade["max_adverse_pips"] = round(max(float(trade.get("max_adverse_pips", 0.0)), adv_pips), 2)

        # 決済判定
        tp = float(trade["take_profit"])
        sl = float(trade["stop_loss"])
        deadline = datetime.fromisoformat(trade["max_holding_deadline"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=JST)
        is_timeout = now >= deadline

        if side == "BUY":
            tp_hit = current_price >= tp
            sl_hit = current_price <= sl
        else:  # SELL
            tp_hit = current_price <= tp
            sl_hit = current_price >= sl

        if tp_hit:
            trade["status"] = "closed"
            trade["exit_price"] = round(current_price, 4)
            trade["exit_reason"] = "TAKE_PROFIT"
            trade["closed_at"] = as_of_jst
        elif sl_hit:
            trade["status"] = "closed"
            trade["exit_price"] = round(current_price, 4)
            trade["exit_reason"] = "STOP_LOSS"
            trade["closed_at"] = as_of_jst
        elif is_timeout:
            trade["status"] = "closed"
            trade["exit_price"] = round(current_price, 4)
            trade["exit_reason"] = "TIMEOUT"
            trade["closed_at"] = as_of_jst

        updated.append(trade)
        changed += 1

    if changed:
        save_fx_paper_trades(payload, path)

    return updated, changed


def summarize_fx_paper_performance(path: Path = DEFAULT_FX_PAPER_TRADES_PATH) -> list[dict]:
    """ルール別のパフォーマンスサマリーを返す。"""
    trades = load_fx_paper_trades(path)["paper_trades"]
    summaries = []
    for rule in FX_PAPER_TRADE_RULES:
        rule_id = rule["rule_id"]
        scoped = [t for t in trades if t.get("rule_id") == rule_id]
        open_trades = [t for t in scoped if t.get("status") == "open"]
        closed_trades = [t for t in scoped if t.get("status") == "closed"]
        wins = [t for t in closed_trades if float(t.get("pnl_jpy", 0.0)) > 0]
        total_pnl = round(sum(float(t.get("pnl_jpy", 0.0)) for t in closed_trades), 2)
        avg_holding = (
            round(sum(float(t.get("holding_hours", 0.0)) for t in scoped) / len(scoped), 2)
            if scoped else 0.0
        )
        summaries.append({
            "rule_id": rule_id,
            "trades": len(scoped),
            "open": len(open_trades),
            "closed": len(closed_trades),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 2) if closed_trades else 0.0,
            "total_pnl_jpy": total_pnl,
            "avg_holding_hours": avg_holding,
            "tp_count": sum(1 for t in closed_trades if t.get("exit_reason") == "TAKE_PROFIT"),
            "sl_count": sum(1 for t in closed_trades if t.get("exit_reason") == "STOP_LOSS"),
            "timeout_count": sum(1 for t in closed_trades if t.get("exit_reason") == "TIMEOUT"),
        })
    return summaries
