import pytest
import requests

from src.brokers.gmo_private_adapter import GMOPrivateAdapter, GMOPrivateAPIError


class DummyResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {"status": 0, "data": "ok"}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"http {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._json_data


def _adapter() -> GMOPrivateAdapter:
    return GMOPrivateAdapter("key", "secret", dry_run=False, read_only=False)


def test_err_5127_does_not_retry(monkeypatch):
    adapter = _adapter()
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return DummyResponse(
            json_data={
                "status": 1,
                "messages": [
                    {
                        "message_code": "ERR-5127",
                        "message_string": "This operation is restricted.",
                    }
                ],
            }
        )

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    with pytest.raises(GMOPrivateAPIError) as exc_info:
        adapter._post("/order", {"symbol": "BTC_JPY"})

    assert "ERR-5127" in str(exc_info.value)
    assert len(calls) == 1


def test_err_5010_does_not_retry(monkeypatch):
    adapter = _adapter()
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return DummyResponse(
            json_data={
                "status": 1,
                "messages": [
                    {
                        "message_code": "ERR-5010",
                        "message_string": "Signature for this request is not valid.",
                    }
                ],
            }
        )

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    with pytest.raises(GMOPrivateAPIError) as exc_info:
        adapter._get("/account/assets")

    assert "ERR-5010" in str(exc_info.value)
    assert len(calls) == 1


def test_http_5xx_retries(monkeypatch):
    adapter = _adapter()
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            return DummyResponse(status_code=503)
        return DummyResponse(json_data={"status": 0, "data": "12345"})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = adapter._post("/order", {"symbol": "BTC_JPY"})

    assert result["data"] == "12345"
    assert len(calls) == 3
