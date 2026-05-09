from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.alerts.dry_run_orders import list_dry_run_orders
from src.alerts.order_proposal import list_order_proposals
from src.fx.order_proposal import list_fx_order_proposals

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DAILY_ORDER_PROPOSAL_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


@dataclass(frozen=True)
class UnifiedProposal:
    asset: str
    side: str
    status: str
    category: str
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    max_loss_jpy: float
    rationale: list[str]
    invalidation_conditions: list[str]
    created_at: str
    source: str
    execution_state: str


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(value).astimezone(JST).date()
    except ValueError:
        return None


def _is_today(value: str, target_date: date) -> bool:
    parsed = _parse_date(value)
    return parsed == target_date


def _category(status: str, approval_confirmed: bool = False) -> str:
    normalized = status.lower()
    if normalized in {"dry_run_recorded", "manually_executed"} or approval_confirmed:
        return "approved"
    if normalized in {"rejected", "ignored", "invalid", "cancelled"}:
        return "invalid"
    if normalized in {"skip", "skipped", "watch", "buy_skip"}:
        return "skip_equivalent"
    return "unapproved"


def _execution_state(category: str, stop_trading_active: bool, source: str) -> str:
    if stop_trading_active:
        return "blocked_by_stop_trading"
    if source == "FX":
        return "proposal_only_no_adapter"
    if category == "approved":
        return "dry_run_recorded_no_exchange_order"
    if category == "unapproved":
        return "requires_manual_confirmation"
    return "not_executable"


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]


def collect_daily_order_proposals(
    *,
    target_date: date,
    dry_run_orders_path: Path,
    btc_order_proposals_path: Path,
    fx_order_proposals_path: Path,
    stop_trading_active: bool,
) -> list[UnifiedProposal]:
    btc_proposals = {
        proposal.get("proposal_id"): proposal
        for proposal in list_order_proposals(btc_order_proposals_path)
    }
    unified: list[UnifiedProposal] = []

    for order in list_dry_run_orders(dry_run_orders_path):
        if not _is_today(str(order.get("created_at", "")), target_date):
            continue
        source_proposal = btc_proposals.get(order.get("source_order_proposal_id"), {})
        status = str(order.get("status", ""))
        category = _category(status, bool(order.get("approval_phrase_confirmed")))
        unified.append(
            UnifiedProposal(
                asset=str(order.get("symbol", "BTC_JPY")),
                side=str(order.get("side", "")),
                status=status,
                category=category,
                entry_price=float(order["price"]) if order.get("price") is not None else None,
                stop_loss=_optional_float(source_proposal.get("stop_loss")),
                take_profit=_optional_float(source_proposal.get("take_profit")),
                max_loss_jpy=_optional_float(source_proposal.get("max_loss_jpy")) or 0.0,
                rationale=_as_list(source_proposal.get("rationale") or order.get("reason")),
                invalidation_conditions=_as_list(source_proposal.get("invalidation_conditions")),
                created_at=str(order.get("created_at", "")),
                source="BTC",
                execution_state=_execution_state(category, stop_trading_active, "BTC"),
            )
        )

    for proposal in list_fx_order_proposals(fx_order_proposals_path):
        if not _is_today(str(proposal.get("created_at", "")), target_date):
            continue
        status = str(proposal.get("status", ""))
        category = _category(status, False)
        unified.append(
            UnifiedProposal(
                asset=str(proposal.get("symbol", "USD/JPY")),
                side=str(proposal.get("side", "")),
                status=status,
                category=category,
                entry_price=_optional_float(proposal.get("suggested_price")),
                stop_loss=_optional_float(proposal.get("stop_loss")),
                take_profit=_optional_float(proposal.get("take_profit")),
                max_loss_jpy=_optional_float(proposal.get("max_loss_jpy")) or 0.0,
                rationale=_as_list(proposal.get("rationale")),
                invalidation_conditions=_as_list(proposal.get("invalidation_conditions")),
                created_at=str(proposal.get("created_at", "")),
                source="FX",
                execution_state=_execution_state(category, stop_trading_active, "FX"),
            )
        )

    return sorted(unified, key=lambda proposal: proposal.created_at)


def _optional_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def render_daily_order_proposal_report(
    proposals: list[UnifiedProposal],
    *,
    target_date: date,
    generated_at: datetime,
    stop_trading_active: bool,
) -> str:
    total_max_loss = round(sum(proposal.max_loss_jpy for proposal in proposals), 2)
    by_category = {
        "unapproved": [p for p in proposals if p.category == "unapproved"],
        "approved": [p for p in proposals if p.category == "approved"],
        "invalid": [p for p in proposals if p.category == "invalid"],
        "skip_equivalent": [p for p in proposals if p.category == "skip_equivalent"],
    }

    lines = [
        f"# Daily Order Proposals {target_date.strftime('%Y-%m-%d')}",
        "",
        f"- Generated at: {generated_at.astimezone(JST).isoformat()}",
        "- Scope: BTC DRY_RUN orders and FX USD/JPY order proposals",
        "- Real order APIs are not used by this report",
        f"- STOP_TRADING: {'active - all proposals are execution prohibited' if stop_trading_active else 'inactive'}",
        f"- Total max_loss_jpy: {total_max_loss:,.2f}",
        "",
    ]

    for category, title in [
        ("unapproved", "未承認"),
        ("approved", "承認済み"),
        ("invalid", "無効"),
        ("skip_equivalent", "SKIP相当"),
    ]:
        items = by_category[category]
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["- none", ""])
            continue
        for proposal in items:
            lines.extend(_render_proposal(proposal))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_proposal(proposal: UnifiedProposal) -> list[str]:
    return [
        f"### {proposal.source} {proposal.asset} {proposal.side}",
        "",
        f"- status: {proposal.status}",
        f"- execution_state: {proposal.execution_state}",
        f"- entry_price: {_fmt_price(proposal.entry_price)}",
        f"- stop_loss: {_fmt_price(proposal.stop_loss)}",
        f"- take_profit: {_fmt_price(proposal.take_profit)}",
        f"- max_loss_jpy: {proposal.max_loss_jpy:,.2f}",
        f"- created_at: {proposal.created_at}",
        "- rationale:",
        *[f"  - {item}" for item in (proposal.rationale or ["none"])],
        "- invalidation_conditions:",
        *[f"  - {item}" for item in (proposal.invalidation_conditions or ["none"])],
    ]


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.4f}" if value < 10_000 else f"{value:,.0f}"


def save_daily_order_proposal_report(
    content: str,
    *,
    target_date: date,
    reports_dir: Path = DEFAULT_DAILY_ORDER_PROPOSAL_REPORTS_DIR,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"daily_order_proposals_{target_date.strftime('%Y%m%d')}.md"
    path.write_text(content, encoding="utf-8")
    return path
