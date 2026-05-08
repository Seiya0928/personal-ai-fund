from pathlib import Path

from src.strategies.dca import DollarCostAveragingStrategy
from src.strategies.dip_buy import DipBuyStrategy
from src.strategies.moving_average import MovingAverageCross
from src.backtest.runner import BacktestRunner, BacktestResult


def _make_rows(prices: list[float], step_ms: int = 3_600_000) -> list[dict]:
    return [
        {"open": p, "high": p, "low": p, "close": p, "volume": 1.0, "timestamp": str(i * step_ms)}
        for i, p in enumerate(prices)
    ]


def _patch_small_search(monkeypatch, run_backtest):
    monkeypatch.setattr(
        run_backtest,
        "_iter_b_grid_configs",
        lambda: [{"name": "grid_small", "params": dict(run_backtest.B_BASELINE_CONFIG)}],
    )
    monkeypatch.setattr(
        run_backtest,
        "_iter_filtered_b_configs",
        lambda: [{
            "name": "filtered_small",
            "params": {
                **run_backtest.FILTER_SEARCH_BASES[0]["params"],
                "min_drop_from_recent_high_pct": 10.0,
                "recent_high_lookback_days": 30,
                "trend_filter": True,
                "volatility_filter": "none",
                "min_days_between_entries": 14.0,
            },
            "base_name": run_backtest.FILTER_SEARCH_BASES[0]["name"],
        }],
    )


def test_dca_strategy_marks_periodic_contributions():
    rows = _make_rows([100, 101, 102, 103, 104, 105])
    df = DollarCostAveragingStrategy(amount_jpy=1000, every_n_bars=2).generate_signals(rows)
    assert list(df["contribution_jpy"]) == [1000.0, 0.0, 1000.0, 0.0, 1000.0, 0.0]


def test_dip_buy_strategy_enters_on_drop_and_exits_on_take_profit():
    rows = _make_rows([100, 99, 95, 101, 102], step_ms=86_400_000)
    df = DipBuyStrategy(
        dip_threshold_pct=3.0,
        take_profit_pct=5.0,
        stop_loss_pct=10.0,
        max_holding_days=90.0,
        max_position_ratio=0.4,
        cooldown_days=7.0,
    ).generate_signals(rows)

    assert list(df["strategy_signal"]) == ["WAIT", "WAIT", "BUY_DIP", "TAKE_PROFIT", "WAIT"]
    assert list(df["target_position"]) == [0.0, 0.0, 0.4, 0.0, 0.0]


def test_dip_buy_strategy_timeout_exit_sets_reason():
    rows = _make_rows([100, 95, 94, 93], step_ms=86_400_000)
    df = DipBuyStrategy(
        dip_threshold_pct=3.0,
        take_profit_pct=50.0,
        stop_loss_pct=None,
        max_holding_days=1.0,
        max_position_ratio=0.3,
        cooldown_days=0.0,
    ).generate_signals(rows)

    assert "TIMEOUT_EXIT" in list(df["strategy_signal"])
    assert "TIMEOUT_EXIT" in list(df["exit_reason"].fillna(""))


def test_dip_buy_strategy_recent_high_and_trend_filters_block_small_dips():
    prices = [100] * 210 + [95, 96, 97]
    df = DipBuyStrategy(
        dip_threshold_pct=3.0,
        take_profit_pct=10.0,
        stop_loss_pct=12.5,
        max_holding_days=90.0,
        max_position_ratio=0.15,
        cooldown_days=14.0,
        min_drop_from_recent_high_pct=10.0,
        recent_high_lookback_days=30,
        trend_filter=True,
        volatility_filter="none",
        min_days_between_entries=14.0,
    ).generate_signals(_make_rows(prices, step_ms=86_400_000))

    assert "BUY_DIP" not in list(df["strategy_signal"])


def test_backtest_runner_returns_extended_metrics():
    prices = [100] * 10 + [110, 120, 130, 140, 150, 160, 170, 180, 190, 200] + [190, 180, 170, 160, 150, 140, 130, 120, 110, 100]
    df = MovingAverageCross(short=3, long=5).generate_signals(_make_rows(prices))
    result = BacktestRunner(initial_capital=100_000, fee_bps=10, spread_bps=5).run(df)

    assert result.final_capital > 0
    assert isinstance(result.annualized_return_pct, float)
    assert isinstance(result.max_drawdown_pct, float)
    assert isinstance(result.max_position_unrealized_drawdown_pct, float)
    assert isinstance(result.max_portfolio_unrealized_drawdown_pct, float)
    assert isinstance(result.max_unrealized_drawdown_pct, float)
    assert isinstance(result.max_holding_days, float)
    assert isinstance(result.average_holding_days, float)
    assert isinstance(result.capital_utilization_rate_pct, float)
    assert isinstance(result.return_per_max_drawdown, float)
    assert isinstance(result.return_per_holding_day, float)
    assert isinstance(result.max_capital_locked_days, float)
    assert "fee_bps" in result.assumptions
    assert result.execution_count >= result.trade_count


def test_buy_and_hold_comparison_metrics_are_computed():
    from scripts import run_backtest

    rows = _make_rows([100, 110, 120, 130, 140], step_ms=86_400_000)
    benchmark = run_backtest._compute_buy_and_hold(rows)

    assert benchmark["final_capital"] > 100_000
    assert "total_return_pct" in benchmark
    assert "annualized_return_pct" in benchmark
    assert "max_drawdown_pct" in benchmark


def test_b_grid_config_count_matches_full_search_space():
    from scripts import run_backtest

    assert len(run_backtest._iter_b_grid_configs()) == 2304


def test_filtered_b_config_count_matches_search_space():
    from scripts import run_backtest

    assert len(run_backtest._iter_filtered_b_configs()) == 768


def test_run_backtest_saves_markdown_report(tmp_path: Path, monkeypatch):
    from scripts import run_backtest

    class FakeStore:
        def load_ohlcv(self, symbol, interval, limit=0):
            base = [100 + i for i in range(120 if interval == "1day" else 200)]
            return _make_rows(base)

    monkeypatch.setattr(run_backtest, "SQLiteStore", lambda: FakeStore())
    monkeypatch.setattr(run_backtest, "ROOT", tmp_path)
    _patch_small_search(monkeypatch, run_backtest)

    result = run_backtest.main()
    report_files = list((tmp_path / "reports").glob("backtest_*.md"))

    assert result.exists()
    assert report_files
    content = report_files[0].read_text(encoding="utf-8")
    assert "| Strategy | Timeframe | Status |" in content
    assert "B&H Return" in content
    assert "Evaluation" in content
    assert "## 実運用判断" in content
    assert "暫定実運用候補" in content
    assert "Portfolio Unrealized DD" in content
    assert "## B派生グリッド比較表" in content
    assert "## 実運用向きランキング" in content
    assert "## フィルター追加版の比較表" in content


def test_run_backtest_keeps_going_when_hourly_ma_has_insufficient_data(tmp_path: Path, monkeypatch):
    from scripts import run_backtest

    class FakeStore:
        def load_ohlcv(self, symbol, interval, limit=0):
            if interval == "1hour":
                return _make_rows([100 + i for i in range(8)])
            return _make_rows([100 + i for i in range(120)], step_ms=86_400_000)

    monkeypatch.setattr(run_backtest, "SQLiteStore", lambda: FakeStore())
    monkeypatch.setattr(run_backtest, "ROOT", tmp_path)
    _patch_small_search(monkeypatch, run_backtest)

    report_path = run_backtest.main()
    content = report_path.read_text(encoding="utf-8")

    assert report_path.exists()
    assert "移動平均クロス / 1hour" in content
    assert "Status: SKIPPED" in content
    assert "定時積立 / 1day" in content
    assert "Status: OK" in content
    assert "| 移動平均クロス | 1hour | SKIPPED |" in content


def test_run_backtest_marks_errors_without_stopping(tmp_path: Path, monkeypatch):
    from scripts import run_backtest

    class FakeStore:
        def load_ohlcv(self, symbol, interval, limit=0):
            return _make_rows([100 + i for i in range(120 if interval == "1day" else 200)])

    class BrokenDip:
        def generate_signals(self, rows):
            raise RuntimeError("broken strategy")

    monkeypatch.setattr(run_backtest, "SQLiteStore", lambda: FakeStore())
    monkeypatch.setattr(run_backtest, "ROOT", tmp_path)
    monkeypatch.setattr(run_backtest, "DipBuyStrategy", lambda **kwargs: BrokenDip())
    _patch_small_search(monkeypatch, run_backtest)

    report_path = run_backtest.main()
    content = report_path.read_text(encoding="utf-8")

    assert "急落時のみ買い A / 1day" in content
    assert "Status: ERROR" in content
    assert "broken strategy" in content
    assert "移動平均クロス / 1day" in content


def test_report_contains_benchmark_verdict_and_evaluation(tmp_path: Path, monkeypatch):
    from scripts import run_backtest

    class FakeStore:
        def load_ohlcv(self, symbol, interval, limit=0):
            return _make_rows([100 + i for i in range(120 if interval == "1day" else 200)])

    monkeypatch.setattr(run_backtest, "SQLiteStore", lambda: FakeStore())
    monkeypatch.setattr(run_backtest, "ROOT", tmp_path)
    _patch_small_search(monkeypatch, run_backtest)

    report_path = run_backtest.main()
    content = report_path.read_text(encoding="utf-8")

    assert "Buy & Holdに" in content
    assert any(label in content for label in ("Candidate", "Watch", "Reject"))
    assert "Capital utilization rate" in content


def test_runner_clamps_tiny_residual_position_and_keeps_unrealized_dd_below_100():
    prices = [100, 95, 101, 95, 101]
    df = DipBuyStrategy(
        dip_threshold_pct=3.0,
        take_profit_pct=5.0,
        stop_loss_pct=10.0,
        max_holding_days=90.0,
        max_position_ratio=0.35,
        cooldown_days=0.0,
    ).generate_signals(_make_rows(prices, step_ms=86_400_000))
    result = BacktestRunner(initial_capital=100_000, fee_bps=12, spread_bps=5).run(df)

    assert result.max_position_unrealized_drawdown_pct < 100.0
    assert result.max_portfolio_unrealized_drawdown_pct < 35.0
    assert result.max_unrealized_drawdown_pct == result.max_portfolio_unrealized_drawdown_pct


def _result(
    total_return: float,
    annualized: float,
    max_dd: float,
    trade_count: int,
    period_days: float,
    win_rate: float,
    final_capital: float = 120_000,
):
    return BacktestResult(
        initial_capital=100_000,
        final_capital=final_capital,
        total_return_pct=total_return,
        annualized_return_pct=annualized,
        win_rate_pct=win_rate,
        max_drawdown_pct=max_dd,
        max_position_unrealized_drawdown_pct=max_dd,
        max_portfolio_unrealized_drawdown_pct=max_dd,
        max_unrealized_drawdown_pct=max_dd,
        max_holding_days=30.0,
        average_holding_days=10.0,
        capital_utilization_rate_pct=60.0,
        return_per_max_drawdown=0.5,
        return_per_holding_day=0.1,
        max_capital_locked_days=40.0,
        realized_loss_count=1,
        stop_loss_count=0,
        timeout_exit_count=0,
        trade_count=trade_count,
        execution_count=trade_count,
        average_pnl_jpy=500.0,
        total_pnl_jpy=final_capital - 100_000,
        period_days=period_days,
        trades=[],
        assumptions={"fee_bps": 12.0, "spread_bps": 5.0},
    )


def test_strict_evaluation_rejects_when_losing_to_benchmark():
    from scripts import run_backtest

    entry = run_backtest._status_result("test", "1day", _make_rows([100, 110], step_ms=86_400_000), "OK", result=_result(12.0, 12.0, 20.0, 12, 400.0, 60.0))
    entry["benchmark"] = {"total_return_pct": 15.0, "max_drawdown_pct": 25.0}
    run_backtest._evaluate_entry(entry)

    assert entry["evaluation"] == "Reject"
    assert entry["benchmark_verdict"] == "Buy & Holdに負けた"


def test_strict_evaluation_downgrades_hourly_short_sample_to_watch():
    from scripts import run_backtest

    entry = run_backtest._status_result("test", "1hour", _make_rows([100, 110], step_ms=3_600_000), "OK", result=_result(25.0, 30.0, 20.0, 20, 126.0, 70.0))
    entry["benchmark"] = {"total_return_pct": 5.0, "max_drawdown_pct": 30.0}
    run_backtest._evaluate_entry(entry)

    assert entry["evaluation"] == "Watch"


def test_strict_evaluation_downgrades_win_rate_100_to_watch():
    from scripts import run_backtest

    entry = run_backtest._status_result("test", "1day", _make_rows([100, 110], step_ms=86_400_000), "OK", result=_result(15.0, 12.0, 20.0, 12, 400.0, 100.0))
    entry["benchmark"] = {"total_return_pct": 3.0, "max_drawdown_pct": 25.0}
    run_backtest._evaluate_entry(entry)

    assert entry["evaluation"] == "Watch"
    assert "未実現損失・損切り未考慮の可能性あり" in entry["warnings"]


def test_select_provisional_candidate_prefers_day_watch_over_hour_watch():
    from scripts import run_backtest

    hourly = run_backtest._status_result("移動平均クロス", "1hour", [], "OK", result=_result(18.0, 14.0, 18.0, 16, 126.0, 60.0))
    hourly["benchmark"] = {"total_return_pct": 10.0, "max_drawdown_pct": 25.0}
    run_backtest._evaluate_entry(hourly)

    daily = run_backtest._status_result("急落時のみ買い B", "1day", [], "OK", result=_result(14.0, 11.0, 22.0, 8, 320.0, 75.0))
    daily["benchmark"] = {"total_return_pct": 8.0, "max_drawdown_pct": 28.0}
    run_backtest._evaluate_entry(daily)

    selected = run_backtest._select_provisional_candidate([hourly, daily])

    assert selected["name"] == "急落時のみ買い B"
    assert selected["interval"] == "1day"


def test_candidate_requires_operational_constraints():
    from scripts import run_backtest

    result = _result(16.0, 12.0, 20.0, 15, 400.0, 70.0)
    result.max_holding_days = 400.0
    entry = run_backtest._status_result("急落時のみ買い B", "1day", [], "OK", result=result)
    entry["benchmark"] = {"total_return_pct": 8.0, "max_drawdown_pct": 35.0}
    run_backtest._evaluate_entry(entry)

    assert entry["evaluation"] == "Watch"


def test_live_evaluation_detects_candidate_and_reject():
    from scripts import run_backtest

    candidate = run_backtest._status_result("grid", "1day", [], "OK", result=_result(18.0, 7.0, 12.0, 180, 400.0, 60.0))
    candidate["benchmark"] = {"total_return_pct": 8.0, "max_drawdown_pct": 30.0}
    candidate["result"].max_portfolio_unrealized_drawdown_pct = 5.0
    candidate["result"].max_holding_days = 60.0
    candidate["result"].average_holding_days = 20.0
    candidate["result"].capital_utilization_rate_pct = 15.0
    candidate["result"].stop_loss_count = 20
    run_backtest._evaluate_entry(candidate)
    run_backtest._evaluate_live_entry(candidate)
    assert candidate["near_live_candidate"] is True

    reject = run_backtest._status_result("grid", "1day", [], "OK", result=_result(5.0, 2.5, 20.0, 400, 400.0, 60.0))
    reject["benchmark"] = {"total_return_pct": 8.0, "max_drawdown_pct": 30.0}
    reject["result"].max_portfolio_unrealized_drawdown_pct = 12.0
    reject["result"].max_holding_days = 120.0
    reject["result"].average_holding_days = 40.0
    reject["result"].capital_utilization_rate_pct = 35.0
    reject["result"].stop_loss_count = 80
    run_backtest._evaluate_entry(reject)
    run_backtest._evaluate_live_entry(reject)

    assert candidate["live_evaluation"] == "LiveCandidate"
    assert reject["live_evaluation"] == "LiveReject"
    assert reject["near_live_candidate"] is False


def test_report_contains_operational_ranking(tmp_path: Path, monkeypatch):
    from scripts import run_backtest

    class FakeStore:
        def load_ohlcv(self, symbol, interval, limit=0):
            if interval == "1day":
                return _make_rows([100, 95, 101, 96, 103, 98, 106, 100, 110, 104, 112, 108] * 40, step_ms=86_400_000)
            return _make_rows([100 + (i % 12) for i in range(500)])

    monkeypatch.setattr(run_backtest, "SQLiteStore", lambda: FakeStore())
    monkeypatch.setattr(run_backtest, "ROOT", tmp_path)
    _patch_small_search(monkeypatch, run_backtest)

    report_path = run_backtest.main()
    content = report_path.read_text(encoding="utf-8")

    assert "## 実運用向きランキング" in content
    assert "Stop Losses" in content
    assert "準LiveCandidate" in content
