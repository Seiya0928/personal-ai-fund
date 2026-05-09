#!/usr/bin/env python
"""
FX dry-run注文を手動で記録するCLIツール。
実注文なし・研究用のみ。

使用方法:
    python scripts/record_fx_dry_run_order.py --proposal-id PROPOSAL_ID
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.fx.order_proposal import load_fx_order_proposals, DEFAULT_FX_ORDER_PROPOSALS_PATH
from src.fx.fx_dry_run_recorder import (
    record_fx_dry_run_order,
    DRY_RUN_APPROVAL_PHRASE,
    DEFAULT_FX_DRY_RUN_ORDERS_PATH,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="FX dry-run注文記録CLIツール（実注文なし）")
    parser.add_argument("--proposal-id", required=True, help="記録対象のFX order proposal ID")
    args = parser.parse_args()

    proposal_id = args.proposal_id

    # proposal を検索
    try:
        proposals = load_fx_order_proposals(DEFAULT_FX_ORDER_PROPOSALS_PATH)["proposals"]
    except Exception as e:
        print(f"[ERROR] FX order proposals 読み込みエラー: {e}")
        sys.exit(1)

    proposal = next((p for p in proposals if p.get("proposal_id") == proposal_id), None)
    if not proposal:
        print(f"[ERROR] proposal_id '{proposal_id}' が見つかりません。")
        print(f"利用可能な proposal_id: {[p.get('proposal_id') for p in proposals]}")
        sys.exit(1)

    # 内容表示
    print(f"\n[FX Dry-Run Order Record] 実注文なし・研究用のみ")
    print(f"  proposal_id  : {proposal_id}")
    print(f"  symbol       : {proposal.get('symbol')}")
    print(f"  side         : {proposal.get('side')}")
    print(f"  price        : {proposal.get('suggested_price')}")
    print(f"  size (units) : {proposal.get('suggested_size')}")
    print(f"  stop_loss    : {proposal.get('stop_loss')}")
    print(f"  take_profit  : {proposal.get('take_profit')}")
    print(f"  max_loss_jpy : {proposal.get('max_loss_jpy')}")
    print(f"\n承認フレーズ: '{DRY_RUN_APPROVAL_PHRASE}'")

    try:
        approval = input("承認フレーズを入力してください: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n[CANCEL] キャンセルされました。")
        sys.exit(0)

    order, reason = record_fx_dry_run_order(
        proposal=proposal,
        approval_input=approval,
        dry_run=True,
        read_only=True,
        path=DEFAULT_FX_DRY_RUN_ORDERS_PATH,
    )

    if order:
        print(f"\n[OK] {reason}")
        print(f"  order_id     : {order.get('order_id')}")
        print(f"  recorded_at  : {order.get('recorded_at')}")
        print(f"  send_to_exchange: {order.get('send_to_exchange')}")
        print(f"  dry_run      : {order.get('dry_run')}")
    else:
        print(f"\n[SKIP] {reason}")


if __name__ == "__main__":
    main()
