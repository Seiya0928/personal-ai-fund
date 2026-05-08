import logging

from src.brokers.gmo_private_adapter import GMOPrivateAdapter
from src.execution.gmo_symbols import to_gmo_spot_symbol


def _adapter() -> GMOPrivateAdapter:
    return GMOPrivateAdapter("test_key", "super_secret_never_log", dry_run=False, read_only=False)


def test_internal_btc_jpy_maps_to_btc_in_api_body():
    adapter = _adapter()

    body = adapter._build_order_body(
        symbol="BTC_JPY",
        side="BUY",
        order_type="LIMIT",
        price=12_173_952.0,
        quantity=0.00008,
    )

    assert body["symbol"] == "BTC"


def test_limit_buy_body_matches_gmo_private_api_shape():
    adapter = _adapter()

    body = adapter._build_order_body(
        symbol="BTC_JPY",
        side="BUY",
        order_type="LIMIT",
        price=12_173_952.0,
        quantity=0.00008,
    )

    assert body == {
        "symbol": "BTC",
        "side": "BUY",
        "executionType": "LIMIT",
        "price": "12173952",
        "size": "0.00008000",
    }


def test_spot_symbol_mapping_handles_pair_and_spot_symbols():
    assert to_gmo_spot_symbol("BTC_JPY") == "BTC"
    assert to_gmo_spot_symbol("BTC") == "BTC"
    assert to_gmo_spot_symbol("ETH_JPY") == "ETH"


def test_size_is_sent_as_string():
    adapter = _adapter()
    body = adapter._build_order_body("BTC_JPY", "BUY", "LIMIT", 12_173_952.0, 0.00008)
    assert isinstance(body["size"], str)


def test_price_is_sent_as_integer_yen_string():
    adapter = _adapter()
    body = adapter._build_order_body("BTC_JPY", "BUY", "LIMIT", 12_173_952.9, 0.00008)
    assert body["price"] == "12173952"
    assert isinstance(body["price"], str)


def test_signature_body_matches_actual_request_body(monkeypatch):
    adapter = _adapter()
    captured = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        captured["data"] = data

        class DummyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"status": 0, "data": "12345"}

        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)

    body = adapter._build_order_body("BTC_JPY", "BUY", "LIMIT", 12_173_952.0, 0.00008)
    expected_body = adapter._serialize_body(body)

    adapter._post("/order", body)

    assert captured["data"] == expected_body


def test_api_secret_not_in_order_body_logs(caplog):
    adapter = _adapter()
    adapter._post = lambda path, body: {"data": "12345"}

    with caplog.at_level(logging.INFO):
        adapter.place_order("BTC_JPY", "BUY", "LIMIT", 12_173_952.0, 0.00008)

    full_log = "\n".join(caplog.messages)
    assert "super_secret_never_log" not in full_log
