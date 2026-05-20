# 実注文なし・研究用レポート生成のみ
from __future__ import annotations

import logging
from pathlib import Path

from src.jp_stocks.models import JP_STOCK_CANDIDATE, JP_STOCK_WATCH, ScreeningResult

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = _PROJECT_ROOT / "reports"


def generate_report(result: ScreeningResult) -> str:
    """スクリーニング結果を Markdown 文字列として生成する。"""
    run_str = result.run_at.strftime("%Y-%m-%d %H:%M:%S JST")
    stale_label = "⚠️ stale（データが古い）" if result.is_stale else "✅ fresh"

    lines: list[str] = []

    # ユニバース情報
    universe_label = result.universe_source
    if result.market_filter != "all":
        universe_label += f" / market={result.market_filter}"
    if result.limit is not None:
        universe_label += f" / limit={result.limit}"

    # ヘッダー
    lines += [
        "# 日本株スクリーニング結果",
        "",
        f"**実行日時**: {run_str}",
        f"**データ取得元**: {result.data_source}",
        f"**データ日付**: {result.data_date or 'N/A'}",
        f"**データ状態**: {stale_label}",
        f"**ユニバース**: {universe_label}",
        "",
        "> ⛔ このレポートは研究用スクリーニングのみ。実注文・証券API発注は一切行わない。",
        "",
        "---",
        "",
        "## サマリー",
        "",
        "| 状態 | 件数 |",
        "|------|------|",
        f"| ユニバース | {result.universe_source} |",
        f"| 市場フィルター | {result.market_filter} |",
        *(
            [f"| 取得上限 | {result.limit} |"]
            if result.limit is not None else []
        ),
        f"| スクリーニング対象 | {result.total_screened} 銘柄 |",
        f"| **JP_STOCK_CANDIDATE** | **{result.candidate_count}** |",
        f"| JP_STOCK_WATCH | {result.watch_count} |",
        f"| JP_STOCK_SKIP | {result.skip_count} |",
        *(
            [f"| データ取得エラー | {len(result.errors)} |"]
            if result.errors else []
        ),
        "",
    ]

    # CANDIDATE セクション
    if result.candidate_signals:
        lines += [
            f"## JP_STOCK_CANDIDATE ({result.candidate_count} 件)",
            "",
            "| 銘柄コード | 銘柄名 | 市場 | 現在値 | 前日比 | 出来高比 | 売買代金 | セクター | 候補理由 |",
            "|-----------|--------|------|--------|--------|----------|----------|----------|----------|",
        ]
        for sig in result.candidate_signals:
            q = sig.quote
            if q:
                reason_str = " / ".join(sig.reasons)
                lines.append(
                    f"| {q.code} | {q.name} | {q.market} | "
                    f"{q.current_price:,.0f}円 | {q.gap_rate:+.1f}% | "
                    f"{q.volume_ratio:.1f}x | {q.turnover_jpy / 1e8:.1f}億 | "
                    f"{q.sector} | {reason_str} |"
                )
        lines.append("")
    else:
        lines += [
            "## JP_STOCK_CANDIDATE (0 件)",
            "",
            "本日の候補銘柄はありません。",
            "",
        ]

    # WATCH セクション
    if result.watch_signals:
        lines += [
            f"## JP_STOCK_WATCH ({result.watch_count} 件)",
            "",
            "| 銘柄コード | 銘柄名 | 市場 | 現在値 | 前日比 | 出来高比 | 売買代金 | 理由 |",
            "|-----------|--------|------|--------|--------|----------|----------|------|",
        ]
        for sig in result.watch_signals:
            q = sig.quote
            if q:
                reason_str = " / ".join(sig.reasons)
                lines.append(
                    f"| {q.code} | {q.name} | {q.market} | "
                    f"{q.current_price:,.0f}円 | {q.gap_rate:+.1f}% | "
                    f"{q.volume_ratio:.1f}x | {q.turnover_jpy / 1e8:.1f}億 | "
                    f"{reason_str} |"
                )
        lines.append("")

    # Next Action
    lines += [
        "---",
        "",
        "## Next Action",
        "",
        "| ステータス | アクション |",
        "|-----------|-----------|",
        "| JP_STOCK_SKIP | 何もしない。記録のみ。 |",
        "| JP_STOCK_WATCH | チャート確認のみ。手動売買しない。 |",
        "| JP_STOCK_CANDIDATE | **チャート・出来高・板を人間が確認する。実注文しない。** |",
        "",
    ]

    # エラーセクション
    if result.errors:
        lines += [
            f"## データ取得エラー ({len(result.errors)} 件)",
            "",
        ]
        for err in result.errors[:10]:
            lines.append(f"- `{err}`")
        if len(result.errors) > 10:
            lines.append(f"- ... 他 {len(result.errors) - 10} 件")
        lines.append("")

    return "\n".join(lines)


def save_report(result: ScreeningResult, report_text: str) -> Path:
    """レポートを reports/ ディレクトリに保存する。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = result.run_at.strftime("%Y%m%d")
    filename = f"jp_stock_screener_{date_str}.md"
    path = REPORTS_DIR / filename
    path.write_text(report_text, encoding="utf-8")
    logger.info(f"レポート保存: {path}")
    return path
