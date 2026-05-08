from pathlib import Path

from src.risk.execution_state import ExecutionStore
from src.risk.pending_orders import PendingOrderStore


def test_place_order_failure_does_not_add_pending_order(tmp_path: Path):
    from src.risk.order_executor import OrderExecutor
    from src.risk.duplicate_order_guard import DuplicateOrderGuard

    class FailingAdapter:
        read_only = False

        def place_order(self, **kwargs):
            raise RuntimeError("ERR-5127 This operation is restricted.")

    pending_store = PendingOrderStore(db_path=tmp_path / "test.db")
    executor = OrderExecutor(
        adapter=FailingAdapter(),
        execution_store=ExecutionStore(db_path=tmp_path / "test.db"),
        pending_store=pending_store,
        guard=DuplicateOrderGuard(db_path=tmp_path / "test.db", guard_seconds=60),
        dry_run=False,
    )
    executor._approval_fn = lambda plan: True

    try:
        executor.place_order(
            symbol="BTC_JPY",
            side="BUY",
            order_type="LIMIT",
            price=12_000_000.0,
            quantity=0.00008,
            amount_jpy=960.0,
        )
    except RuntimeError:
        pass

    assert pending_store.open_order_count() == 0
    assert pending_store.load_by_id("FAILED_TO_PLACE") is None


def test_live_order_once_generates_failed_order_report(monkeypatch, tmp_path: Path):
    from scripts import live_order_once

    saved = {}

    class FakeAdapter:
        dry_run = False
        read_only = False

    class FakeChecklistResult:
        ok = True
        name = "ok"
        message = "ok"

    class FakeConfig:
        dry_run = False
        order_timeout_seconds = 1
        polling_interval_seconds = 0
        stop_trading_file = tmp_path / "STOP_TRADING"

    class FakeRiskManager:
        def __init__(self, config=None, adapter=None):
            self.config = config
            self.adapter = adapter
            self.pending_store = type("PendingStore", (), {"db_path": tmp_path / "test.db"})()

        def pre_trade_sync(self, symbol):
            return type("State", (), {"balance_jpy": 50_000.0, "btc_held": 0.0, "executions_today": []})()

        def check_order_allowed(self, **kwargs):
            return type("Result", (), {"allowed": True, "reason": "OK", "__str__": lambda self: "OK"})()

        def place_order(self, **kwargs):
            raise RuntimeError("ERR-5127 This operation is restricted.")

    def fake_generate_failed_order_report(**kwargs):
        saved["report"] = kwargs
        return type("Report", (), {"order_status": "FAILED", "file_suffix": "20260428_000000"})()

    def fake_save_report(report, reports_dir=None, logs_dir=None):
        saved["saved"] = True
        return tmp_path / "failed.md", tmp_path / "failed.log"

    monkeypatch.setattr(live_order_once, "run_checklist", lambda: [FakeChecklistResult()])
    monkeypatch.setattr(live_order_once, "load_adapter_from_env", lambda: FakeAdapter())
    monkeypatch.setattr(live_order_once, "load_config", lambda: FakeConfig())
    monkeypatch.setattr(live_order_once, "RiskManager", FakeRiskManager)
    monkeypatch.setattr(live_order_once, "get_current_price", lambda: 12_173_952.0)
    monkeypatch.setattr(
        live_order_once,
        "size_btc_jpy_limit_buy",
        lambda target_amount_jpy, reference_price_jpy: type(
            "SizedOrder",
            (),
            {"price": 12_173_952.0, "quantity": 0.00008, "amount_jpy": 973.91616},
        )(),
    )
    monkeypatch.setattr(live_order_once, "generate_failed_order_report", fake_generate_failed_order_report)
    monkeypatch.setattr(live_order_once, "save_report", fake_save_report)

    result = live_order_once.main()

    assert result == 1
    assert saved["report"]["symbol"] == "BTC_JPY"
    assert "ERR-5127" in saved["report"]["errors"][0]
    assert saved["saved"] is True
