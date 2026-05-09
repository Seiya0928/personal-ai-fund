"""
run_daily_personal_report / daily_watch_workflow のユニットテスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.fx.daily_watch_workflow import (
    compute_unresolved_count,
    compute_watch_eval_stats,
    load_safety_flags,
)
from src.fx.strategy_candidate import WatchSignal
from src.reports.daily_personal_report import (
    _watch_signal_section,
    render_daily_personal_report,
)

JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(
    signal_id: str = "watch_test_20260509_buy",
    action: str = "buy",
    status: str = "open",
    resolution: str = "unresolved",
    tp_hit: bool = False,
) -> WatchSignal:
    return WatchSignal(
        signal_id=signal_id,
        strategy_name="usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all",
        created_at="2026-05-09T09:00:00+09:00",
        data_timestamp="2026-05-09T00:00:00+00:00",
        action=action,
        current_price=154.500,
        trend_direction="UP",
        breakout_level=155.000,
        stop_loss=153.000,
        take_profit=157.000,
        risk_pips=150.0,
        reward_pips=250.0,
        rr_ratio=1.67,
        reason="テスト用シグナル",
        instrument="USD_JPY",
        status=status,
        resolution="tp_hit" if tp_hit else resolution,
    )


def _make_signals_json(signals: list[dict]) -> dict:
    return {"signals": signals}


def _sig_to_dict(sig: WatchSignal) -> dict:
    from src.fx.strategy_candidate import watch_signal_to_dict
    return watch_signal_to_dict(sig)


# ---------------------------------------------------------------------------
# load_safety_flags
# ---------------------------------------------------------------------------

class TestLoadSafetyFlags:
    def test_no_stop_trading_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("READ_ONLY", "true")
        stop, dry, ro = load_safety_flags(root=tmp_path)
        assert stop is False
        assert dry is True
        assert ro is True

    def test_stop_trading_file_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("READ_ONLY", "false")
        (tmp_path / "STOP_TRADING").touch()
        stop, dry, ro = load_safety_flags(root=tmp_path)
        assert stop is True
        assert dry is False
        assert ro is False

    def test_dry_run_false_variants(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("false", "0", "no"):
            monkeypatch.setenv("DRY_RUN", val)
            _, dry, _ = load_safety_flags(root=tmp_path)
            assert dry is False, f"DRY_RUN={val!r} should be False"

    def test_dry_run_true_variants(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("true", "1", "yes", "TRUE"):
            monkeypatch.setenv("DRY_RUN", val)
            _, dry, _ = load_safety_flags(root=tmp_path)
            assert dry is True, f"DRY_RUN={val!r} should be True"

    def test_read_only_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("READ_ONLY", "0")
        _, _, ro = load_safety_flags(root=tmp_path)
        assert ro is False


# ---------------------------------------------------------------------------
# compute_watch_eval_stats
# ---------------------------------------------------------------------------

class TestComputeWatchEvalStats:
    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "fx_watch_signals.json"
        path.write_text(json.dumps({"signals": []}), encoding="utf-8")
        stats = compute_watch_eval_stats(signals_path=path)
        assert stats == {}

    def test_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "fx_watch_signals.json"
        stats = compute_watch_eval_stats(signals_path=path)
        assert stats == {}

    def test_with_signals(self, tmp_path: Path) -> None:
        tp_sig = _sig_to_dict(_make_signal("s1", action="buy", status="resolved", tp_hit=True))
        sl_sig = _sig_to_dict(_make_signal("s2", action="sell", status="resolved", resolution="sl_hit"))
        path = tmp_path / "fx_watch_signals.json"
        path.write_text(
            json.dumps(_make_signals_json([tp_sig, sl_sig])),
            encoding="utf-8",
        )
        stats = compute_watch_eval_stats(signals_path=path)
        assert stats["tp_hit"] == 1
        assert stats["sl_hit"] == 1
        assert stats["actionable_signals"] == 2
        assert stats["win_rate"] == pytest.approx(0.5, abs=0.01)

    def test_returns_aggregate_keys(self, tmp_path: Path) -> None:
        sig = _sig_to_dict(_make_signal("s1", action="buy", status="open"))
        path = tmp_path / "fx_watch_signals.json"
        path.write_text(json.dumps(_make_signals_json([sig])), encoding="utf-8")
        stats = compute_watch_eval_stats(signals_path=path)
        expected_keys = {
            "total_signals", "actionable_signals", "buy_count", "sell_count",
            "tp_hit", "sl_hit", "timeout", "ambiguous", "open", "win_rate",
            "avg_mfe", "avg_mae", "avg_time_to_resolution",
        }
        assert expected_keys == set(stats.keys())


# ---------------------------------------------------------------------------
# compute_unresolved_count
# ---------------------------------------------------------------------------

class TestComputeUnresolvedCount:
    def test_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "fx_watch_signals.json"
        assert compute_unresolved_count(signals_path=path) == 0

    def test_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "fx_watch_signals.json"
        path.write_text(json.dumps({"signals": []}), encoding="utf-8")
        assert compute_unresolved_count(signals_path=path) == 0

    def test_counts_only_open(self, tmp_path: Path) -> None:
        open1 = _sig_to_dict(_make_signal("s1", action="buy", status="open"))
        open2 = _sig_to_dict(_make_signal("s2", action="sell", status="open"))
        resolved = _sig_to_dict(_make_signal("s3", action="buy", status="resolved", tp_hit=True))
        no_sig = _sig_to_dict(_make_signal("s4", action="no_signal", status="no_signal"))
        path = tmp_path / "fx_watch_signals.json"
        path.write_text(
            json.dumps(_make_signals_json([open1, open2, resolved, no_sig])),
            encoding="utf-8",
        )
        assert compute_unresolved_count(signals_path=path) == 2


# ---------------------------------------------------------------------------
# _watch_signal_section with eval_stats
# ---------------------------------------------------------------------------

class TestWatchSignalSection:
    def test_no_eval_stats(self) -> None:
        sig = _make_signal()
        lines = _watch_signal_section([sig], unresolved_count=1)
        text = "\n".join(lines)
        assert "直近評価サマリー" not in text
        assert "usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all" in text

    def test_with_eval_stats(self) -> None:
        sig = _make_signal()
        stats = {
            "tp_hit": 5, "sl_hit": 3, "timeout": 2,
            "ambiguous": 1, "open": 2, "win_rate": 0.556,
        }
        lines = _watch_signal_section([sig], unresolved_count=2, eval_stats=stats)
        text = "\n".join(lines)
        assert "直近評価サマリー" in text
        assert "55.6%" in text
        assert "| 5 | 3 | 2 | 1 | 2 |" in text

    def test_eval_stats_none_win_rate(self) -> None:
        sig = _make_signal()
        stats = {
            "tp_hit": 0, "sl_hit": 0, "timeout": 1,
            "ambiguous": 0, "open": 3, "win_rate": None,
        }
        lines = _watch_signal_section([sig], eval_stats=stats)
        text = "\n".join(lines)
        assert "n/a" in text

    def test_empty_signals_with_eval_stats(self) -> None:
        stats = {"tp_hit": 2, "sl_hit": 1, "timeout": 0, "ambiguous": 0, "open": 0, "win_rate": 0.667}
        lines = _watch_signal_section([], eval_stats=stats)
        text = "\n".join(lines)
        assert "直近評価サマリー" in text
        assert "- none" in text

    def test_empty_eval_stats_dict_not_rendered(self) -> None:
        # eval_stats={} (falsy) は表示しない
        lines = _watch_signal_section([], eval_stats={})
        text = "\n".join(lines)
        assert "直近評価サマリー" not in text


# ---------------------------------------------------------------------------
# render_daily_personal_report with watch_eval_stats
# ---------------------------------------------------------------------------

class TestRenderDailyPersonalReport:
    def _base_kwargs(self) -> dict:
        return {
            "target_date": date(2026, 5, 9),
            "generated_at": datetime(2026, 5, 9, 9, 0, 0, tzinfo=JST),
            "stop_trading_active": False,
            "dry_run": True,
            "read_only": True,
        }

    def test_no_watch_signals(self) -> None:
        content = render_daily_personal_report([], **self._base_kwargs())
        assert "Daily Personal Report 2026-05-09" in content
        assert "FX Watch Candidate" in content
        assert "直近評価サマリー" not in content

    def test_with_watch_signals(self) -> None:
        sig = _make_signal()
        content = render_daily_personal_report(
            [],
            **self._base_kwargs(),
            watch_signals=[sig],
            watch_unresolved_count=1,
        )
        assert "usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all" in content
        assert "未解決シグナル: 1 件" in content

    def test_with_watch_eval_stats(self) -> None:
        sig = _make_signal()
        stats = {
            "tp_hit": 5, "sl_hit": 3, "timeout": 2,
            "ambiguous": 1, "open": 2, "win_rate": 0.556,
        }
        content = render_daily_personal_report(
            [],
            **self._base_kwargs(),
            watch_signals=[sig],
            watch_unresolved_count=2,
            watch_eval_stats=stats,
        )
        assert "直近評価サマリー" in content
        assert "55.6%" in content

    def test_watch_eval_stats_none(self) -> None:
        sig = _make_signal()
        content = render_daily_personal_report(
            [],
            **self._base_kwargs(),
            watch_signals=[sig],
            watch_eval_stats=None,
        )
        assert "直近評価サマリー" not in content

    def test_full_report_structure(self) -> None:
        sig = _make_signal()
        stats = {"tp_hit": 1, "sl_hit": 1, "timeout": 0, "ambiguous": 0, "open": 0, "win_rate": 0.5}
        content = render_daily_personal_report(
            [],
            **self._base_kwargs(),
            watch_signals=[sig],
            watch_unresolved_count=0,
            watch_eval_stats=stats,
        )
        # 主要セクションが揃っているか確認
        assert "## 安全フラグ" in content
        assert "## FX Watch Candidate" in content
        assert "直近評価サマリー" in content
        assert "## 提案サマリー" in content
        assert content.endswith("\n")
