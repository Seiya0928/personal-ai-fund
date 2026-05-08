"""
test_read_only.py — READ_ONLY モード・APIキー安全確認テスト。

テスト対象:
  - READ_ONLY=true のとき place_order が ReadOnlyViolationError を送出する
  - READ_ONLY=true のとき cancel_order が ReadOnlyViolationError を送出する
  - READ_ONLY=false DRY_RUN=true は発注を許可する（モック）
  - APIキー未設定で load_adapter_from_env が MissingAPIKeyError を送出する
  - APIシークレット未設定で load_adapter_from_env が MissingAPIKeyError を送出する
  - ログ出力にシークレットが含まれないこと
"""
import logging
import pytest

from src.brokers.gmo_private_adapter import (
    GMOPrivateAdapter,
    ReadOnlyViolationError,
    MissingAPIKeyError,
    load_adapter_from_env,
)
from src.execution.gmo_symbols import to_gmo_spot_symbol


# ---------------------------------------------------------------------------
# READ_ONLY ガードテスト
# ---------------------------------------------------------------------------

class TestReadOnlyGuard:
    def _make_adapter(self, read_only: bool, dry_run: bool = True) -> GMOPrivateAdapter:
        return GMOPrivateAdapter(
            api_key="test_key",
            api_secret="test_secret",
            dry_run=dry_run,
            read_only=read_only,
        )

    def test_read_only_blocks_place_order(self):
        """READ_ONLY=true のとき place_order は ReadOnlyViolationError を送出する。"""
        adapter = self._make_adapter(read_only=True)
        with pytest.raises(ReadOnlyViolationError) as exc_info:
            adapter.place_order(
                symbol="BTC_JPY",
                side="BUY",
                order_type="LIMIT",
                price=10_000_000.0,
                quantity=0.001,
            )
        # エラーメッセージに place_order が含まれること
        assert "place_order" in str(exc_info.value)
        assert "READ_ONLY" in str(exc_info.value)

    def test_read_only_blocks_cancel_order(self):
        """READ_ONLY=true のとき cancel_order は ReadOnlyViolationError を送出する。"""
        adapter = self._make_adapter(read_only=True)
        with pytest.raises(ReadOnlyViolationError) as exc_info:
            adapter.cancel_order(order_id="12345", symbol="BTC_JPY")
        assert "cancel_order" in str(exc_info.value)
        assert "READ_ONLY" in str(exc_info.value)

    def test_read_only_false_dry_run_allows_place_order(self):
        """READ_ONLY=false かつ DRY_RUN=true はモック発注を許可する。"""
        adapter = self._make_adapter(read_only=False, dry_run=True)
        result = adapter.place_order(
            symbol="BTC_JPY",
            side="BUY",
            order_type="LIMIT",
            price=10_000_000.0,
            quantity=0.001,
        )
        assert result["order_id"].startswith("dry_")
        assert result["status"] == "OPEN"

    def test_read_only_false_dry_run_allows_cancel_order(self):
        """READ_ONLY=false かつ DRY_RUN=true はモックキャンセルを許可する。"""
        adapter = self._make_adapter(read_only=False, dry_run=True)
        result = adapter.cancel_order(order_id="dry_abc123", symbol="BTC_JPY")
        assert result is True

    def test_read_only_does_not_block_get_balance(self, monkeypatch):
        """READ_ONLY=true でも get_balance（読み取り）はブロックされない。"""
        adapter = self._make_adapter(read_only=True)
        # _get をモックして API 呼び出しをスキップ
        mock_response = {"status": 0, "data": [
            {"symbol": "JPY", "amount": "100000", "available": "100000"},
            {"symbol": "BTC", "amount": "0.001",  "available": "0.001"},
        ]}
        monkeypatch.setattr(adapter, "_get", lambda path, params=None: mock_response)
        balance = adapter.get_balance()
        assert balance["jpy"] == 100_000.0
        assert balance["btc"] == 0.001


class TestSignaturePayload:
    def _make_adapter(self) -> GMOPrivateAdapter:
        return GMOPrivateAdapter(
            api_key="test_key",
            api_secret="test_secret",
            dry_run=False,
            read_only=True,
        )

    def test_get_account_assets_signature_payload(self, monkeypatch):
        """GET /account/assets は /v1/account/assets と空bodyで署名される。"""
        adapter = self._make_adapter()
        monkeypatch.setattr("time.time", lambda: 1710000000.123)

        versioned_path = adapter._versioned_path("/account/assets")
        timestamp, payload = adapter._build_signature_payload("GET", versioned_path, "")

        assert versioned_path == "/v1/account/assets"
        assert timestamp == "1710000000123"
        assert payload == "1710000000123GET/v1/account/assets"

    def test_get_signature_payload_does_not_include_empty_json(self, monkeypatch):
        """GET の署名対象に {} は含まれない。"""
        adapter = self._make_adapter()
        monkeypatch.setattr("time.time", lambda: 1710000000.123)

        _, payload = adapter._build_signature_payload(
            "GET",
            adapter._versioned_path("/account/assets"),
            "",
        )

        assert "{}" not in payload

    def test_post_signature_payload_includes_json_body(self, monkeypatch):
        """POST は JSON 文字列を署名対象に含める。"""
        adapter = self._make_adapter()
        body = {"symbol": to_gmo_spot_symbol("BTC_JPY"), "side": "BUY"}
        body_str = adapter._serialize_body(body)
        monkeypatch.setattr("time.time", lambda: 1710000000.123)

        timestamp, payload = adapter._build_signature_payload(
            "POST",
            adapter._versioned_path("/order"),
            body_str,
        )

        assert timestamp == "1710000000123"
        assert body_str == '{"symbol":"BTC","side":"BUY"}'
        assert payload == '1710000000123POST/v1/order{"symbol":"BTC","side":"BUY"}'


# ---------------------------------------------------------------------------
# APIキー安全確認テスト
# ---------------------------------------------------------------------------

class TestMissingAPIKey:
    def test_missing_api_key_raises(self, monkeypatch, tmp_path):
        """GMO_API_KEY が未設定のとき load_adapter_from_env が MissingAPIKeyError を送出する。"""
        monkeypatch.setenv("GMO_API_KEY", "")
        monkeypatch.setenv("GMO_API_SECRET", "dummy_secret")
        monkeypatch.setattr("dotenv.load_dotenv", lambda: None)  # .env 読み込みスキップ

        with pytest.raises(MissingAPIKeyError) as exc_info:
            load_adapter_from_env()
        assert "GMO_API_KEY" in str(exc_info.value)

    def test_missing_api_secret_raises(self, monkeypatch):
        """GMO_API_SECRET が未設定のとき load_adapter_from_env が MissingAPIKeyError を送出する。"""
        monkeypatch.setenv("GMO_API_KEY", "dummy_key")
        monkeypatch.setenv("GMO_API_SECRET", "")
        monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

        with pytest.raises(MissingAPIKeyError) as exc_info:
            load_adapter_from_env()
        assert "GMO_API_SECRET" in str(exc_info.value)

    def test_valid_keys_return_adapter(self, monkeypatch):
        """有効なキーが設定されていれば GMOPrivateAdapter が返る。"""
        monkeypatch.setenv("GMO_API_KEY", "valid_key_1234")
        monkeypatch.setenv("GMO_API_SECRET", "valid_secret_5678")
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

        adapter = load_adapter_from_env()
        assert isinstance(adapter, GMOPrivateAdapter)
        assert adapter.dry_run is True
        assert adapter.read_only is True


# ---------------------------------------------------------------------------
# シークレット非露出テスト
# ---------------------------------------------------------------------------

class TestSecretNotInLogs:
    def test_secret_not_in_logs(self, monkeypatch, caplog):
        """APIシークレットがログに出力されないこと。"""
        secret = "super_secret_key_9999"
        monkeypatch.setenv("GMO_API_KEY", "test_key_1234")
        monkeypatch.setenv("GMO_API_SECRET", secret)
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

        with caplog.at_level(logging.DEBUG):
            load_adapter_from_env()

        # ログ全文にシークレット文字列が含まれていないことを確認
        full_log = "\n".join(caplog.messages)
        assert secret not in full_log, f"シークレットがログに露出しています: {full_log}"

    def test_api_key_only_last4_in_logs(self, monkeypatch, caplog):
        """ログにはAPIキーの末尾4文字のみが含まれること（先頭は *** でマスク）。"""
        api_key = "ABCDEF1234567890"
        last4 = api_key[-4:]  # "7890"
        first_part = api_key[:-4]  # "ABCDEF123456"

        monkeypatch.setenv("GMO_API_KEY", api_key)
        monkeypatch.setenv("GMO_API_SECRET", "some_secret_xyz")
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("READ_ONLY", "true")
        monkeypatch.setattr("dotenv.load_dotenv", lambda: None)

        with caplog.at_level(logging.INFO):
            load_adapter_from_env()

        full_log = "\n".join(caplog.messages)
        # APIキーの先頭部分はログに出ていないこと
        assert first_part not in full_log, f"APIキーの先頭部分がログに露出しています"
        # 末尾4文字はログに出ること（*** でマスクされた状態で確認）
        assert f"***{last4}" in full_log, f"***{last4} がログに見つかりません: {full_log}"


class TestCheckPrivateApiConnection:
    def test_script_calls_get_balance_only(self, monkeypatch):
        """接続確認スクリプトは get_balance 以外の adapter メソッドを呼ばない。"""
        from scripts import check_private_api_connection as script

        calls = []

        class FakeAdapter:
            dry_run = False
            read_only = True

            def get_balance(self):
                calls.append("get_balance")
                return {"jpy": 100_000.0, "btc": 0.001, "btc_available": 0.001}

            def place_order(self, *args, **kwargs):
                raise AssertionError("place_order must not be called")

            def cancel_order(self, *args, **kwargs):
                raise AssertionError("cancel_order must not be called")

            def get_positions(self, *args, **kwargs):
                raise AssertionError("get_positions must not be called")

            def get_executions_today(self, *args, **kwargs):
                raise AssertionError("get_executions_today must not be called")

        monkeypatch.setattr(script, "load_adapter_from_env", lambda: FakeAdapter())

        result = script.main()

        assert result == 0
        assert calls == ["get_balance"]
