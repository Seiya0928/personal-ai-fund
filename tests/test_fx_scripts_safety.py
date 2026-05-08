from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_fx_usdjpy_signal.py"
SPEC = importlib.util.spec_from_file_location("run_fx_usdjpy_signal_test", SCRIPT_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_fx_script_requires_dry_run_true(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("READ_ONLY", "true")

    try:
        module.ensure_research_safety()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "DRY_RUN=true" in str(exc)


def test_fx_script_requires_read_only_true(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("READ_ONLY", "false")

    try:
        module.ensure_research_safety()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "READ_ONLY=true" in str(exc)


def test_fx_script_has_no_order_execution_imports_or_private_order_endpoint():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "order_executor" not in source
    assert "live_order_once" not in source
    assert "place_order" not in source
    assert "/private/v1/order" not in source
    assert "broker_adapter" not in source
