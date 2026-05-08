#!/usr/bin/env python
# =============================================================================
# 実注文なし・研究用シグナルのみ
# FXSignalStorage から最新20件のシグナルをコンソールに表示する。
# =============================================================================

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fx.storage import FXSignalStorage
from src.utils.logger import get_logger

log = get_logger("list_fx_signals")


def main() -> None:
    storage = FXSignalStorage()
    signals = storage.get_latest(n=20)

    if not signals:
        print("シグナルがありません。run_fx_usdjpy_signal.py を実行してください。")
        return

    print("=" * 90)
    print("FX USD/JPY シグナル一覧（最新20件）  ※実注文なし・研究用")
    print("=" * 90)
    header = (
        f"{'timestamp':<28} | {'action':<5} | {'price':>8} | "
        f"{'spread':>6} | {'SL':>8} | {'TP':>8} | reasons"
    )
    print(header)
    print("-" * 90)
    for s in signals:
        sl_str = f"{s.stop_loss:.3f}" if s.stop_loss is not None else "  -   "
        tp_str = f"{s.take_profit:.3f}" if s.take_profit is not None else "  -   "
        reasons_short = "; ".join(s.reasons[:2])
        if len(s.reasons) > 2:
            reasons_short += f" (+{len(s.reasons)-2})"
        print(
            f"{s.timestamp[:28]:<28} | {s.action:<5} | {s.price:>8.4f} | "
            f"{s.spread_pips:>5.2f}p | {sl_str:>8} | {tp_str:>8} | {reasons_short}"
        )
    print("=" * 90)
    print(f"合計 {len(signals)} 件")


if __name__ == "__main__":
    main()
