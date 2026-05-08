import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "rehearse_gmo_spot_order.py"
SPEC = importlib.util.spec_from_file_location("rehearse_gmo_spot_order_module", SCRIPT_PATH)
rehearse_gmo_spot_order = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = rehearse_gmo_spot_order
SPEC.loader.exec_module(rehearse_gmo_spot_order)


def test_build_rehearsal_uses_btc_for_order_body_symbol():
    rehearsal = rehearse_gmo_spot_order.build_rehearsal(
        symbol="BTC_JPY",
        proposal_jpy=1_000.0,
        reference_price=12_117_748.0,
    )

    assert rehearsal.internal_symbol == "BTC_JPY"
    assert rehearsal.gmo_spot_symbol == "BTC"
    assert rehearsal.order_body["symbol"] == "BTC"


def test_rehearsal_keeps_send_to_exchange_false_and_safety_true():
    rehearsal = rehearse_gmo_spot_order.build_rehearsal(
        symbol="BTC_JPY",
        proposal_jpy=1_000.0,
        reference_price=12_117_748.0,
    )

    assert rehearsal.send_to_exchange is False
    assert rehearsal.safety["DRY_RUN"] is True
    assert rehearsal.safety["READ_ONLY"] is True
    assert rehearsal.safety["send_to_exchange"] is False


def test_rehearsal_output_contains_expected_lines():
    rehearsal = rehearse_gmo_spot_order.build_rehearsal(
        symbol="BTC_JPY",
        proposal_jpy=1_000.0,
        reference_price=12_117_748.0,
    )

    output = rehearse_gmo_spot_order.render_rehearsal(rehearsal)

    assert "Rehearsal only. No order sent." in output
    assert "internal_symbol: BTC_JPY" in output
    assert "gmo_spot_symbol: BTC" in output
    assert 'price: "' in output
    assert 'size: "' in output


def test_rehearsal_requires_dry_run_and_read_only(monkeypatch):
    original_adapter = rehearse_gmo_spot_order.GMOPrivateAdapter

    class UnsafeAdapter(original_adapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.dry_run = False

    monkeypatch.setattr(rehearse_gmo_spot_order, "GMOPrivateAdapter", UnsafeAdapter)
    try:
        try:
            rehearse_gmo_spot_order.build_rehearsal(
                symbol="BTC_JPY",
                proposal_jpy=1_000.0,
                reference_price=12_117_748.0,
            )
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "DRY_RUN" in str(exc)
    finally:
        monkeypatch.setattr(rehearse_gmo_spot_order, "GMOPrivateAdapter", original_adapter)


def test_rehearsal_does_not_call_private_order_endpoint(monkeypatch):
    called = {"post": False}

    def fail_post(self, path, body):
        called["post"] = True
        raise AssertionError("should not call _post")

    monkeypatch.setattr(rehearse_gmo_spot_order.GMOPrivateAdapter, "_post", fail_post)
    rehearse_gmo_spot_order.build_rehearsal(
        symbol="BTC_JPY",
        proposal_jpy=1_000.0,
        reference_price=12_117_748.0,
    )

    assert called["post"] is False


def test_rehearsal_script_source_does_not_reference_live_order_once_or_manual_approval():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "live_order_once" not in source
    assert "manual_approval" not in source


def test_api_secret_is_not_printed(capsys, monkeypatch):
    monkeypatch.setattr(
        rehearse_gmo_spot_order,
        "parse_args",
        lambda: type("Args", (), {"symbol": "BTC_JPY", "proposal_jpy": 1000.0, "reference_price": 12_117_748.0})(),
    )

    exit_code = rehearse_gmo_spot_order.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "rehearsal_secret" not in output
