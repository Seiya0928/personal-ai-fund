"""
order_sizing.py — GMOコイン現物注文の価格・数量丸め。

現時点の BTC/JPY 取引所（現物）ルールに合わせて、
- 最小注文数量: 0.00001 BTC / 回
- 最小注文単位: 0.00001 BTC / 回
で数量を切り下げる。

価格刻みは GMO Private API の注文 price が整数円文字列であることから、
BTC_JPY は 1円単位で扱う。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

BTC_JPY_MIN_QUANTITY = Decimal("0.00001")
BTC_JPY_QUANTITY_STEP = Decimal("0.00001")
BTC_JPY_PRICE_TICK = Decimal("1")


@dataclass(frozen=True)
class SizedOrder:
    symbol: str
    price: float
    quantity: float
    amount_jpy: float
    target_amount_jpy: float


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def size_btc_jpy_limit_buy(target_amount_jpy: float, reference_price_jpy: float) -> SizedOrder:
    """
    BTC_JPY BUY LIMIT 用に、価格と数量を GMO 仕様に合わせて丸める。

    - 価格: 1円刻みで切り下げ
    - 数量: 0.00001 BTC 刻みで切り下げ
    - 実注文金額は target_amount_jpy を超えない
    """
    if target_amount_jpy <= 0:
        raise ValueError("target_amount_jpy must be positive")
    if reference_price_jpy <= 0:
      raise ValueError("reference_price_jpy must be positive")

    target_amount = Decimal(str(target_amount_jpy))
    raw_price = Decimal(str(reference_price_jpy))
    rounded_price = _floor_to_step(raw_price, BTC_JPY_PRICE_TICK)
    if rounded_price <= 0:
        raise ValueError("rounded price must be positive")

    raw_quantity = target_amount / rounded_price
    rounded_quantity = _floor_to_step(raw_quantity, BTC_JPY_QUANTITY_STEP)

    if rounded_quantity < BTC_JPY_MIN_QUANTITY:
        raise ValueError(
            "target_amount_jpy is too small for GMO BTC_JPY minimum quantity"
        )

    actual_amount = rounded_price * rounded_quantity
    if actual_amount > target_amount:
        raise ValueError("rounded order amount exceeds target amount")

    return SizedOrder(
        symbol="BTC_JPY",
        price=float(rounded_price),
        quantity=float(rounded_quantity),
        amount_jpy=float(actual_amount),
        target_amount_jpy=float(target_amount),
    )
