from pathlib import Path

import pytest

from src.risk.order_sizing import (
    BTC_JPY_MIN_QUANTITY,
    BTC_JPY_QUANTITY_STEP,
    size_btc_jpy_limit_buy,
)


def test_size_btc_jpy_limit_buy_rounds_quantity_down_to_step():
    sized = size_btc_jpy_limit_buy(
        target_amount_jpy=1_000.0,
        reference_price_jpy=12_173_952.0,
    )

    assert sized.price == 12_173_952.0
    assert sized.quantity == 0.00008
    assert sized.amount_jpy == pytest.approx(973.91616)
    assert sized.amount_jpy <= 1_000.0


def test_size_btc_jpy_limit_buy_rounds_price_down_to_1yen():
    sized = size_btc_jpy_limit_buy(
        target_amount_jpy=1_000.0,
        reference_price_jpy=12_173_952.9,
    )

    assert sized.price == 12_173_952.0
    assert sized.amount_jpy <= 1_000.0


def test_size_btc_jpy_limit_buy_raises_if_min_quantity_exceeds_budget():
    with pytest.raises(ValueError, match="minimum quantity"):
        size_btc_jpy_limit_buy(
            target_amount_jpy=1_000.0,
            reference_price_jpy=200_000_000.0,
        )


def test_rehearsal_uses_same_order_sizing_result(tmp_path: Path):
    from scripts.rehearse_live_order import run_rehearsal, REHEARSAL_AMOUNT_JPY

    price = 12_173_952.0
    record = run_rehearsal(db_path=tmp_path / "test.db", current_price=price)
    sized = size_btc_jpy_limit_buy(REHEARSAL_AMOUNT_JPY, price)

    assert record.price == sized.price
    assert record.quantity == sized.quantity
    assert record.amount_jpy == sized.amount_jpy


def test_quantity_step_constants_match_gmo_btc_rule():
    assert str(BTC_JPY_MIN_QUANTITY) == "0.00001"
    assert str(BTC_JPY_QUANTITY_STEP) == "0.00001"
