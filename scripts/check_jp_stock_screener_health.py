#!/usr/bin/env python3
"""日本株スクリーニング bot のヘルスチェック。

実行方法:
    ./venv/bin/python scripts/check_jp_stock_screener_health.py

終了コード:
    0 : OK または WARNING（監視システムとしては動作中）
    1 : NG（重大な問題）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.jp_stocks.health import check_health, render_health
from src.jp_stocks.signal_history import get_last_entry


def main() -> None:
    result = check_health()
    print(render_health(result))

    last = get_last_entry()
    if last and last.get("candidates"):
        print("")
        print("  最終 CANDIDATE 銘柄:")
        for c in last["candidates"]:
            change = c.get("change_pct", 0)
            vol = c.get("volume_ratio", 0)
            reasons = " / ".join(c.get("reasons", []))
            print(f"    {c['code']} {c['name']}  {change:+.1f}% / 出来高比 {vol:.1f}x")
            if reasons:
                print(f"      → {reasons}")

    if last and last.get("watches"):
        print("")
        print("  最終 WATCH 銘柄:")
        for w in last["watches"][:5]:
            print(f"    {w['code']} {w['name']}")

    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
