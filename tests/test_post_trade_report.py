"""
test_post_trade_report.py — 発注後検証レポートのテスト。

テスト対象:
  - OPEN 注文が残っていたら次回発注 NG
  - execution_state と API 残高がズレていたら NG
  - エラーがあれば NG
  - 正常約定なら OK
  - レポートファイル（.md と .log）が生成される
  - STOP_TRADING があれば NG
  - 本日注文回数が上限に達していれば NG
"""
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.risk.risk_config import RiskConfig
from src.risk.execution_state import ExecutionState, ExecutionStore, Execution
from src.risk.pending_orders import PendingOrderStore, PendingOrder, STATUS_OPEN, STATUS_FILLED, STATUS_CANCELLED
from src.risk.post_trade_reporter import generate_report, save_report, PostTradeReport


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, **overrides) -> RiskConfig:
    cfg = RiskConfig(
        dry_run=True,
        stop_trading_file=tmp_path / "STOP_TRADING",
        max_daily_orders=1,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _filled_pending(tmp_path: Path, order_id: str = "order_001") -> PendingOrder:
    """FILLED 状態の PendingOrder を DB に保存して返す。"""
    store = PendingOrderStore(db_path=tmp_path / "t.db")
    p = PendingOrder(
        order_id=order_id,
        symbol="BTC_JPY",
        side="BUY",
        order_type="LIMIT",
        price=10_000_000.0,
        quantity=0.0001,
        amount_jpy=1_000.0,
        status=STATUS_FILLED,
        created_at=time.time(),
        updated_at=time.time(),
        is_dry_run=True,
    )
    store.save(p)
    return p


def _open_pending(tmp_path: Path, order_id: str = "order_002") -> PendingOrder:
    """OPEN 状態の PendingOrder を DB に保存して返す。"""
    store = PendingOrderStore(db_path=tmp_path / "t.db")
    p = PendingOrder(
        order_id=order_id,
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
    )
    store.save(p)
    return p


def _make_states(btc_before=0.0, btc_after=0.0001, jpy_before=10_000.0, jpy_after=9_000.0):
    before = ExecutionState(balance_jpy=jpy_before, btc_held=btc_before)
    after = ExecutionState(balance_jpy=jpy_after, btc_held=btc_after)
    return before, after


def _run(tmp_path, order_id="order_001", errors=None, stop=False, exec_count=1, **cfg_overrides):
    """テスト用のデフォルト設定でレポートを生成する。"""
    config = _make_config(tmp_path, **cfg_overrides)
    if stop:
        config.stop_trading_file.write_text("stop")
    before, after = _make_states()
    # 本日約定を exec_count 件追加
    for i in range(exec_count):
        ex = Execution(
            symbol="BTC_JPY", side="BUY",
            price=10_000_000.0, quantity=0.0001,
            timestamp=time.time(),
            execution_id=f"fill_exec_{i}",
        )
        after.executions_today.append(ex)
    return generate_report(
        order_id=order_id,
        state_before=before,
        state_after=after,
        config=config,
        db_path=tmp_path / "t.db",
        adapter=None,
        errors=errors,
        stop_trading_file=config.stop_trading_file,
    )


# ---------------------------------------------------------------------------
# 次回発注可否チェックのテスト
# ---------------------------------------------------------------------------

class TestNextOrderAllowed:

    def test_normal_fill_is_ok(self, tmp_path):
        """正常約定（FILLED、エラーなし、OPEN注文なし）は次回発注 OK。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0)
        # FILLED 注文が 1 件あるが exec_count=0 → 本日約定0件 → 上限未達
        assert report.next_order_allowed is True
        assert report.next_order_blocked_reasons == []

    def test_open_order_remaining_blocks_next(self, tmp_path):
        """OPEN 注文が残っていると次回発注 NG。"""
        _open_pending(tmp_path)
        report = _run(tmp_path, order_id="order_002", exec_count=0)
        assert report.next_order_allowed is False
        assert any("未処理注文" in r for r in report.next_order_blocked_reasons)

    def test_non_terminal_status_blocks_next(self, tmp_path):
        """注文ステータスが FILLED でも CANCELLED でもない場合は NG。"""
        # OPEN 状態のまま
        _open_pending(tmp_path, order_id="open_999")
        report = _run(tmp_path, order_id="open_999", exec_count=0)
        assert report.next_order_allowed is False
        # "未確定" か "未処理注文" のいずれかでブロック
        reasons = " ".join(report.next_order_blocked_reasons)
        assert "未処理" in reasons or "未確定" in reasons

    def test_cancelled_order_is_ok_if_no_other_issues(self, tmp_path):
        """CANCELLED は終端ステータスなので、他に問題がなければ次回 OK。"""
        store = PendingOrderStore(db_path=tmp_path / "t.db")
        p = PendingOrder(
            order_id="cancelled_001",
            symbol="BTC_JPY", side="BUY", order_type="LIMIT",
            price=10_000_000.0, quantity=0.0001, amount_jpy=1_000.0,
            status=STATUS_CANCELLED,
            created_at=time.time(), updated_at=time.time(), is_dry_run=True,
        )
        store.save(p)
        report = _run(tmp_path, order_id="cancelled_001", exec_count=0)
        assert report.next_order_allowed is True

    def test_errors_block_next(self, tmp_path):
        """エラーが発生していると次回発注 NG。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, errors=["API timeout"], exec_count=0)
        assert report.next_order_allowed is False
        assert any("エラー" in r for r in report.next_order_blocked_reasons)

    def test_stop_trading_blocks_next(self, tmp_path):
        """STOP_TRADING ファイルが存在すると次回発注 NG。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, stop=True, exec_count=0)
        assert report.next_order_allowed is False
        assert any("STOP_TRADING" in r for r in report.next_order_blocked_reasons)

    def test_daily_limit_reached_blocks_next(self, tmp_path):
        """本日約定回数が上限に達していると次回発注 NG。"""
        _filled_pending(tmp_path)
        # max_daily_orders=1、exec_count=1 → 上限到達
        report = _run(tmp_path, exec_count=1, max_daily_orders=1)
        assert report.next_order_allowed is False
        assert any("上限" in r for r in report.next_order_blocked_reasons)

    def test_daily_limit_not_yet_reached_is_ok(self, tmp_path):
        """本日約定回数が上限未満なら OK。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0, max_daily_orders=1)
        assert report.next_order_allowed is True

    def test_balance_discrepancy_blocks_next(self, tmp_path):
        """API 残高とローカル状態がズレていると次回発注 NG。"""
        _filled_pending(tmp_path)
        config = _make_config(tmp_path, dry_run=False)

        # ローカル残高 ¥9,000、API残高 ¥50,000（大きなズレ）
        before, after = _make_states(jpy_after=9_000.0)
        mock_adapter = MagicMock()
        mock_adapter.get_balance.return_value = {"jpy": 50_000.0, "btc": 0.0}

        report = generate_report(
            order_id="order_001",
            state_before=before,
            state_after=after,
            config=config,
            db_path=tmp_path / "t.db",
            adapter=mock_adapter,
        )
        assert report.balance_discrepancy is True
        assert report.next_order_allowed is False
        assert any("残高ズレ" in r for r in report.next_order_blocked_reasons)

    def test_no_discrepancy_when_balances_match(self, tmp_path):
        """API 残高とローカル状態が一致していればズレなし。"""
        _filled_pending(tmp_path)
        config = _make_config(tmp_path, dry_run=False)
        before, after = _make_states(jpy_after=9_000.0)

        mock_adapter = MagicMock()
        mock_adapter.get_balance.return_value = {"jpy": 9_000.0, "btc": 0.0001}

        report = generate_report(
            order_id="order_001",
            state_before=before,
            state_after=after,
            config=config,
            db_path=tmp_path / "t.db",
            adapter=mock_adapter,
        )
        assert report.balance_discrepancy is False


# ---------------------------------------------------------------------------
# レポートファイル生成テスト
# ---------------------------------------------------------------------------

class TestSaveReport:
    def test_md_and_log_files_are_created(self, tmp_path):
        """save_report が .md と .log の両方を生成すること。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0)

        md_path, log_path = save_report(
            report,
            reports_dir=tmp_path / "reports",
            logs_dir=tmp_path / "logs",
        )
        assert md_path.exists(), f"Markdown ファイルが生成されていません: {md_path}"
        assert log_path.exists(), f"ログファイルが生成されていません: {log_path}"
        assert md_path.suffix == ".md"
        assert log_path.suffix == ".log"

    def test_md_contains_order_id(self, tmp_path):
        """Markdown ファイルに order_id が含まれること。"""
        _filled_pending(tmp_path, order_id="test_order_abc")
        report = _run(tmp_path, order_id="test_order_abc", exec_count=0)
        md_path, _ = save_report(report, reports_dir=tmp_path / "r", logs_dir=tmp_path / "l")
        content = md_path.read_text(encoding="utf-8")
        assert "test_order_abc" in content

    def test_md_contains_next_order_result(self, tmp_path):
        """Markdown に「次回発注可否」セクションが含まれること。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0)
        md_path, _ = save_report(report, reports_dir=tmp_path / "r", logs_dir=tmp_path / "l")
        content = md_path.read_text(encoding="utf-8")
        assert "次回発注可否" in content

    def test_log_contains_next_order_result(self, tmp_path):
        """ログファイルに next_order= が含まれること。"""
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0)
        _, log_path = save_report(report, reports_dir=tmp_path / "r", logs_dir=tmp_path / "l")
        content = log_path.read_text(encoding="utf-8")
        assert "next_order=" in content

    def test_filename_has_timestamp_format(self, tmp_path):
        """ファイル名が post_trade_YYYYMMDD_HHMMSS 形式であること。"""
        import re
        _filled_pending(tmp_path)
        report = _run(tmp_path, exec_count=0)
        md_path, log_path = save_report(report, reports_dir=tmp_path / "r", logs_dir=tmp_path / "l")
        pattern = r"post_trade_\d{8}_\d{6}"
        assert re.search(pattern, md_path.name), f"ファイル名の形式が違います: {md_path.name}"
        assert re.search(pattern, log_path.name), f"ファイル名の形式が違います: {log_path.name}"
