import pytest

from src.brokers.gmo_private_adapter import GMOPrivateAdapter
from src.execution.gmo_symbols import to_gmo_spot_symbol


def test_to_gmo_spot_symbol_maps_btc_jpy_to_btc():
    assert to_gmo_spot_symbol("BTC_JPY") == "BTC"


def test_to_gmo_spot_symbol_keeps_btc_as_btc():
    assert to_gmo_spot_symbol("BTC") == "BTC"


def test_to_gmo_spot_symbol_maps_eth_jpy_to_eth():
    assert to_gmo_spot_symbol("ETH_JPY") == "ETH"


def test_to_gmo_spot_symbol_raises_for_invalid_symbol():
    with pytest.raises(ValueError, match="unsupported GMO spot symbol"):
        to_gmo_spot_symbol("DOGE_JPY")


def test_build_order_body_uses_gmo_spot_symbol():
    adapter = GMOPrivateAdapter("test_key", "test_secret", dry_run=False, read_only=False)
    body = adapter._build_order_body("BTC_JPY", "BUY", "LIMIT", 12_117_748.0, 0.00008)

    assert body == {
        "symbol": "BTC",
        "side": "BUY",
        "executionType": "LIMIT",
        "price": "12117748",
        "size": "0.00008000",
    }
