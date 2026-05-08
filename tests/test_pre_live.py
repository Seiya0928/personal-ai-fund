"""
test_pre_live.py — pre_live_checklist・rehearse_live_order のテスト。

テスト対象:
  - pending_orders が残っているとき pre_live_checklist が失敗
  - max_order_amount_jpy > 1,000 のとき失敗
  - allowed_order_types に MARKET があるとき失敗
  - STOP_TRADING ファイルが存在するとき失敗
  - DRY_RUN=true のとき失敗
  - READ_ONLY=true のとき失敗
  - 全項目 OK のとき成功
  - リハーサルは実 API の place_order を呼ばない
  - リハーサルは rehearsals テーブルに保存される
  - リハーサルは RiskManager.place_order を呼ばない
"""
import time
import pytest
from pathlib import Path

from src.risk.risk_config import RiskConfig
from src.risk.pending_orders import PendingOrderStore, PendingOrder, STATUS_OPEN


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _ok_env(tmp_path: Path) -> dict:
    """全項目 OK になる最低限の環境変数セット。"""
    return {
        "DRY_RUN": "false",
        "READ_ONLY": "false",
        "GMO_API_KEY": "dummy_key_1234",
        "GMO_API_SECRET": "dummy_secret_5678",
        "WITHDRAWAL_API_DISABLED": "confirmed",
    }


def _ok_config() -> RiskConfig:
    """全項目 OK になる RiskConfig。"""
    return RiskConfig(
        dry_run=False,
        max_order_amount_jpy=1_000.0,
        max_daily_orders=1,
        allowed_symbols=["BTC_JPY"],
        allowed_order_types=["LIMIT"],
    )


# ---------------------------------------------------------------------------
# pre_live_checklist テスト
# ---------------------------------------------------------------------------

class TestPreLiveChecklist:
    def _run(self, tmp_path, config=None, env=None, stop_file_exists=False):
        from scripts.pre_live_checklist import run_checklist

        cfg = config or _ok_config()
        ev = env or _ok_env(tmp_path)
        stop = tmp_path / "STOP_TRADING"
        cfg.stop_trading_file = stop
        if stop_file_exists:
            stop.write_text("stop")

        return run_checklist(config=cfg, db_path=tmp_path / "test.db", stop_trading_file=stop, env=ev)

    def _find(self, results, name):
        """名前で CheckResult を検索する。"""
        for r in results:
            if name in r.name:
                return r
        raise KeyError(f"'{name}' というチェック項目が見つかりません")

    # --- 全項目 OK ---

    def test_all_ok(self, tmp_path):
        results = self._run(tmp_path)
        failed = [r for r in results if not r.ok]
        assert failed == [], f"全項目 OK のはずが失敗: {[r.name + ': ' + r.message for r in failed]}"

    # --- DRY_RUN / READ_ONLY ---

    def test_dry_run_true_blocks(self, tmp_path):
        env = _ok_env(tmp_path)
        env["DRY_RUN"] = "true"
        results = self._run(tmp_path, env=env)
        r = self._find(results, "DRY_RUN")
        assert not r.ok
        assert "DRY_RUN" in r.message

    def test_read_only_true_blocks(self, tmp_path):
        env = _ok_env(tmp_path)
        env["READ_ONLY"] = "true"
        results = self._run(tmp_path, env=env)
        r = self._find(results, "READ_ONLY")
        assert not r.ok
        assert "READ_ONLY" in r.message

    # --- STOP_TRADING ---

    def test_stop_trading_file_blocks(self, tmp_path):
        results = self._run(tmp_path, stop_file_exists=True)
        r = self._find(results, "STOP_TRADING")
        assert not r.ok
        assert "STOP_TRADING" in r.message

    def test_no_stop_trading_file_passes(self, tmp_path):
        results = self._run(tmp_path, stop_file_exists=False)
        r = self._find(results, "STOP_TRADING")
        assert r.ok

    # --- APIキー ---

    def test_missing_api_key_blocks(self, tmp_path):
        env = _ok_env(tmp_path)
        env["GMO_API_KEY"] = ""
        results = self._run(tmp_path, env=env)
        r = self._find(results, "GMO_API_KEY")
        assert not r.ok

    def test_missing_api_secret_blocks(self, tmp_path):
        env = _ok_env(tmp_path)
        env["GMO_API_SECRET"] = ""
        results = self._run(tmp_path, env=env)
        r = self._find(results, "GMO_API_SECRET")
        assert not r.ok

    # --- 注文額 ---

    def test_max_order_amount_over_1000_blocks(self, tmp_path):
        cfg = _ok_config()
        cfg.max_order_amount_jpy = 1_001.0
        results = self._run(tmp_path, config=cfg)
        r = self._find(results, "最大注文額")
        assert not r.ok
        assert "1,001" in r.message

    def test_max_order_amount_exactly_1000_passes(self, tmp_path):
        cfg = _ok_config()
        cfg.max_order_amount_jpy = 1_000.0
        results = self._run(tmp_path, config=cfg)
        r = self._find(results, "最大注文額")
        assert r.ok

    # --- 日次注文回数 ---

    def test_max_daily_orders_over_1_blocks(self, tmp_path):
        cfg = _ok_config()
        cfg.max_daily_orders = 2
        results = self._run(tmp_path, config=cfg)
        r = self._find(results, "日次注文回数")
        assert not r.ok

    # --- 成行注文 ---

    def test_market_order_allowed_blocks(self, tmp_path):
        cfg = _ok_config()
        cfg.allowed_order_types = ["LIMIT", "MARKET"]
        results = self._run(tmp_path, config=cfg)
        r = self._find(results, "MARKET")
        assert not r.ok
        assert "MARKET" in r.message

    def test_only_limit_allowed_passes(self, tmp_path):
        results = self._run(tmp_path)
        r = self._find(results, "MARKET")
        assert r.ok

    # --- pending_orders ---

    def test_pending_orders_remaining_blocks(self, tmp_path):
        """OPEN 状態の注文が残っていると NG になる。"""
        db = tmp_path / "test.db"
        store = PendingOrderStore(db_path=db)
        store.save(PendingOrder(
            order_id="open_123",
            symbol="BTC_JPY",
            side="BUY",
            order_type="LIMIT",
            price=10_000_000.0,
            quantity=0.0001,
            amount_jpy=1_000.0,
            status=STATUS_OPEN,
            created_at=time.time(),
            updated_at=time.time(),
            is_dry_run=True,
        ))
        results = self._run(tmp_path)
        r = self._find(results, "未処理注文")
        assert not r.ok
        assert "1 件" in r.message

    def test_no_pending_orders_passes(self, tmp_path):
        results = self._run(tmp_path)
        r = self._find(results, "未処理注文")
        assert r.ok


# ---------------------------------------------------------------------------
# rehearse_live_order テスト
# ---------------------------------------------------------------------------

class TestRehearseLiveOrder:
    def test_rehearsal_does_not_call_place_order(self, tmp_path, monkeypatch):
        """リハーサルは RiskManager.place_order を呼ばない。"""
        from scripts.rehearse_live_order import run_rehearsal
        from src.risk.risk_manager import RiskManager

        place_order_called = []

        original_place_order = RiskManager.place_order

        def mock_place_order(self, *args, **kwargs):
            place_order_called.append(True)
            return original_place_order(self, *args, **kwargs)

        monkeypatch.setattr(RiskManager, "place_order", mock_place_order)

        run_rehearsal(db_path=tmp_path / "test.db", current_price=10_000_000.0)

        assert place_order_called == [], "リハーサルで place_order が呼ばれました（呼んではいけない）"

    def test_rehearsal_saves_to_db(self, tmp_path):
        """リハーサルは rehearsals テーブルに記録を保存する。"""
        from scripts.rehearse_live_order import run_rehearsal, RehearsalStore

        run_rehearsal(db_path=tmp_path / "test.db", current_price=10_000_000.0)

        store = RehearsalStore(db_path=tmp_path / "test.db")
        records = store.load_all()
        assert len(records) == 1
        assert records[0]["symbol"] == "BTC_JPY"
        assert records[0]["side"] == "BUY"
        assert records[0]["order_type"] == "LIMIT"
        assert float(records[0]["price"]) == 10_000_000.0

    def test_rehearsal_risk_check_passes_with_default_config(self, tmp_path):
        """デフォルト設定でリハーサルのリスクチェックが通る。"""
        from scripts.rehearse_live_order import run_rehearsal

        record = run_rehearsal(db_path=tmp_path / "test.db", current_price=10_000_000.0)
        assert record.risk_check_passed is True

    def test_rehearsal_quantity_correct(self, tmp_path):
        """数量は GMO の刻みに切り下げられ、注文額は上限以内に収まる。"""
        from scripts.rehearse_live_order import run_rehearsal

        price = 12_173_952.0
        record = run_rehearsal(db_path=tmp_path / "test.db", current_price=price)
        assert record.quantity == 0.00008
        assert record.amount_jpy <= 1_000.0
        assert record.price == price

    def test_rehearsal_uses_dry_run(self, tmp_path, monkeypatch):
        """リハーサルは RiskManager を DRY_RUN=true で起動する。"""
        from scripts.rehearse_live_order import run_rehearsal
        from src.risk.risk_manager import RiskManager

        dry_run_values = []
        original_init = RiskManager.__init__

        def mock_init(self, config=None, db_path=None, adapter=None):
            original_init(self, config=config, db_path=db_path, adapter=adapter)
            dry_run_values.append(self.config.dry_run)

        monkeypatch.setattr(RiskManager, "__init__", mock_init)

        run_rehearsal(db_path=tmp_path / "test.db", current_price=10_000_000.0)

        assert dry_run_values, "RiskManager が初期化されていません"
        assert all(v is True for v in dry_run_values), f"DRY_RUN が True ではありません: {dry_run_values}"

    def test_live_order_once_uses_shared_order_sizing(self, monkeypatch):
        """live_order_once は共通 order_sizing の結果をそのまま発注に使う。"""
        from scripts import live_order_once

        placed = {}

        class FakeAdapter:
            dry_run = False
            read_only = False

        class FakePending:
            order_id = "test_order_123"
            status = "OPEN"

        class FakeLoadedPending:
            status = "FILLED"

        class FakeRiskManager:
            def __init__(self, config=None, adapter=None):
                self.config = config
                self.adapter = adapter
                self.pending_store = self

            def pre_trade_sync(self, symbol):
                return type("State", (), {"btc_held": 0.0, "balance_jpy": 50_000.0})()

            def check_order_allowed(self, **kwargs):
                return type("Result", (), {"allowed": True, "reason": "OK", "__str__": lambda self: "OK"})()

            def place_order(self, **kwargs):
                placed.update(kwargs)
                return FakePending()

            def watch_orders(self):
                return ["test_order_123"]

            def load_by_id(self, order_id):
                return FakeLoadedPending()

        class FakeConfig:
            order_timeout_seconds = 1
            polling_interval_seconds = 0

        class FakeChecklistResult:
            def __init__(self):
                self.ok = True
                self.name = "ok"
                self.message = "ok"

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
                {
                    "price": 12_173_952.0,
                    "quantity": 0.00008,
                    "amount_jpy": 973.91616,
                },
            )(),
        )
        monkeypatch.setattr(live_order_once, "generate_report", lambda **kwargs: type(
            "Report", (), {"next_order_allowed": True, "next_order_blocked_reasons": []}
        )())
        monkeypatch.setattr(live_order_once, "save_report", lambda report: ("report.md", "report.log"))
        monkeypatch.setattr(live_order_once.time, "sleep", lambda _: None)

        result = live_order_once.main()

        assert result == 0
        assert placed["price"] == 12_173_952.0
        assert placed["quantity"] == 0.00008
        assert placed["amount_jpy"] == 973.91616
