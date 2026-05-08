# 実注文なし・研究用シグナルのみ
# このモジュールは実注文APIを一切呼びません。

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.fx.models import FXSignal
from src.utils.logger import get_logger

log = get_logger(__name__)

JST = ZoneInfo("Asia/Tokyo")

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


class FXReporter:
    """
    FXシグナルのレポート生成（研究用・実注文なし）
    """

    def generate_summary(self, signals: list[FXSignal]) -> str:
        """テキスト形式のレポートを生成する"""
        lines = []
        lines.append("=" * 60)
        lines.append("FX USD/JPY シグナル検証レポート（研究用・実注文なし）")
        lines.append("=" * 60)
        lines.append(f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
        lines.append(f"総シグナル数: {len(signals)}")
        lines.append("")

        # 集計
        action_counts = Counter(s.action for s in signals)
        lines.append("--- アクション集計 ---")
        for action in ("BUY", "SELL", "WATCH", "SKIP"):
            lines.append(f"  {action}: {action_counts.get(action, 0)}件")
        lines.append("")

        # スプレッド平均
        spread_values = [s.spread_pips for s in signals if s.action != "SKIP"]
        if spread_values:
            avg_spread = sum(spread_values) / len(spread_values)
            lines.append(f"スプレッド平均 (SKIP除く): {avg_spread:.3f} pips")
            lines.append("")

        # SKIPの主な理由
        skip_signals = [s for s in signals if s.action == "SKIP" and s.skip_reason]
        if skip_signals:
            lines.append("--- SKIPの主な理由 ---")
            skip_reasons = Counter(s.skip_reason for s in skip_signals)
            for reason, count in skip_reasons.most_common(5):
                # 理由が長い場合は省略
                short = reason[:60] + "..." if len(reason) > 60 else reason
                lines.append(f"  [{count}件] {short}")
            lines.append("")

        # 最新10件のシグナル一覧
        recent = signals[:10]
        lines.append("--- 最新10件のシグナル ---")
        if not recent:
            lines.append("  (データなし)")
        else:
            header = f"{'timestamp':<26} | {'action':<5} | {'price':>8} | {'spread':>6} | {'SL':>8} | {'TP':>8}"
            lines.append(header)
            lines.append("-" * len(header))
            for s in recent:
                sl_str = f"{s.stop_loss:.3f}" if s.stop_loss is not None else "  -   "
                tp_str = f"{s.take_profit:.3f}" if s.take_profit is not None else "  -   "
                lines.append(
                    f"{s.timestamp[:26]:<26} | {s.action:<5} | {s.price:>8.4f} | "
                    f"{s.spread_pips:>5.2f}p | {sl_str:>8} | {tp_str:>8}"
                )
        lines.append("")
        lines.append("=" * 60)
        lines.append("※ このレポートは研究用です。実注文は行いません。")
        lines.append("=" * 60)
        return "\n".join(lines)

    def save_report(
        self, content: str, path: Path | None = None
    ) -> Path:
        """
        レポートを保存する。
        path が None の場合は reports/fx_usdjpy_YYYYMMDD.txt に保存する。
        """
        if path is None:
            today = datetime.now(JST).strftime("%Y%m%d")
            path = REPORTS_DIR / f"fx_usdjpy_{today}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log.info(f"FXレポート保存: {path}")
        return path
