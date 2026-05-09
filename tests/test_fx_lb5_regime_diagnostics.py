"""
lb=5 regime_filter 診断モジュールのテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.fx.fx_backtest import FXBacktestResult
from src.fx.lb5_regime_report import (
    D1_DIFF_PF_THRESHOLD,
    REGIME_PATTERNS,
    _evaluate_pattern,
    _format_monthly,
    _monthly_dependence_flag,
    _side_metrics,
    _summary_row,
    render_lb5_regime_report,
)


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

def _make_result(
    trade_count: int = 30,
    buy_count: int = 15,
    sell_count: int = 15,
    win_rate: float = 0.5,
    profit_factor: float = 1.2,
    max_drawdown_pct: float = 5.0,
    expectancy: float = 500.0,
    total_return_pct: float = 3.0,
    max_losing_streak: int = 3,
    avg_mfe_pips: float = 40.0,
    avg_mae_pips: float = 30.0,
    failed_after_half_tp_count: int = 2,
    monthly_returns: dict | None = None,
    trades: list[dict] | None = None,
) -> FXBacktestResult:
    if monthly_returns is None:
        monthly_returns = {"2026-01": 1.0, "2026-02": 0.5, "2026-03": 0.8}
    if trades is None:
        trades = [
            {"side": "LONG",  "pnl_jpy": 1000.0},
            {"side": "LONG",  "pnl_jpy": -500.0},
            {"side": "SHORT", "pnl_jpy": 800.0},
            {"side": "SHORT", "pnl_jpy": -400.0},
        ]
    return FXBacktestResult(
        symbol="USD/JPY H1",
        initial_balance=1_000_000,
        final_balance=1_000_000 * (1 + total_return_pct / 100),
        total_return_pct=total_return_pct,
        expectancy=expectancy,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        max_losing_streak=max_losing_streak,
        trade_count=trade_count,
        monthly_returns=monthly_returns,
        trades=trades,
        buy_count=buy_count,
        sell_count=sell_count,
        avg_mfe_pips=avg_mfe_pips,
        avg_mae_pips=avg_mae_pips,
        failed_after_half_tp_count=failed_after_half_tp_count,
    )


def _make_results_dict(
    train: FXBacktestResult | None = None,
    val: FXBacktestResult | None = None,
    test: FXBacktestResult | None = None,
) -> dict:
    return {
        "train": train or _make_result(),
        "val":   val   or _make_result(),
        "test":  test  or _make_result(),
    }


# ---------------------------------------------------------------------------
# REGIME_PATTERNS
# ---------------------------------------------------------------------------

class TestRegimePatterns:
    def test_has_8_patterns(self):
        assert len(REGIME_PATTERNS) == 8

    def test_all_pattern_has_none_filter(self):
        names = {p[0]: p[1] for p in REGIME_PATTERNS}
        assert names["all"] is None

    def test_uptrend_pattern(self):
        names = {p[0]: p[1] for p in REGIME_PATTERNS}
        assert names["uptrend"] == ["uptrend"]

    def test_range_excluded_pattern(self):
        names = {p[0]: p[1] for p in REGIME_PATTERNS}
        assert names["range_excluded"] == ["uptrend", "downtrend"]

    def test_up_excluded_same_as_down_range(self):
        names = {p[0]: p[1] for p in REGIME_PATTERNS}
        assert names["up_excluded"] == names["down+range"]


# ---------------------------------------------------------------------------
# _side_metrics
# ---------------------------------------------------------------------------

class TestSideMetrics:
    def test_long_metrics(self):
        trades = [
            {"side": "LONG", "pnl_jpy": 1000.0},
            {"side": "LONG", "pnl_jpy": -200.0},
            {"side": "SHORT", "pnl_jpy": 500.0},
        ]
        m = _side_metrics(trades, "LONG")
        assert m["count"] == 2
        assert m["win_rate"] == pytest.approx(0.5)
        assert m["profit_factor"] == pytest.approx(5.0)

    def test_short_metrics(self):
        trades = [{"side": "SHORT", "pnl_jpy": -100.0}]
        m = _side_metrics(trades, "SHORT")
        assert m["count"] == 1
        assert m["win_rate"] == 0.0

    def test_empty_returns_zeroes(self):
        m = _side_metrics([], "LONG")
        assert m["count"] == 0
        assert m["win_rate"] == 0.0
        assert m["profit_factor"] == float("inf")

    def test_all_wins_pf_is_inf(self):
        trades = [{"side": "LONG", "pnl_jpy": 500.0}]
        m = _side_metrics(trades, "LONG")
        assert m["profit_factor"] == float("inf")


# ---------------------------------------------------------------------------
# _format_monthly
# ---------------------------------------------------------------------------

class TestFormatMonthly:
    def test_sorted_output(self):
        monthly = {"2026-03": 1.0, "2026-01": -0.5, "2026-02": 0.3}
        lines = _format_monthly(monthly)
        assert "2026-01" in lines[0]
        assert "2026-03" in lines[-1]

    def test_sign_present(self):
        lines = _format_monthly({"2026-01": 1.5, "2026-02": -0.3})
        full = "\n".join(lines)
        assert "+1.50%" in full
        assert "-0.30%" in full

    def test_empty_returns_no_data(self):
        lines = _format_monthly({})
        assert "データなし" in lines[0]


# ---------------------------------------------------------------------------
# _monthly_dependence_flag
# ---------------------------------------------------------------------------

class TestMonthlyDependenceFlag:
    def test_empty_returns_na(self):
        assert _monthly_dependence_flag({}) == "n/a"

    def test_no_profit_months(self):
        flag = _monthly_dependence_flag({"2026-01": -1.0, "2026-02": -0.5})
        assert "利益月なし" in flag

    def test_one_profit_month_warns(self):
        flag = _monthly_dependence_flag({"2026-01": 5.0, "2026-02": -0.5})
        assert "集中" in flag

    def test_dispersed_returns_ok(self):
        monthly = {f"2026-{i:02d}": 0.5 for i in range(1, 7)}
        flag = _monthly_dependence_flag(monthly)
        assert flag == "分散"

    def test_top2_concentration_warns(self):
        monthly = {
            "2026-01": 10.0, "2026-02": 9.0,
            "2026-03": 0.1, "2026-04": 0.1, "2026-05": 0.1,
        }
        flag = _monthly_dependence_flag(monthly)
        assert "⚠️" in flag


# ---------------------------------------------------------------------------
# _evaluate_pattern
# ---------------------------------------------------------------------------

class TestEvaluatePattern:
    def _res(self, pf=1.2, trades=15, mdd=5.0):
        return _make_results_dict(val=_make_result(profit_factor=pf, trade_count=trades, max_drawdown_pct=mdd))

    def test_adopted_when_both_pf_above_1_1(self):
        res = self._res(pf=1.2, trades=15)
        verdict = _evaluate_pattern("up+range", res, res)
        assert verdict == "採用候補"

    def test_rejected_when_val_trades_too_low(self):
        res = self._res(trades=3)
        verdict = _evaluate_pattern("uptrend", res, res)
        assert "棄却" in verdict

    def test_rejected_when_val_pf_below_threshold(self):
        res = self._res(pf=0.9, trades=15)
        verdict = _evaluate_pattern("range", res, res)
        assert "棄却" in verdict

    def test_rejected_when_mdd_too_high(self):
        res = self._res(pf=1.3, trades=15, mdd=20.0)
        verdict = _evaluate_pattern("all", res, res)
        assert "棄却" in verdict

    def test_held_when_d1_sources_diverge(self):
        res_high = _make_results_dict(val=_make_result(profit_factor=1.5, trade_count=15))
        res_low  = _make_results_dict(val=_make_result(profit_factor=1.0, trade_count=15))
        verdict = _evaluate_pattern("all", res_high, res_low)
        assert "保留" in verdict

    def test_held_when_one_source_pf_between_1_0_and_1_1(self):
        res_high = _make_results_dict(val=_make_result(profit_factor=1.05, trade_count=15))
        verdict = _evaluate_pattern("all", res_high, res_high)
        assert verdict == "保留"


# ---------------------------------------------------------------------------
# _summary_row
# ---------------------------------------------------------------------------

class TestSummaryRow:
    def test_contains_pattern_name(self):
        res = _make_results_dict()
        row = _summary_row("uptrend", res)
        assert "uptrend" in row

    def test_contains_val_pf(self):
        res = _make_results_dict(val=_make_result(profit_factor=1.234))
        row = _summary_row("all", res)
        assert "1.234" in row


# ---------------------------------------------------------------------------
# render_lb5_regime_report
# ---------------------------------------------------------------------------

class TestRenderLb5RegimeReport:
    def _all_results(self, pf=1.2, trades=20):
        r = _make_results_dict(val=_make_result(profit_factor=pf, trade_count=trades))
        return {pat: r for pat, _ in REGIME_PATTERNS}

    def test_report_contains_header(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {"ema_fast": 20}, datetime.now(timezone.utc))
        assert "lb=5 regime_filter 診断レポート" in report

    def test_report_contains_no_execution_note(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "実注文APIは使用していません" in report

    def test_report_contains_both_d1_sources(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "resample D1" in report
        assert "direct D1" in report

    def test_report_contains_all_patterns(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        for pat, _ in REGIME_PATTERNS:
            assert pat in report

    def test_report_contains_adoption_sections(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "採用候補" in report
        assert "保留" in report
        assert "棄却" in report

    def test_report_contains_monthly_returns(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "2026-01" in report

    def test_report_contains_buy_sell_breakdown(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "BUY" in report
        assert "SELL" in report

    def test_report_notes_up_excluded_equivalence(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "up_excluded" in report
        assert "down+range" in report

    def test_report_ends_with_newline(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert report.endswith("\n")

    def test_report_no_forbidden_tokens(self):
        src = Path(__file__).resolve().parents[1] / "src" / "fx" / "lb5_regime_report.py"
        text = src.read_text(encoding="utf-8")
        for forbidden in ["place_order", "live_order", "broker_adapter", "/private/v1/order", "send_to_exchange"]:
            assert forbidden not in text, f"Forbidden token: {forbidden}"

    def test_script_no_forbidden_tokens(self):
        src = Path(__file__).resolve().parents[1] / "scripts" / "run_fx_lb5_regime_diagnostics.py"
        text = src.read_text(encoding="utf-8")
        for forbidden in ["place_order", "live_order", "broker_adapter", "/private/v1/order"]:
            assert forbidden not in text, f"Forbidden token: {forbidden}"

    def test_rejected_pattern_shows_in_rejection_section(self):
        low_trade = _make_results_dict(val=_make_result(trade_count=2))
        ok = _make_results_dict()
        results_r = {pat: (low_trade if pat == "uptrend" else ok) for pat, _ in REGIME_PATTERNS}
        results_d = {pat: (low_trade if pat == "uptrend" else ok) for pat, _ in REGIME_PATTERNS}
        report = render_lb5_regime_report(results_r, results_d, {}, datetime.now(timezone.utc))
        lines = report.splitlines()
        # 棄却セクション内に uptrend が含まれるか
        in_reject = False
        found_uptrend_in_reject = False
        for line in lines:
            if "### 棄却" in line:
                in_reject = True
            elif in_reject and line.startswith("###"):
                in_reject = False
            if in_reject and "uptrend" in line:
                found_uptrend_in_reject = True
        assert found_uptrend_in_reject

    def test_diff_table_present(self):
        results = self._all_results()
        report = render_lb5_regime_report(results, results, {}, datetime.now(timezone.utc))
        assert "resample / direct D1 VAL PF 差分" in report
