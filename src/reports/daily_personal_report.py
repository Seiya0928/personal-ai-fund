# BTC・FX統合デイリーレポート。実注文APIは呼ばない。
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.fx.strategy_candidate import WatchSignal
from src.proposals.common_proposal import CommonOrderProposal

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DAILY_PERSONAL_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _fmt_price(value: Optional[float], instrument: str) -> str:
    if value is None:
        return "n/a"
    if instrument == "BTC_JPY":
        return f"¥{value:,.0f}"
    return f"{value:.4f}"


def _fmt_rr(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _fmt_jpy(value: float) -> str:
    return f"¥{value:,.0f}"


def _safety_flags_section(
    stop_trading_active: bool,
    dry_run: bool,
    read_only: bool,
) -> list[str]:
    stop = "🛑 ACTIVE — 全提案が実行禁止" if stop_trading_active else "inactive"
    dr = "true" if dry_run else "false"
    ro = "true" if read_only else "false"
    return [
        "## 安全フラグ（グローバル）",
        "",
        f"| フラグ | 状態 |",
        f"|--------|------|",
        f"| STOP_TRADING | {stop} |",
        f"| DRY_RUN | {dr} |",
        f"| READ_ONLY | {ro} |",
        "",
    ]


def _proposal_table_rows(proposals: list[CommonOrderProposal]) -> list[str]:
    if not proposals:
        return ["- none", ""]
    header = "| # | 資産 | 銘柄 | side | status | risk_jpy | expected_rr | confidence | created_at |"
    sep    = "|---|------|------|------|--------|----------|-------------|------------|------------|"
    rows = [header, sep]
    for i, p in enumerate(proposals, 1):
        conf = f"{p.confidence:.2f}" if p.confidence is not None else "n/a"
        rows.append(
            f"| {i} | {p.asset_class} | {p.instrument} | {p.side} | {p.status}"
            f" | {_fmt_jpy(p.risk_jpy)} | {_fmt_rr(p.expected_rr)} | {conf} | {p.created_at[:19]} |"
        )
    return rows + [""]


def _proposal_detail(p: CommonOrderProposal, index: int) -> list[str]:
    meta = p.metadata
    entry = meta.get("suggested_price")
    sl = meta.get("stop_loss")
    tp = meta.get("take_profit")
    rationale = meta.get("rationale") or []
    invalidation = meta.get("invalidation_conditions") or []
    lines = [
        f"### {index}. [{p.asset_class.upper()}] {p.instrument} {p.side.upper()} — {p.proposal_id}",
        "",
        f"- strategy: {p.strategy_name}",
        f"- status: {p.status}",
        f"- side: {p.side}",
        f"- entry: {_fmt_price(entry, p.instrument)}",
        f"- stop_loss: {_fmt_price(sl, p.instrument)}",
        f"- take_profit: {_fmt_price(tp, p.instrument)}",
        f"- max_loss_jpy: {_fmt_jpy(p.max_loss_jpy)}",
        f"- expected_rr: {_fmt_rr(p.expected_rr)}",
        f"- confidence: {f'{p.confidence:.2f}' if p.confidence is not None else 'n/a'}",
        f"- expires_at: {p.expires_at or 'n/a'}",
        f"- reason: {p.reason}",
    ]
    if rationale:
        lines += ["- rationale:", *[f"  - {item}" for item in rationale]]
    if invalidation:
        lines += ["- invalidation_conditions:", *[f"  - {item}" for item in invalidation]]
    lines.append("")
    return lines


def _fmt_pips(value: Optional[float]) -> str:
    return f"{value:.1f}pips" if value is not None else "n/a"


def _watch_signal_section(
    watch_signals: list[WatchSignal],
    unresolved_count: int = 0,
    eval_stats: Optional[dict] = None,
) -> list[str]:
    """
    FX Watch Candidate セクション。
    Action Required ではなく観察目的のみ。注文提案には昇格しない。
    """
    lines = ["## FX Watch Candidate（観察専用・Action Required ではない）", ""]
    lines += [f"- 未解決シグナル: {unresolved_count} 件", ""]

    if eval_stats:
        win_rate = eval_stats.get("win_rate")
        win_rate_str = f"{win_rate * 100:.1f}%" if win_rate is not None else "n/a"
        lines += [
            "### 直近評価サマリー",
            "",
            "| tp_hit | sl_hit | timeout | ambiguous | open | win_rate |",
            "|--------|--------|---------|-----------|------|----------|",
            (
                f"| {eval_stats.get('tp_hit', 0)}"
                f" | {eval_stats.get('sl_hit', 0)}"
                f" | {eval_stats.get('timeout', 0)}"
                f" | {eval_stats.get('ambiguous', 0)}"
                f" | {eval_stats.get('open', 0)}"
                f" | {win_rate_str} |"
            ),
            "",
        ]

    if not watch_signals:
        lines += ["- none", ""]
        return lines
    for sig in watch_signals:
        action_label = sig.action.upper()
        lines += [
            f"### {sig.strategy_name}",
            "",
            f"- **action**: {action_label}",
            f"- current_price: {sig.current_price:.4f}",
            f"- trend_direction: {sig.trend_direction}",
            f"- breakout_level: {f'{sig.breakout_level:.4f}' if sig.breakout_level is not None else 'n/a'}",
            f"- stop_loss: {f'{sig.stop_loss:.4f}' if sig.stop_loss is not None else 'n/a'}",
            f"- take_profit: {f'{sig.take_profit:.4f}' if sig.take_profit is not None else 'n/a'}",
            f"- risk_pips: {_fmt_pips(sig.risk_pips)}",
            f"- reward_pips: {_fmt_pips(sig.reward_pips)}",
            f"- rr_ratio: {_fmt_rr(sig.rr_ratio)}",
            f"- reason: {sig.reason}",
            f"- data_timestamp: {sig.data_timestamp}",
            f"- created_at: {sig.created_at}",
            "- **注意**: 実注文・OrderProposal・DRY_RUN注文には昇格しない",
            "",
        ]
    return lines


def render_daily_personal_report(
    proposals: list[CommonOrderProposal],
    *,
    target_date: date,
    generated_at: datetime,
    stop_trading_active: bool,
    dry_run: bool,
    read_only: bool,
    watch_signals: Optional[list[WatchSignal]] = None,
    watch_unresolved_count: int = 0,
    watch_eval_stats: Optional[dict] = None,
) -> str:
    """
    BTC・FX統合デイリーレポートをMarkdown文字列で返す。
    実注文APIは呼ばない。proposals はアダプタ変換済みのCommonOrderProposalリスト。
    watch_signals は watch_candidate のシグナル（観察専用・Action Required ではない）。
    """
    total_risk = round(sum(p.risk_jpy for p in proposals), 2)
    by_status = {s: [p for p in proposals if p.status == s] for s in ("proposed", "approved", "dry_run_recorded", "rejected", "expired")}

    lines: list[str] = [
        f"# Daily Personal Report {target_date.strftime('%Y-%m-%d')}",
        "",
        f"- 生成日時: {generated_at.astimezone(JST).isoformat()}",
        "- 実注文APIは使用していません（研究・提案のみ）",
        f"- 対象: BTC_JPY / USD_JPY 注文提案",
        f"- 提案件数: {len(proposals)} 件",
        f"- 合計 risk_jpy: {_fmt_jpy(total_risk)}",
        "",
    ]

    lines += _safety_flags_section(stop_trading_active, dry_run, read_only)

    # FX Watch Candidate（観察専用）
    lines += _watch_signal_section(
        watch_signals or [],
        unresolved_count=watch_unresolved_count,
        eval_stats=watch_eval_stats,
    )

    lines += ["## 提案サマリー（全資産クラス）", ""]
    lines += _proposal_table_rows(proposals)

    for status_label, status_key in [
        ("未承認 (proposed)", "proposed"),
        ("承認済み (approved)", "approved"),
        ("DRY_RUN記録済み", "dry_run_recorded"),
        ("棄却 (rejected)", "rejected"),
        ("期限切れ (expired)", "expired"),
    ]:
        items = by_status[status_key]
        lines += [f"## {status_label}", ""]
        if not items:
            lines += ["- none", ""]
            continue
        for i, p in enumerate(items, 1):
            lines += _proposal_detail(p, i)

    return "\n".join(lines).rstrip() + "\n"


def save_daily_personal_report(
    content: str,
    *,
    target_date: date,
    reports_dir: Path = DEFAULT_DAILY_PERSONAL_REPORTS_DIR,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"daily_personal_report_{target_date.strftime('%Y%m%d')}.md"
    path.write_text(content, encoding="utf-8")
    return path
