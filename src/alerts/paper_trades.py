from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Optional

from src.risk.order_sizing import BTC_JPY_MIN_QUANTITY, BTC_JPY_QUANTITY_STEP

DEFAULT_PAPER_TRADES_PATH = Path(__file__).resolve().parents[2] / "state" / "paper_trades.json"
PAPER_TRADE_RULES = (
    {"rule_id": "Conservative", "take_profit_pct": 5.0, "stop_loss_pct": -7.5, "max_holding_days": 30},
    {"rule_id": "Current", "take_profit_pct": 10.0, "stop_loss_pct": -12.5, "max_holding_days": 90},
    {"rule_id": "Wide", "take_profit_pct": 15.0, "stop_loss_pct": -15.0, "max_holding_days": 180},
)


@dataclass
class PaperTrade:
    paper_trade_id: str
    source_signal_id: str
    source_order_proposal_id: str
    rule_id: str
    symbol: str
    entry_date: str
    entry_price: float
    size: float
    notional_jpy: float
    take_profit_pct: float
    stop_loss_pct: float
    max_holding_days: int
    take_profit_line: float
    stop_loss_line: float
    max_holding_deadline: str
    status: str
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: float = 0.0
    pnl_jpy: float = 0.0
    max_unrealized_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    holding_days: int = 0


def _floor_quantity(quantity: float) -> float:
    raw = Decimal(str(quantity))
    floored = (raw / BTC_JPY_QUANTITY_STEP).to_integral_value(rounding=ROUND_DOWN) * BTC_JPY_QUANTITY_STEP
    return float(floored)


def load_paper_trades(path: Path = DEFAULT_PAPER_TRADES_PATH) -> dict:
    if not path.exists():
        return {"paper_trades": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades = payload.get("paper_trades")
    if not isinstance(trades, list):
        raise ValueError("paper_trades.json の形式が不正です。")
    return {"paper_trades": trades}


def save_paper_trades(payload: dict, path: Path = DEFAULT_PAPER_TRADES_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_paper_trades(path: Path = DEFAULT_PAPER_TRADES_PATH, status: Optional[str] = None, rule_id: Optional[str] = None) -> list[dict]:
    trades = load_paper_trades(path)["paper_trades"]
    if status:
        trades = [trade for trade in trades if trade.get("status") == status]
    if rule_id:
        trades = [trade for trade in trades if trade.get("rule_id") == rule_id]
    return trades


def _build_trade_id(symbol: str, order_proposal_id: str, rule_id: str) -> str:
    return f"{symbol.lower()}_{order_proposal_id}_{rule_id.lower()}"


def create_paper_trades_from_buy_proposal(signal_record: dict, proposal: Optional[dict]) -> tuple[list[dict], str]:
    if not proposal:
        return [], "order_proposal_not_found"
    if proposal.get("side") != "BUY":
        return [], "buy_order_proposal_only"
    size = _floor_quantity(float(proposal.get("suggested_size", 0.0)))
    if size < float(BTC_JPY_MIN_QUANTITY):
        return [], "proposal_size_below_minimum"
    entry_date = signal_record["created_at"][:10]
    entry_price = float(proposal["suggested_price"])
    created = []
    for rule in PAPER_TRADE_RULES:
        deadline = date.fromisoformat(entry_date).fromordinal(
            date.fromisoformat(entry_date).toordinal() + int(rule["max_holding_days"])
        )
        trade = PaperTrade(
            paper_trade_id=_build_trade_id(signal_record["symbol"], proposal["proposal_id"], rule["rule_id"]),
            source_signal_id=signal_record["signal_id"],
            source_order_proposal_id=proposal["proposal_id"],
            rule_id=rule["rule_id"],
            symbol=signal_record["symbol"],
            entry_date=entry_date,
            entry_price=entry_price,
            size=size,
            notional_jpy=round(entry_price * size, 2),
            take_profit_pct=float(rule["take_profit_pct"]),
            stop_loss_pct=float(rule["stop_loss_pct"]),
            max_holding_days=int(rule["max_holding_days"]),
            take_profit_line=round(entry_price * (1 + float(rule["take_profit_pct"]) / 100), 0),
            stop_loss_line=round(entry_price * (1 + float(rule["stop_loss_pct"]) / 100), 0),
            max_holding_deadline=deadline.isoformat(),
            status="open",
        )
        created.append(asdict(trade))
    return created, "created"


def save_paper_trade_records(records: list[dict], path: Path = DEFAULT_PAPER_TRADES_PATH) -> tuple[list[dict], int]:
    payload = load_paper_trades(path)
    saved_records = []
    saved_count = 0
    existing_by_id = {trade["paper_trade_id"]: trade for trade in payload["paper_trades"]}
    for record in records:
        existing = existing_by_id.get(record["paper_trade_id"])
        if existing is not None:
            saved_records.append(existing)
            continue
        payload["paper_trades"].append(record)
        existing_by_id[record["paper_trade_id"]] = record
        saved_records.append(record)
        saved_count += 1
    if saved_count:
        save_paper_trades(payload, path)
    return saved_records, saved_count


def update_open_paper_trades(current_price: float, as_of_jst: str, path: Path = DEFAULT_PAPER_TRADES_PATH) -> tuple[list[dict], int]:
    payload = load_paper_trades(path)
    updated = []
    changed = 0
    as_of_date = datetime.fromisoformat(as_of_jst).date()
    for trade in payload["paper_trades"]:
        if trade.get("status") != "open":
            continue
        entry_date = date.fromisoformat(trade["entry_date"])
        holding_days = (as_of_date - entry_date).days
        pnl_pct = ((current_price / float(trade["entry_price"])) - 1) * 100
        pnl_jpy = (current_price - float(trade["entry_price"])) * float(trade["size"])
        trade["pnl_pct"] = round(pnl_pct, 2)
        trade["pnl_jpy"] = round(pnl_jpy, 2)
        trade["holding_days"] = holding_days
        trade["max_unrealized_pnl_pct"] = round(max(float(trade.get("max_unrealized_pnl_pct", 0.0)), pnl_pct), 2)
        trade["max_drawdown_pct"] = round(max(float(trade.get("max_drawdown_pct", 0.0)), max(0.0, -pnl_pct)), 2)
        if current_price >= float(trade["take_profit_line"]):
            trade["status"] = "closed"
            trade["exit_date"] = as_of_date.isoformat()
            trade["exit_price"] = round(current_price, 0)
            trade["exit_reason"] = "TAKE_PROFIT"
        elif current_price <= float(trade["stop_loss_line"]):
            trade["status"] = "closed"
            trade["exit_date"] = as_of_date.isoformat()
            trade["exit_price"] = round(current_price, 0)
            trade["exit_reason"] = "STOP_LOSS"
        elif holding_days >= int(trade["max_holding_days"]):
            trade["status"] = "closed"
            trade["exit_date"] = as_of_date.isoformat()
            trade["exit_price"] = round(current_price, 0)
            trade["exit_reason"] = "TIMEOUT"
        updated.append(trade)
        changed += 1
    if changed:
        save_paper_trades(payload, path)
    return updated, changed


def summarize_paper_performance(path: Path = DEFAULT_PAPER_TRADES_PATH) -> list[dict]:
    trades = load_paper_trades(path)["paper_trades"]
    summaries = []
    for rule in PAPER_TRADE_RULES:
        rule_id = rule["rule_id"]
        scoped = [trade for trade in trades if trade.get("rule_id") == rule_id]
        open_trades = [trade for trade in scoped if trade.get("status") == "open"]
        closed_trades = [trade for trade in scoped if trade.get("status") == "closed"]
        wins = [trade for trade in closed_trades if float(trade.get("pnl_jpy", 0.0)) > 0]
        avg_pnl_pct = sum(float(trade.get("pnl_pct", 0.0)) for trade in closed_trades) / len(closed_trades) if closed_trades else 0.0
        avg_holding_days = sum(int(trade.get("holding_days", 0)) for trade in scoped) / len(scoped) if scoped else 0.0
        summaries.append(
            {
                "rule_id": rule_id,
                "trades": len(scoped),
                "open": len(open_trades),
                "closed": len(closed_trades),
                "win_rate": round((len(wins) / len(closed_trades) * 100), 2) if closed_trades else 0.0,
                "total_pnl_jpy": round(sum(float(trade.get("pnl_jpy", 0.0)) for trade in closed_trades), 2),
                "avg_pnl_pct": round(avg_pnl_pct, 2),
                "max_drawdown_pct": round(max((float(trade.get("max_drawdown_pct", 0.0)) for trade in scoped), default=0.0), 2),
                "avg_holding_days": round(avg_holding_days, 1),
                "take_profit_count": sum(1 for trade in closed_trades if trade.get("exit_reason") == "TAKE_PROFIT"),
                "stop_loss_count": sum(1 for trade in closed_trades if trade.get("exit_reason") == "STOP_LOSS"),
                "timeout_count": sum(1 for trade in closed_trades if trade.get("exit_reason") == "TIMEOUT"),
            }
        )
    return summaries
