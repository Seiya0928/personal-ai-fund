"""GMO現物注文 body の発注直前リハーサル。

実注文は送信しない。
Private API の /private/v1/order も呼ばない。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.brokers.gmo_private_adapter import GMOPrivateAdapter
from src.execution.gmo_symbols import to_gmo_spot_symbol
from src.risk.order_sizing import size_btc_jpy_limit_buy
from src.storage.sqlite_store import SQLiteStore

DEFAULT_SYMBOL = "BTC_JPY"
DEFAULT_SIDE = "BUY"
DEFAULT_ORDER_TYPE = "LIMIT"
DEFAULT_PROPOSAL_JPY = 1_000.0
DEFAULT_FALLBACK_PRICE = 12_117_748.0


@dataclass
class SpotOrderRehearsal:
    internal_symbol: str
    gmo_spot_symbol: str
    order_body: dict
    send_to_exchange: bool
    safety: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GMO現物注文 body リハーサル")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--proposal-jpy", type=float, default=DEFAULT_PROPOSAL_JPY)
    parser.add_argument("--reference-price", type=float)
    return parser.parse_args()


def load_reference_price(symbol: str, explicit_price: float | None) -> float:
    if explicit_price is not None and explicit_price > 0:
        return explicit_price
    store = SQLiteStore()
    ticker = store.load_latest_ticker(symbol)
    if ticker and ticker.get("last"):
        return float(ticker["last"])
    return DEFAULT_FALLBACK_PRICE


def build_rehearsal(symbol: str = DEFAULT_SYMBOL, proposal_jpy: float = DEFAULT_PROPOSAL_JPY, reference_price: float | None = None) -> SpotOrderRehearsal:
    adapter = GMOPrivateAdapter(
        api_key="rehearsal_key",
        api_secret="rehearsal_secret",
        dry_run=True,
        read_only=True,
    )
    if not adapter.dry_run:
        raise ValueError("DRY_RUN must stay true for rehearsal")
    if not adapter.read_only:
        raise ValueError("READ_ONLY must stay true for rehearsal")

    actual_reference_price = load_reference_price(symbol, reference_price)
    sized = size_btc_jpy_limit_buy(proposal_jpy, actual_reference_price)
    order_body = adapter._build_order_body(
        symbol=symbol,
        side=DEFAULT_SIDE,
        order_type=DEFAULT_ORDER_TYPE,
        price=sized.price,
        quantity=sized.quantity,
    )

    return SpotOrderRehearsal(
        internal_symbol=symbol,
        gmo_spot_symbol=to_gmo_spot_symbol(symbol),
        order_body=order_body,
        send_to_exchange=False,
        safety={
            "DRY_RUN": True,
            "READ_ONLY": True,
            "send_to_exchange": False,
        },
    )


def render_rehearsal(rehearsal: SpotOrderRehearsal) -> str:
    body = rehearsal.order_body
    lines = [
        "Rehearsal only. No order sent.",
        f"internal_symbol: {rehearsal.internal_symbol}",
        f"gmo_spot_symbol: {rehearsal.gmo_spot_symbol}",
        "order_body:",
        f"  symbol: {body['symbol']}",
        f"  side: {body['side']}",
        f"  executionType: {body['executionType']}",
        f'  size: "{body["size"]}"',
        f'  price: "{body["price"]}"',
        "safety:",
        f"  DRY_RUN: {str(rehearsal.safety['DRY_RUN']).lower()}",
        f"  READ_ONLY: {str(rehearsal.safety['READ_ONLY']).lower()}",
        f"  send_to_exchange: {str(rehearsal.safety['send_to_exchange']).lower()}",
    ]
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    rehearsal = build_rehearsal(
        symbol=args.symbol,
        proposal_jpy=args.proposal_jpy,
        reference_price=args.reference_price,
    )
    print(render_rehearsal(rehearsal))
    return 0


if __name__ == "__main__":
    sys.exit(main())
