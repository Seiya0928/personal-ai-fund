"""
strategy_candidate / candidate_signal_runner / daily_personal_report の統合テスト
実注文なし・研究用のみ
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.fx.candidate_signal_runner import (
    _action_from_signal,
    _build_reason,
    _empty_signal,
    _optional_float,
    _pips,
    run_candidate_signal,
)
from src.fx.strategy_candidate import (
    DEFAULT_WATCH_SIGNALS_PATH,
    USDJPY_PRIMARY_CANDIDATE,
    StrategyCandidateConfig,
    WatchSignal,
    list_watch_signals,
    load_watch_signals,
    save_watch_signal,
    save_watch_signals,
    watch_signal_from_dict,
    watch_signal_to_dict,
)
from src.reports.daily_personal_report import (
    _watch_signal_section,
    render_daily_personal_report,
)

# ---------------------------------------------------------------------------
# StrategyCandidateConfig
# ---------------------------------------------------------------------------

class TestStrategyCandidateConfig:
    def test_default_values(self):
        cfg = StrategyCandidateConfig()
        assert cfg.strategy_name == "usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all"
        assert cfg.timeframe_entry == "H1"
        assert cfg.timeframe_trend == "D1"
        assert cfg.ema_fast == 20
        assert cfg.ema_slow == 200
        assert cfg.breakout_lookback == 5
        assert cfg.atr_sl_multiplier == 1.5
        assert cfg.rr_ratio == 1.5
        assert cfg.direction == "both"
        assert cfg.regime_filter == "all"
        assert cfg.status == "watch_candidate"

    def test_frozen(self):
        cfg = StrategyCandidateConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.ema_fast = 50  # type: ignore[misc]

    def test_singleton(self):
        assert USDJPY_PRIMARY_CANDIDATE is USDJPY_PRIMARY_CANDIDATE
        assert USDJPY_PRIMARY_CANDIDATE.ema_fast == 20

    def test_custom_config(self):
        cfg = StrategyCandidateConfig(
            strategy_name="custom",
            direction="long_only",
        )
        assert cfg.strategy_name == "custom"
        assert cfg.direction == "long_only"
        assert cfg.ema_fast == 20  # default preserved


# ---------------------------------------------------------------------------
# WatchSignal
# ---------------------------------------------------------------------------

def _make_watch_signal(**kwargs) -> WatchSignal:
    defaults = dict(
        signal_id="watch_test_20260101_buy",
        strategy_name="usdjpy_h1_d1_ema20_200_lb5_sl1_5_rr1_5_all",
        created_at="2026-01-01T09:00:00+09:00",
        data_timestamp="2026-01-01T00:00:00+00:00",
        action="buy",
        current_price=155.123,
        trend_direction="UP",
        breakout_level=155.500,
        stop_loss=154.500,
        take_profit=156.500,
        risk_pips=62.3,
        reward_pips=137.7,
        rr_ratio=2.21,
        reason="EMA20 > EMA200 + ブレイクアウト",
    )
    defaults.update(kwargs)
    return WatchSignal(**defaults)


class TestWatchSignal:
    def test_creation(self):
        sig = _make_watch_signal()
        assert sig.action == "buy"
        assert sig.current_price == pytest.approx(155.123)
        assert sig.trend_direction == "UP"

    def test_optional_none_fields(self):
        sig = _make_watch_signal(
            action="no_signal",
            breakout_level=None,
            stop_loss=None,
            take_profit=None,
            risk_pips=None,
            reward_pips=None,
            rr_ratio=None,
        )
        assert sig.breakout_level is None
        assert sig.stop_loss is None
        assert sig.rr_ratio is None

    def test_to_dict_roundtrip(self):
        sig = _make_watch_signal()
        d = watch_signal_to_dict(sig)
        assert isinstance(d, dict)
        sig2 = watch_signal_from_dict(d)
        assert sig2.signal_id == sig.signal_id
        assert sig2.current_price == sig.current_price
        assert sig2.rr_ratio == sig.rr_ratio

    def test_metadata_default_empty(self):
        sig = _make_watch_signal()
        assert isinstance(sig.metadata, dict)

    def test_metadata_custom(self):
        sig = _make_watch_signal(metadata={"ema_fast_value": 155.0})
        assert sig.metadata["ema_fast_value"] == 155.0


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------

class TestWatchSignalStorage:
    def test_load_empty_when_file_missing(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        payload = load_watch_signals(path)
        assert payload == {"signals": []}

    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        payload = {"signals": [{"signal_id": "x"}]}
        save_watch_signals(payload, path)
        loaded = load_watch_signals(path)
        assert loaded["signals"][0]["signal_id"] == "x"

    def test_save_watch_signal_new(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        sig = _make_watch_signal()
        stored, is_new = save_watch_signal(sig, path)
        assert is_new is True
        assert stored["signal_id"] == sig.signal_id

    def test_save_watch_signal_duplicate_skipped(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        sig = _make_watch_signal()
        save_watch_signal(sig, path)
        stored, is_new = save_watch_signal(sig, path)
        assert is_new is False

    def test_list_watch_signals(self, tmp_path: Path):
        path = tmp_path / "signals.json"
        sig1 = _make_watch_signal(signal_id="w1")
        sig2 = _make_watch_signal(signal_id="w2")
        save_watch_signal(sig1, path)
        save_watch_signal(sig2, path)
        lst = list_watch_signals(path)
        assert len(lst) == 2
        ids = {d["signal_id"] for d in lst}
        assert ids == {"w1", "w2"}

    def test_load_invalid_raises(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text('{"signals": "not_a_list"}', encoding="utf-8")
        with pytest.raises(ValueError, match="不正"):
            load_watch_signals(path)


# ---------------------------------------------------------------------------
# Helpers in candidate_signal_runner
# ---------------------------------------------------------------------------

class TestActionFromSignal:
    @pytest.mark.parametrize("direction,expected", [
        ("both", "buy"),
        ("long_only", "buy"),
        ("short_only", "skip"),
    ])
    def test_signal_1(self, direction, expected):
        assert _action_from_signal(1, direction) == expected

    @pytest.mark.parametrize("direction,expected", [
        ("both", "sell"),
        ("short_only", "sell"),
        ("long_only", "skip"),
    ])
    def test_signal_minus1(self, direction, expected):
        assert _action_from_signal(-1, direction) == expected

    def test_signal_0(self):
        assert _action_from_signal(0, "both") == "no_signal"
        assert _action_from_signal(0, "long_only") == "no_signal"


class TestPips:
    def test_basic(self):
        assert _pips(1.0) == pytest.approx(100.0)
        assert _pips(0.5) == pytest.approx(50.0)

    def test_none(self):
        assert _pips(None) is None

    def test_nan(self):
        assert _pips(float("nan")) is None


class TestOptionalFloat:
    def test_valid(self):
        assert _optional_float(1.5) == pytest.approx(1.5)

    def test_none(self):
        assert _optional_float(None) is None

    def test_nan(self):
        assert _optional_float(float("nan")) is None

    def test_pd_nan(self):
        import pandas as pd
        assert _optional_float(pd.NA) is None

    def test_string_number(self):
        assert _optional_float("3.14") == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# Synthetic data helpers for run_candidate_signal
# ---------------------------------------------------------------------------

def _make_synthetic_df(n: int = 300, freq: str = "H") -> pd.DataFrame:
    """シンプルな合成OHLCVデータを作成する。"""
    timestamps = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    close = 150.0 + np.cumsum(np.random.default_rng(42).normal(0, 0.05, n))
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": close - 0.02,
        "high": close + 0.05,
        "low": close - 0.05,
        "close": close,
        "volume": np.ones(n) * 1000,
    })
    return df


def _make_h1_d1() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_h1 = _make_synthetic_df(n=500, freq="h")
    df_d1 = _make_synthetic_df(n=200, freq="D")
    return df_h1, df_d1


# ---------------------------------------------------------------------------
# run_candidate_signal
# ---------------------------------------------------------------------------

class TestRunCandidateSignal:
    def test_returns_watch_signal(self):
        df_h1, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(df_h1, df_d1)
        assert isinstance(sig, WatchSignal)

    def test_action_is_valid(self):
        df_h1, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(df_h1, df_d1)
        assert sig.action in ("buy", "sell", "no_signal", "skip")

    def test_signal_id_format(self):
        df_h1, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(df_h1, df_d1)
        assert sig.signal_id.startswith("watch_")
        assert sig.action in sig.signal_id

    def test_created_at_injected(self):
        df_h1, df_d1 = _make_h1_d1()
        ts = "2026-05-01T09:00:00+09:00"
        sig = run_candidate_signal(df_h1, df_d1, created_at=ts)
        assert sig.created_at == ts

    def test_strategy_name_from_config(self):
        df_h1, df_d1 = _make_h1_d1()
        cfg = StrategyCandidateConfig(strategy_name="custom_test")
        sig = run_candidate_signal(df_h1, df_d1, config=cfg)
        assert sig.strategy_name == "custom_test"

    def test_empty_h1_returns_skip(self):
        _, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(pd.DataFrame(), df_d1)
        assert sig.action == "skip"
        assert "H1" in sig.reason

    def test_empty_d1_returns_skip(self):
        df_h1, _ = _make_h1_d1()
        sig = run_candidate_signal(df_h1, pd.DataFrame())
        assert sig.action == "skip"
        assert "D1" in sig.reason

    def test_risk_reward_consistency(self):
        df_h1, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(df_h1, df_d1)
        if sig.risk_pips is not None and sig.reward_pips is not None and sig.rr_ratio is not None:
            assert sig.risk_pips > 0
            assert sig.reward_pips > 0
            assert sig.rr_ratio > 0

    def test_no_signal_has_no_levels(self):
        """no_signal / skip では breakout_level が None でも問題ない。"""
        _, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(pd.DataFrame(), df_d1)
        assert sig.stop_loss is None
        assert sig.take_profit is None

    def test_current_price_nonzero_when_data_exists(self):
        df_h1, df_d1 = _make_h1_d1()
        sig = run_candidate_signal(df_h1, df_d1)
        # シグナルがあれば current_price != 0
        if sig.action not in ("skip",):
            assert sig.current_price != 0.0

    def test_long_only_direction_no_sell(self):
        df_h1, df_d1 = _make_h1_d1()
        cfg = StrategyCandidateConfig(direction="long_only")
        sig = run_candidate_signal(df_h1, df_d1, config=cfg)
        assert sig.action != "sell"

    def test_short_only_direction_no_buy(self):
        df_h1, df_d1 = _make_h1_d1()
        cfg = StrategyCandidateConfig(direction="short_only")
        sig = run_candidate_signal(df_h1, df_d1, config=cfg)
        assert sig.action != "buy"


# ---------------------------------------------------------------------------
# _watch_signal_section (daily_personal_report)
# ---------------------------------------------------------------------------

class TestWatchSignalSection:
    def test_empty_list_shows_none(self):
        lines = _watch_signal_section([])
        text = "\n".join(lines)
        assert "none" in text

    def test_header_present(self):
        lines = _watch_signal_section([])
        assert any("FX Watch Candidate" in l for l in lines)

    def test_action_required_note_absent(self):
        lines = _watch_signal_section([])
        text = "\n".join(lines)
        assert "Action Required" not in text.replace("Action Required ではない", "")

    def test_signal_rendered(self):
        sig = _make_watch_signal(action="buy")
        lines = _watch_signal_section([sig])
        text = "\n".join(lines)
        assert "BUY" in text
        assert "155.12" in text  # current_price

    def test_no_orderproposal_note(self):
        sig = _make_watch_signal()
        lines = _watch_signal_section([sig])
        text = "\n".join(lines)
        assert "昇格しない" in text

    def test_multiple_signals(self):
        sig1 = _make_watch_signal(signal_id="w1", action="buy")
        sig2 = _make_watch_signal(signal_id="w2", action="no_signal")
        lines = _watch_signal_section([sig1, sig2])
        text = "\n".join(lines)
        assert "BUY" in text
        assert "NO_SIGNAL" in text

    def test_none_fields_show_na(self):
        sig = _make_watch_signal(
            action="no_signal",
            breakout_level=None,
            stop_loss=None,
            take_profit=None,
            risk_pips=None,
            reward_pips=None,
            rr_ratio=None,
        )
        lines = _watch_signal_section([sig])
        text = "\n".join(lines)
        assert "n/a" in text


# ---------------------------------------------------------------------------
# render_daily_personal_report with watch_signals
# ---------------------------------------------------------------------------

class TestRenderDailyPersonalReportWithWatchSignals:
    def _render(self, watch_signals=None):
        from src.proposals.common_proposal import CommonOrderProposal
        return render_daily_personal_report(
            proposals=[],
            target_date=date(2026, 5, 9),
            generated_at=datetime(2026, 5, 9, 9, 0, 0, tzinfo=timezone.utc),
            stop_trading_active=False,
            dry_run=False,
            read_only=False,
            watch_signals=watch_signals,
        )

    def test_no_watch_signals_renders_none(self):
        report = self._render(watch_signals=None)
        assert "FX Watch Candidate" in report
        assert "none" in report

    def test_empty_watch_signals_renders_none(self):
        report = self._render(watch_signals=[])
        assert "FX Watch Candidate" in report
        assert "none" in report

    def test_watch_signal_appears_before_proposals(self):
        sig = _make_watch_signal(action="sell")
        report = self._render(watch_signals=[sig])
        idx_watch = report.index("FX Watch Candidate")
        idx_summary = report.index("提案サマリー")
        assert idx_watch < idx_summary

    def test_watch_signal_fields_in_report(self):
        sig = _make_watch_signal(action="buy")
        report = self._render(watch_signals=[sig])
        assert "BUY" in report
        assert "UP" in report  # trend_direction

    def test_watch_signal_not_action_required(self):
        sig = _make_watch_signal()
        report = self._render(watch_signals=[sig])
        # "Action Required ではない" must appear somewhere
        assert "Action Required ではない" in report

    def test_watch_signal_not_order_proposal(self):
        sig = _make_watch_signal()
        report = self._render(watch_signals=[sig])
        assert "昇格しない" in report
