from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional


DEFAULT_MANUAL_POSITIONS_PATH = Path(__file__).resolve().parents[2] / "state" / "manual_positions.json"


@dataclass
class ManualPosition:
    id: str
    symbol: str
    entry_date: str
    entry_price: float
    position_size: float
    note: str
    status: str
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    realized_pnl_pct: Optional[float] = None
    realized_pnl_jpy: Optional[float] = None


def _empty_payload() -> dict:
    return {"positions": []}


def load_manual_positions(path: Path = DEFAULT_MANUAL_POSITIONS_PATH) -> dict:
    if not path.exists():
        return _empty_payload()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "positions" not in payload or not isinstance(payload["positions"], list):
        return _empty_payload()
    return payload


def save_manual_positions(payload: dict, path: Path = DEFAULT_MANUAL_POSITIONS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _symbol_id_prefix(symbol: str) -> str:
    prefix = symbol.lower().split("_", 1)[0]
    return prefix or "position"


def _next_position_id(symbol: str, entry_date: str, positions: list[dict]) -> str:
    stamp = entry_date.replace("-", "")
    prefix = _symbol_id_prefix(symbol)
    existing = [p for p in positions if p.get("id", "").startswith(f"{prefix}_{stamp}_")]
    seq = len(existing) + 1
    return f"{prefix}_{stamp}_{seq:03d}"


def add_manual_position(
    symbol: str,
    entry_price: float,
    entry_date: str,
    position_size: float,
    note: str,
    path: Path = DEFAULT_MANUAL_POSITIONS_PATH,
) -> dict:
    payload = load_manual_positions(path)
    position = ManualPosition(
        id=_next_position_id(symbol, entry_date, payload["positions"]),
        symbol=symbol,
        entry_date=entry_date,
        entry_price=float(entry_price),
        position_size=float(position_size),
        note=note,
        status="open",
    )
    payload["positions"].append(asdict(position))
    save_manual_positions(payload, path)
    return asdict(position)


def list_manual_positions(path: Path = DEFAULT_MANUAL_POSITIONS_PATH) -> list[dict]:
    return load_manual_positions(path)["positions"]


def close_manual_position(
    position_id: str,
    exit_price: float,
    exit_date: str,
    reason: str,
    path: Path = DEFAULT_MANUAL_POSITIONS_PATH,
) -> dict:
    payload = load_manual_positions(path)
    for position in payload["positions"]:
        if position["id"] != position_id:
            continue
        if position.get("status") != "open":
            raise ValueError(f"position is already closed: {position_id}")
        entry_price = float(position["entry_price"])
        size = float(position["position_size"])
        pnl_pct = (float(exit_price) / entry_price - 1) * 100
        pnl_jpy = (float(exit_price) - entry_price) * size
        position["exit_price"] = float(exit_price)
        position["exit_date"] = exit_date
        position["exit_reason"] = reason
        position["realized_pnl_pct"] = round(pnl_pct, 2)
        position["realized_pnl_jpy"] = round(pnl_jpy, 2)
        position["status"] = "closed"
        save_manual_positions(payload, path)
        return position
    raise ValueError(f"position not found: {position_id}")


def select_active_position(
    symbol: str,
    path: Path = DEFAULT_MANUAL_POSITIONS_PATH,
) -> tuple[Optional[dict], list[str], list[dict]]:
    positions = list_manual_positions(path)
    open_positions = [
        position for position in positions
        if position.get("symbol") == symbol and position.get("status") == "open"
    ]
    warnings: list[str] = []
    if not open_positions:
        return None, warnings, positions
    open_positions.sort(key=lambda p: (p.get("entry_date", ""), p.get("id", "")))
    selected = open_positions[-1]
    if len(open_positions) > 1:
        warnings.append(
            f"{symbol} の open position が {len(open_positions)} 件あります。最新の {selected['id']} を判定対象にしました。"
        )
    return selected, warnings, positions


def parse_position_input(position: dict):
    from src.alerts.btc_dip_alert import PositionInput

    return PositionInput(
        entry_price=float(position["entry_price"]),
        entry_date=date.fromisoformat(position["entry_date"]),
        position_size=float(position["position_size"]),
        position_id=position.get("id"),
        note=position.get("note"),
    )
