from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Optional, Protocol

from src.risk.kill_switch import KillSwitch

DEFAULT_STOP_TRADING_FILE = Path(__file__).resolve().parents[2] / "STOP_TRADING"


class DuplicateGuard(Protocol):
    def is_duplicate(self, symbol: str, side: str, order_type: str, amount_jpy: float) -> bool:
        ...


@dataclass(frozen=True)
class GateCheckResult:
    ok: bool
    checked: tuple[str, ...]


def require_approval_phrase(typed_phrase: str, expected_phrase: str) -> None:
    if typed_phrase != expected_phrase:
        raise ValueError("approval phrase mismatch")


def _require_present(proposal: Mapping[str, object], key: str) -> None:
    value = proposal.get(key)
    if value is None or value == "" or value == []:
        raise ValueError(f"{key} is required")


def validate_manual_execution_proposal(
    proposal: Mapping[str, object],
    *,
    dry_run: bool,
    read_only: bool,
    require_dry_run: bool = True,
    require_read_only: bool = True,
    stop_trading_file: Path = DEFAULT_STOP_TRADING_FILE,
    duplicate_guard: Optional[DuplicateGuard] = None,
) -> GateCheckResult:
    """
    Common pre-execution gate for manual BTC/FX proposal flows.

    This module only validates proposal safety. It never submits orders.
    """
    checked: list[str] = []

    if require_dry_run and not dry_run:
        raise ValueError("DRY_RUN must be true")
    checked.append("dry_run")

    if require_read_only and not read_only:
        raise ValueError("READ_ONLY must be true")
    checked.append("read_only")

    if KillSwitch(stop_trading_file).is_active():
        raise ValueError("kill switch is active")
    checked.append("kill_switch")

    if proposal.get("status") != "proposed":
        raise ValueError("proposal.status must be proposed")
    checked.append("status")

    if proposal.get("send_to_exchange") is not False:
        raise ValueError("proposal.send_to_exchange must be false")
    checked.append("send_to_exchange")

    if proposal.get("requires_manual_confirmation") is not True:
        raise ValueError("proposal.requires_manual_confirmation must be true")
    checked.append("manual_confirmation")

    if proposal.get("side") not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    checked.append("side")

    if proposal.get("execution_type") != "LIMIT":
        raise ValueError("execution_type must be LIMIT")
    checked.append("execution_type")

    for key in ("stop_loss", "take_profit", "max_loss_jpy", "rationale", "invalidation_conditions"):
        _require_present(proposal, key)
    checked.append("proposal_risk_fields")

    if duplicate_guard is not None:
        amount = float(proposal.get("estimated_jpy", 0.0) or 0.0)
        if duplicate_guard.is_duplicate(
            str(proposal.get("symbol")),
            str(proposal.get("side")),
            str(proposal.get("execution_type")),
            amount,
        ):
            raise ValueError("duplicate proposal is blocked")
        checked.append("duplicate_guard")

    return GateCheckResult(ok=True, checked=tuple(checked))


def validate_limit_order_shape(
    *,
    order_body: Mapping[str, object],
    expected_exchange_symbol: str,
    minimum_size: Decimal,
) -> GateCheckResult:
    if order_body.get("symbol") != expected_exchange_symbol:
        raise ValueError("order_body.symbol must match proposal exchange symbol")
    if "_" in str(order_body.get("symbol", "")):
        raise ValueError("order_body.symbol must be an exchange spot symbol")
    if order_body.get("side") not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if order_body.get("executionType") != "LIMIT":
        raise ValueError("execution_type must be LIMIT")

    size = Decimal(str(order_body.get("size", "0")))
    if size < minimum_size:
        raise ValueError("size must be minimum quantity or larger")

    price = Decimal(str(order_body.get("price", "0")))
    if price <= 0 or price != price.to_integral_value():
        raise ValueError("price must be a positive integer JPY value")

    return GateCheckResult(
        ok=True,
        checked=("exchange_symbol", "side", "execution_type", "minimum_size", "integer_price"),
    )
