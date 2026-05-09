"""
watch_signal_evaluator / strategy_candidate (新フィールド) のテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

from src.fx.strategy_candidate import (
    WatchSignal,
    watch_signal_from_dict,
    watch_signal_to_dict,
    update_watch_signal,
    load_watch_signals,
    save_watch_signals,
)
from src.fx.watch_signal_evaluator import (
    aggregate_evaluation,
    evaluate_all_signals,
    evaluate_signal,
    monthly_summary,
    render_evaluation_report,
)
from src.reports.daily_personal_report import (
    _watch_signal_section,
    render_daily_personal_report,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_TS = "2026-01-10T00:00:00+00:00"   # data_timestamp (UTC)
_ENTRY = 155.0


def _sig(
    action: str = "buy",
    sl: Optional[float] = 154.0,
    tp: Optional[float] = 156.5,
    status: str = "open",
    resolution: str = "unresolved",
    created_at: str = "2026-01-10T09:00:00+09:00",
    signal_id: Optional[str] = None,
    **kwargs,
) -> WatchSignal:
    _id = signal_id or f"watch_test_{action}_{created_at[:10].replace('-','')}"
    return WatchSignal(
        signal_id=_id,
        strategy_name="usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all",
        created_at=created_at,
        data_timestamp=_BASE_TS,
        action=action,
        current_price=_ENTRY,
        trend_direction="UP" if action == "buy" else "DOWN",
        breakout_level=_ENTRY + 0.1 if action == "buy" else _ENTRY - 0.1,
        stop_loss=sl,
        take_profit=tp,
        risk_pips=100.0,
        reward_pips=150.0,
        rr_ratio=1.5,
        reason="test reason",
        instrument="USD_JPY",
        status=status,
        resolution=resolution,
        **kwargs,
    )


def _make_h1(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """
    (open, high, low, close) のリストから H1 DataFrame を作る。
    timestamp は _BASE_TS の 1 時間後から連番。
    """
    base = pd.Timestamp(_BASE_TS)
    rows = []
    for i, (o, h, l, c) in enumerate(bars):
        rows.append({
            "timestamp": base + pd.Timedelta(hours=i + 1),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# WatchSignal 新フィールドのデフォルト値テスト
# ---------------------------------------------------------------------------

class TestWatchSignalNewFields:
    def test_default_instrument(self):
        sig = _sig()
        assert sig.instrument == "USD_JPY"

    def test_default_status_open_for_buy(self):
        sig = _sig(action="buy")
        assert sig.status == "open"

    def test_default_resolution_unresolved(self):
        sig = _sig(action="buy")
        assert sig.resolution == "unresolved"

    def test_no_signal_status(self):
        sig = _sig(action="no_signal", status="no_signal", resolution="no_trade")
        assert sig.status == "no_signal"
        assert sig.resolution == "no_trade"

    def test_mfe_mae_default_none(self):
        sig = _sig()
        assert sig.mfe_pips is None
        assert sig.mae_pips is None

    def test_resolution_bar_count_default_none(self):
        sig = _sig()
        assert sig.resolution_bar_count is None


# ---------------------------------------------------------------------------
# watch_signal_from_dict 後方互換
# ---------------------------------------------------------------------------

class TestWatchSignalFromDictBackwardCompat:
    def _old_dict(self) -> dict:
        """旧フォーマット（instrument/status/resolution なし）"""
        return {
            "signal_id": "watch_old_20260101_buy",
            "strategy_name": "usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all",
            "created_at": "2026-01-01T09:00:00+09:00",
            "data_timestamp": "2026-01-01T00:00:00+00:00",
            "action": "buy",
            "current_price": 155.0,
            "trend_direction": "UP",
            "breakout_level": 155.5,
            "stop_loss": 154.0,
            "take_profit": 156.5,
            "risk_pips": 100.0,
            "reward_pips": 150.0,
            "rr_ratio": 1.5,
            "reason": "old signal",
            "metadata": {},
        }

    def test_loads_without_new_fields(self):
        sig = watch_signal_from_dict(self._old_dict())
        assert sig.instrument == "USD_JPY"   # default
        assert sig.status == "open"           # default
        assert sig.resolution == "unresolved" # default

    def test_unknown_fields_ignored(self):
        d = self._old_dict()
        d["unknown_future_field"] = "some_value"
        sig = watch_signal_from_dict(d)
        assert sig.signal_id == "watch_old_20260101_buy"

    def test_roundtrip_with_new_fields(self):
        sig = _sig(status="resolved", resolution="tp_hit", mfe_pips=45.0, mae_pips=12.0)
        d = watch_signal_to_dict(sig)
        sig2 = watch_signal_from_dict(d)
        assert sig2.status == "resolved"
        assert sig2.resolution == "tp_hit"
        assert sig2.mfe_pips == 45.0


# ---------------------------------------------------------------------------
# update_watch_signal
# ---------------------------------------------------------------------------

class TestUpdateWatchSignal:
    def test_updates_existing(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        sig = _sig(signal_id="w1")
        payload = {"signals": [watch_signal_to_dict(sig)]}
        save_watch_signals(payload, path)

        updated = replace(sig, status="resolved", resolution="tp_hit")
        update_watch_signal(updated, path)

        loaded = load_watch_signals(path)
        assert len(loaded["signals"]) == 1
        assert loaded["signals"][0]["status"] == "resolved"
        assert loaded["signals"][0]["resolution"] == "tp_hit"

    def test_appends_when_not_found(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        sig1 = _sig(signal_id="w1")
        payload = {"signals": [watch_signal_to_dict(sig1)]}
        save_watch_signals(payload, path)

        sig2 = _sig(signal_id="w2")
        update_watch_signal(sig2, path)

        loaded = load_watch_signals(path)
        assert len(loaded["signals"]) == 2


# ---------------------------------------------------------------------------
# evaluate_signal
# ---------------------------------------------------------------------------

class TestEvaluateSignal:
    # --- buy: TP 到達 ---
    def test_buy_tp_hit(self):
        sig = _sig(action="buy", sl=154.0, tp=156.5)
        df = _make_h1([
            (155.0, 155.5, 154.9, 155.2),   # bar1: no hit
            (155.2, 156.6, 155.1, 156.5),   # bar2: high >= tp
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "tp_hit"
        assert result.status == "resolved"
        assert result.resolution_bar_count == 2

    # --- buy: SL 到達 ---
    def test_buy_sl_hit(self):
        sig = _sig(action="buy", sl=154.0, tp=156.5)
        df = _make_h1([
            (155.0, 155.3, 153.9, 154.5),   # bar1: low <= sl
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "sl_hit"
        assert result.status == "resolved"
        assert result.resolution_bar_count == 1

    # --- buy: 同一足で ambiguous ---
    def test_buy_ambiguous(self):
        sig = _sig(action="buy", sl=154.0, tp=156.5)
        df = _make_h1([
            (155.0, 157.0, 153.5, 155.0),   # high > tp AND low < sl
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "ambiguous"
        assert result.status == "resolved"

    # --- buy: timeout ---
    def test_buy_timeout(self):
        sig = _sig(action="buy", sl=154.0, tp=156.5)
        # 24本すべて到達なし
        bars = [(155.0, 155.3, 154.5, 155.1)] * 24
        df = _make_h1(bars)
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "timeout"
        assert result.status == "resolved"
        assert result.resolution_bar_count == 24

    # --- buy: データ不足 (open のまま) ---
    def test_buy_insufficient_data(self):
        sig = _sig(action="buy", sl=154.0, tp=156.5)
        df = _make_h1([])  # data_timestamp 以降のバーなし
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.status == "open"
        assert result.resolution == "unresolved"

    # --- sell: TP 到達 ---
    def test_sell_tp_hit(self):
        sig = _sig(action="sell", sl=156.5, tp=153.5)
        df = _make_h1([
            (155.0, 155.2, 153.4, 153.8),   # bar1: low <= tp
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "tp_hit"

    # --- sell: SL 到達 ---
    def test_sell_sl_hit(self):
        sig = _sig(action="sell", sl=156.5, tp=153.5)
        df = _make_h1([
            (155.0, 156.6, 154.8, 155.5),   # bar1: high >= sl
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "sl_hit"

    # --- sell: ambiguous ---
    def test_sell_ambiguous(self):
        sig = _sig(action="sell", sl=156.5, tp=153.5)
        df = _make_h1([
            (155.0, 157.0, 153.0, 155.0),   # both hit
        ])
        result = evaluate_signal(sig, df, timeout_bars=24)
        assert result.resolution == "ambiguous"

    # --- no_signal: no_trade ---
    def test_no_signal_action(self):
        sig = _sig(action="no_signal", sl=None, tp=None, status="no_signal", resolution="no_trade")
        df = _make_h1([(155.0, 155.5, 154.5, 155.1)])
        result = evaluate_signal(sig, df)
        assert result.status == "no_signal"
        assert result.resolution == "no_trade"

    # --- already resolved: unchanged ---
    def test_already_resolved(self):
        sig = _sig(status="resolved", resolution="tp_hit")
        df = _make_h1([(155.0, 157.0, 154.0, 156.0)])
        result = evaluate_signal(sig, df)
        assert result.resolution == "tp_hit"  # 変更なし

    # --- no SL/TP: open のまま ---
    def test_missing_sl_tp(self):
        sig = _sig(action="buy", sl=None, tp=None)
        df = _make_h1([(155.0, 158.0, 154.0, 156.0)])
        result = evaluate_signal(sig, df)
        assert result.status == "open"
        assert result.resolution == "unresolved"

    # --- MFE / MAE 計算確認 (buy) ---
    def test_mfe_mae_buy(self):
        sig = _sig(action="buy", sl=154.0, tp=160.0)  # tp far away
        df = _make_h1([
            (155.0, 155.8, 154.8, 155.2),   # mfe=0.8/0.01=80, mae=0.2/0.01=20
            (155.2, 156.0, 154.5, 155.8),   # mfe=1.0/0.01=100, mae=0.5/0.01=50
        ])
        result = evaluate_signal(sig, df, timeout_bars=2)
        assert result.resolution == "timeout"
        assert result.mfe_pips == pytest.approx(100.0)
        assert result.mae_pips == pytest.approx(50.0)

    # --- MFE / MAE 計算確認 (sell) ---
    def test_mfe_mae_sell(self):
        sig = _sig(action="sell", sl=157.0, tp=152.0)
        df = _make_h1([
            (155.0, 155.5, 154.2, 154.5),   # mfe=(155-154.2)/0.01=80, mae=(155.5-155)/0.01=50
        ])
        result = evaluate_signal(sig, df, timeout_bars=1)
        assert result.resolution == "timeout"
        assert result.mfe_pips == pytest.approx(80.0)
        assert result.mae_pips == pytest.approx(50.0)

    def test_timeout_bars_respected(self):
        sig = _sig(action="buy", sl=154.0, tp=160.0)
        bars = [(155.0, 155.3, 154.5, 155.1)] * 10
        df = _make_h1(bars)
        # timeout_bars=5: 5本後にタイムアウト
        result = evaluate_signal(sig, df, timeout_bars=5)
        assert result.resolution == "timeout"
        assert result.resolution_bar_count == 5

    def test_empty_data_timestamp(self):
        sig = replace(_sig(), data_timestamp="")
        df = _make_h1([(155.0, 156.0, 154.0, 155.5)])
        result = evaluate_signal(sig, df)
        assert result.status == "open"


# ---------------------------------------------------------------------------
# evaluate_all_signals
# ---------------------------------------------------------------------------

class TestEvaluateAllSignals:
    def test_resolved_unchanged(self):
        sig = _sig(status="resolved", resolution="sl_hit", signal_id="r1")
        df = _make_h1([(155.0, 158.0, 154.0, 156.0)])
        results = evaluate_all_signals([sig], df)
        assert results[0].resolution == "sl_hit"

    def test_no_signal_marked(self):
        sig = _sig(action="no_signal", sl=None, tp=None, signal_id="ns1")
        df = _make_h1([])
        results = evaluate_all_signals([sig], df)
        assert results[0].status == "no_signal"
        assert results[0].resolution == "no_trade"

    def test_mixed_batch(self):
        buy_sig = _sig(action="buy", sl=154.0, tp=156.5, signal_id="buy1")
        no_sig = _sig(action="no_signal", sl=None, tp=None, signal_id="ns1")
        resolved = _sig(status="resolved", resolution="tp_hit", signal_id="res1")

        df = _make_h1([
            (155.0, 156.6, 154.5, 156.0),  # buy_sig → tp_hit
        ])
        results = evaluate_all_signals([buy_sig, no_sig, resolved], df)

        sig_map = {r.signal_id: r for r in results}
        assert sig_map["buy1"].resolution == "tp_hit"
        assert sig_map["ns1"].status == "no_signal"
        assert sig_map["res1"].resolution == "tp_hit"  # unchanged

    def test_returns_same_count(self):
        sigs = [_sig(signal_id=f"s{i}") for i in range(5)]
        df = _make_h1([])
        results = evaluate_all_signals(sigs, df)
        assert len(results) == 5


# ---------------------------------------------------------------------------
# aggregate_evaluation
# ---------------------------------------------------------------------------

class TestAggregateEvaluation:
    def _make_set(self) -> list[WatchSignal]:
        return [
            _sig(action="buy", status="resolved", resolution="tp_hit", mfe_pips=50.0, mae_pips=10.0, resolution_bar_count=5, signal_id="s1"),
            _sig(action="buy", status="resolved", resolution="sl_hit", mfe_pips=5.0, mae_pips=40.0, resolution_bar_count=3, signal_id="s2"),
            _sig(action="sell", status="resolved", resolution="tp_hit", mfe_pips=30.0, mae_pips=8.0, resolution_bar_count=10, signal_id="s3"),
            _sig(action="sell", status="resolved", resolution="ambiguous", mfe_pips=20.0, mae_pips=20.0, resolution_bar_count=1, signal_id="s4"),
            _sig(action="buy", status="resolved", resolution="timeout", mfe_pips=15.0, mae_pips=12.0, resolution_bar_count=24, signal_id="s5"),
            _sig(action="no_signal", status="no_signal", resolution="no_trade", sl=None, tp=None, signal_id="s6"),
            _sig(action="buy", status="open", resolution="unresolved", signal_id="s7"),
        ]

    def test_total_signals(self):
        stats = aggregate_evaluation(self._make_set())
        assert stats["total_signals"] == 7

    def test_actionable_signals(self):
        stats = aggregate_evaluation(self._make_set())
        assert stats["actionable_signals"] == 6  # buy*4 + sell*2

    def test_buy_sell_counts(self):
        stats = aggregate_evaluation(self._make_set())
        assert stats["buy_count"] == 4
        assert stats["sell_count"] == 2

    def test_tp_sl_counts(self):
        stats = aggregate_evaluation(self._make_set())
        assert stats["tp_hit"] == 2
        assert stats["sl_hit"] == 1
        assert stats["ambiguous"] == 1
        assert stats["timeout"] == 1

    def test_open_count(self):
        stats = aggregate_evaluation(self._make_set())
        assert stats["open"] == 1

    def test_win_rate(self):
        stats = aggregate_evaluation(self._make_set())
        # decisive = tp(2) + sl(1) + amb(1) = 4
        # win_rate = 2/4 = 0.5
        assert stats["win_rate"] == pytest.approx(0.5)

    def test_win_rate_none_when_no_decisive(self):
        sigs = [_sig(action="buy", status="open", resolution="unresolved", signal_id="s1")]
        stats = aggregate_evaluation(sigs)
        assert stats["win_rate"] is None

    def test_avg_mfe_mae(self):
        stats = aggregate_evaluation(self._make_set())
        # mfe: 50, 5, 30, 20, 15 → avg = 24.0
        assert stats["avg_mfe"] == pytest.approx(24.0)
        # mae: 10, 40, 8, 20, 12 → avg = 18.0
        assert stats["avg_mae"] == pytest.approx(18.0)

    def test_avg_time_to_resolution(self):
        stats = aggregate_evaluation(self._make_set())
        # resolution_bar_count: 5, 3, 10, 1, 24 → avg = 8.6
        assert stats["avg_time_to_resolution"] == pytest.approx(8.6)

    def test_empty(self):
        stats = aggregate_evaluation([])
        assert stats["total_signals"] == 0
        assert stats["win_rate"] is None
        assert stats["avg_mfe"] is None


# ---------------------------------------------------------------------------
# monthly_summary
# ---------------------------------------------------------------------------

class TestMonthlySummary:
    def test_groups_by_month(self):
        sigs = [
            _sig(signal_id="a", created_at="2026-01-10T09:00:00+09:00", status="resolved", resolution="tp_hit"),
            _sig(signal_id="b", created_at="2026-01-15T09:00:00+09:00", status="resolved", resolution="sl_hit"),
            _sig(signal_id="c", created_at="2026-02-05T09:00:00+09:00", status="resolved", resolution="tp_hit"),
        ]
        rows = monthly_summary(sigs)
        assert len(rows) == 2
        months = [r["month"] for r in rows]
        assert "2026-01" in months
        assert "2026-02" in months

    def test_win_rate_per_month(self):
        sigs = [
            _sig(signal_id="a", created_at="2026-01-10T09:00:00+09:00", status="resolved", resolution="tp_hit"),
            _sig(signal_id="b", created_at="2026-01-15T09:00:00+09:00", status="resolved", resolution="tp_hit"),
            _sig(signal_id="c", created_at="2026-01-20T09:00:00+09:00", status="resolved", resolution="sl_hit"),
        ]
        rows = monthly_summary(sigs)
        jan = rows[0]
        assert jan["month"] == "2026-01"
        assert jan["tp_hit"] == 2
        assert jan["sl_hit"] == 1
        assert jan["win_rate"] == pytest.approx(2 / 3, abs=1e-3)

    def test_no_signal_excluded(self):
        sigs = [
            _sig(signal_id="ns", action="no_signal", sl=None, tp=None,
                 status="no_signal", resolution="no_trade",
                 created_at="2026-01-10T09:00:00+09:00"),
        ]
        rows = monthly_summary(sigs)
        assert rows == []

    def test_win_rate_none_when_no_decisive(self):
        sigs = [_sig(signal_id="s1", created_at="2026-01-10T09:00:00+09:00",
                     status="resolved", resolution="timeout")]
        rows = monthly_summary(sigs)
        assert rows[0]["win_rate"] is None


# ---------------------------------------------------------------------------
# render_evaluation_report
# ---------------------------------------------------------------------------

class TestRenderEvaluationReport:
    def _make_sigs(self) -> list[WatchSignal]:
        return [
            _sig(signal_id="s1", action="buy", status="resolved", resolution="tp_hit",
                 mfe_pips=50.0, mae_pips=10.0, resolution_bar_count=5),
            _sig(signal_id="s2", action="sell", status="resolved", resolution="sl_hit",
                 mfe_pips=5.0, mae_pips=30.0, resolution_bar_count=2),
            _sig(signal_id="s3", action="buy", status="open", resolution="unresolved"),
        ]

    def test_contains_header(self):
        report = render_evaluation_report(self._make_sigs(), datetime.now(timezone.utc))
        assert "# FX Watch Candidate 評価レポート" in report

    def test_contains_summary_table(self):
        report = render_evaluation_report(self._make_sigs(), datetime.now(timezone.utc))
        assert "集計サマリー" in report
        assert "win_rate" in report

    def test_contains_monthly_section(self):
        report = render_evaluation_report(self._make_sigs(), datetime.now(timezone.utc))
        assert "月次サマリー" in report

    def test_contains_signal_details(self):
        report = render_evaluation_report(self._make_sigs(), datetime.now(timezone.utc))
        assert "シグナル詳細" in report
        assert "s1" in report
        assert "s2" in report

    def test_no_order_api_note(self):
        report = render_evaluation_report(self._make_sigs(), datetime.now(timezone.utc))
        assert "実注文なし" in report
        assert "昇格しない" in report

    def test_empty_signals(self):
        report = render_evaluation_report([], datetime.now(timezone.utc))
        assert "# FX Watch Candidate 評価レポート" in report
        assert "none" in report  # 月次サマリー: none

    def test_timeout_bars_shown(self):
        report = render_evaluation_report([], datetime.now(timezone.utc), timeout_bars=48)
        assert "timeout_bars: 48" in report

    def test_ends_with_newline(self):
        report = render_evaluation_report([], datetime.now(timezone.utc))
        assert report.endswith("\n")


# ---------------------------------------------------------------------------
# _watch_signal_section with unresolved_count
# ---------------------------------------------------------------------------

class TestWatchSignalSectionUnresolvedCount:
    def _make_watch_signal(self, **kwargs) -> WatchSignal:
        return _sig(**kwargs)

    def test_unresolved_count_shown(self):
        lines = _watch_signal_section([], unresolved_count=5)
        text = "\n".join(lines)
        assert "未解決シグナル: 5 件" in text

    def test_unresolved_count_zero(self):
        lines = _watch_signal_section([], unresolved_count=0)
        text = "\n".join(lines)
        assert "未解決シグナル: 0 件" in text

    def test_default_unresolved_count(self):
        lines = _watch_signal_section([])
        text = "\n".join(lines)
        assert "未解決シグナル:" in text


# ---------------------------------------------------------------------------
# render_daily_personal_report with watch_unresolved_count
# ---------------------------------------------------------------------------

class TestDailyReportWatchUnresolvedCount:
    def _render(self, watch_signals=None, count: int = 0) -> str:
        from datetime import date
        return render_daily_personal_report(
            proposals=[],
            target_date=date(2026, 5, 9),
            generated_at=datetime(2026, 5, 9, 9, 0, 0, tzinfo=timezone.utc),
            stop_trading_active=False,
            dry_run=False,
            read_only=False,
            watch_signals=watch_signals,
            watch_unresolved_count=count,
        )

    def test_unresolved_count_in_report(self):
        report = self._render(count=3)
        assert "未解決シグナル: 3 件" in report

    def test_zero_count_default(self):
        report = self._render()
        assert "未解決シグナル: 0 件" in report

    def test_signal_plus_count(self):
        sig = _sig(action="buy", signal_id="test_w1")
        report = self._render(watch_signals=[sig], count=2)
        assert "未解決シグナル: 2 件" in report
        assert "BUY" in report


# ---------------------------------------------------------------------------
# candidate_signal_runner: new fields set correctly
# ---------------------------------------------------------------------------

class TestCandidateSignalRunnerNewFields:
    def _make_dfs(self) -> tuple:
        import numpy as np
        n_h1, n_d1 = 500, 200
        rng = np.random.default_rng(99)
        ts_h1 = pd.date_range("2024-01-01", periods=n_h1, freq="h", tz="UTC")
        close_h1 = 150.0 + np.cumsum(rng.normal(0, 0.05, n_h1))
        df_h1 = pd.DataFrame({
            "timestamp": ts_h1,
            "open": close_h1 - 0.02,
            "high": close_h1 + 0.05,
            "low": close_h1 - 0.05,
            "close": close_h1,
            "volume": np.ones(n_h1) * 1000,
        })
        ts_d1 = pd.date_range("2024-01-01", periods=n_d1, freq="D", tz="UTC")
        close_d1 = 150.0 + np.cumsum(rng.normal(0, 0.2, n_d1))
        df_d1 = pd.DataFrame({
            "timestamp": ts_d1,
            "open": close_d1 - 0.05,
            "high": close_d1 + 0.1,
            "low": close_d1 - 0.1,
            "close": close_d1,
            "volume": np.ones(n_d1) * 1000,
        })
        return df_h1, df_d1

    def test_instrument_set(self):
        from src.fx.candidate_signal_runner import run_candidate_signal
        df_h1, df_d1 = self._make_dfs()
        sig = run_candidate_signal(df_h1, df_d1)
        assert sig.instrument == "USD_JPY"

    def test_status_open_for_actionable(self):
        from src.fx.candidate_signal_runner import run_candidate_signal
        df_h1, df_d1 = self._make_dfs()
        sig = run_candidate_signal(df_h1, df_d1)
        if sig.action in ("buy", "sell"):
            assert sig.status == "open"
            assert sig.resolution == "unresolved"

    def test_status_no_signal_for_empty(self):
        from src.fx.candidate_signal_runner import run_candidate_signal
        _, df_d1 = self._make_dfs()
        sig = run_candidate_signal(pd.DataFrame(), df_d1)
        assert sig.status == "no_signal"
        assert sig.resolution == "no_trade"
