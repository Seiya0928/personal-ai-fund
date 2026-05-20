"""日本株スクリーニング条件・ステータス判定のテスト。"""
from __future__ import annotations

import pytest

from src.jp_stocks.models import (
    JP_STOCK_CANDIDATE,
    JP_STOCK_SKIP,
    JP_STOCK_WATCH,
    StockQuote,
)
from src.jp_stocks.screener import (
    CANDIDATE_GAP_UP_PCT,
    CANDIDATE_TURNOVER_JPY,
    CANDIDATE_VOLUME_RATIO,
    WATCH_GAP_PCT,
    WATCH_VOLUME_RATIO,
    WATCH_TURNOVER_JPY,
    screen_quote,
    run_screening,
)


# ── テスト用 fixture ─────────────────────────────────────────────────

def _make_quote(**overrides) -> StockQuote:
    """デフォルト値を持つテスト用 StockQuote を生成する。"""
    defaults = dict(
        code="0000",
        name="テスト株式会社",
        market="Prime",
        sector="テスト",
        prev_close=1000.0,
        current_price=1050.0,
        change_pct=5.0,
        volume=2_000_000,
        avg_volume_20d=1_000_000,
        turnover_jpy=2_100_000_000,
        high_52w=1_200.0,
        low_52w=800.0,
        data_date="2026-05-19",
        is_stale=False,
        fetch_error=None,
    )
    defaults.update(overrides)
    return StockQuote(**defaults)


# ── CANDIDATE 条件テスト ─────────────────────────────────────────────

class TestCandidateConditions:
    def test_gap_up_candidate(self):
        """前日比+2%以上・出来高比1.5x以上・売買代金5億以上 → CANDIDATE。"""
        q = _make_quote(change_pct=2.5, volume=1_500_000, avg_volume_20d=1_000_000,
                        turnover_jpy=600_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_CANDIDATE
        assert len(sig.reasons) >= 1
        assert "ギャップアップ" in sig.reasons[0]

    def test_rebound_candidate(self):
        """前日比-5%以下・出来高比2x以上・売買代金5億以上 → CANDIDATE。"""
        q = _make_quote(change_pct=-6.0, volume=2_000_000, avg_volume_20d=1_000_000,
                        turnover_jpy=800_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_CANDIDATE
        assert any("リバウンド" in r for r in sig.reasons)

    def test_gap_up_insufficient_volume(self):
        """前日比+3%でも出来高比が不足 → CANDIDATE にならない。"""
        q = _make_quote(change_pct=3.0, volume=1_200_000, avg_volume_20d=1_000_000,
                        turnover_jpy=600_000_000)
        # volume_ratio = 1.2 < 1.5 (CANDIDATE_VOLUME_RATIO)
        sig = screen_quote(q)
        assert sig.status != JP_STOCK_CANDIDATE

    def test_gap_up_insufficient_turnover(self):
        """前日比+3%・出来高比2xでも売買代金が不足 → CANDIDATE にならない。"""
        q = _make_quote(change_pct=3.0, volume=2_000_000, avg_volume_20d=1_000_000,
                        turnover_jpy=100_000_000)  # 1億 < 5億
        sig = screen_quote(q)
        assert sig.status != JP_STOCK_CANDIDATE

    def test_boundary_gap_exactly_2pct(self):
        """前日比ちょうど +2.0% は CANDIDATE 条件を満たす。"""
        q = _make_quote(change_pct=CANDIDATE_GAP_UP_PCT, volume=1_500_000,
                        avg_volume_20d=1_000_000, turnover_jpy=CANDIDATE_TURNOVER_JPY)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_CANDIDATE

    def test_boundary_gap_below_2pct(self):
        """前日比 +1.9% は CANDIDATE ギャップアップ条件を満たさない。"""
        q = _make_quote(change_pct=1.9, volume=1_500_000, avg_volume_20d=1_000_000,
                        turnover_jpy=600_000_000)
        sig = screen_quote(q)
        assert sig.status != JP_STOCK_CANDIDATE


# ── WATCH 条件テスト ──────────────────────────────────────────────────

class TestWatchConditions:
    def test_momentum_watch(self):
        """前日比+1%以上・出来高比1.2x以上・売買代金1億以上 → WATCH。"""
        q = _make_quote(change_pct=1.5, volume=1_200_000, avg_volume_20d=1_000_000,
                        turnover_jpy=150_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_WATCH
        assert any("モメンタム" in r for r in sig.reasons)

    def test_volume_spike_watch(self):
        """出来高比2x以上・売買代金2億以上（価格変動小） → WATCH。"""
        q = _make_quote(change_pct=0.5, volume=2_100_000, avg_volume_20d=1_000_000,
                        turnover_jpy=250_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_WATCH
        assert any("出来高急増" in r for r in sig.reasons)

    def test_dip_watch(self):
        """前日比-3%以下・出来高比1.5x以上 → WATCH。"""
        q = _make_quote(change_pct=-3.5, volume=1_600_000, avg_volume_20d=1_000_000,
                        turnover_jpy=250_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_WATCH
        assert any("急落監視" in r for r in sig.reasons)

    def test_watch_not_triggered_for_low_activity(self):
        """変動もなく出来高も平均的 → SKIP。"""
        q = _make_quote(change_pct=0.3, volume=1_000_000, avg_volume_20d=1_000_000,
                        turnover_jpy=50_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_SKIP


# ── SKIP 条件テスト ───────────────────────────────────────────────────

class TestSkipConditions:
    def test_fetch_error_becomes_skip(self):
        """データ取得失敗は SKIP になる。"""
        q = _make_quote(fetch_error="タイムアウト", is_stale=True)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_SKIP
        assert sig.fetch_error == "タイムアウト"
        assert "データ取得失敗" in sig.reasons[0]

    def test_stale_data_becomes_skip(self):
        """stale データは SKIP になる（条件を満たしていても）。"""
        q = _make_quote(change_pct=5.0, volume=2_000_000, avg_volume_20d=1_000_000,
                        turnover_jpy=1_000_000_000, is_stale=True)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_SKIP
        assert "stale" in sig.reasons[0]

    def test_normal_stock_without_signal(self):
        """特徴のない銘柄は SKIP。"""
        q = _make_quote(change_pct=0.1, volume=900_000, avg_volume_20d=1_000_000,
                        turnover_jpy=30_000_000)
        sig = screen_quote(q)
        assert sig.status == JP_STOCK_SKIP
        assert sig.reasons == []


# ── run_screening テスト ─────────────────────────────────────────────

class TestRunScreening:
    def test_counts_are_consistent(self):
        """candidate_count + watch_count + skip_count == total_screened。"""
        quotes = [
            _make_quote(code="A", change_pct=3.0, volume=2_000_000,
                        avg_volume_20d=1_000_000, turnover_jpy=800_000_000),
            _make_quote(code="B", change_pct=1.2, volume=1_300_000,
                        avg_volume_20d=1_000_000, turnover_jpy=150_000_000),
            _make_quote(code="C", change_pct=0.1, volume=500_000,
                        avg_volume_20d=1_000_000, turnover_jpy=20_000_000),
        ]
        result = run_screening(quotes, [], data_source="test")
        assert result.total_screened == 3
        assert (result.candidate_count + result.watch_count + result.skip_count
                == result.total_screened)

    def test_candidates_sorted_first(self):
        """CANDIDATE シグナルは WATCH・SKIP より先に並ぶ。"""
        quotes = [
            _make_quote(code="skip1", change_pct=0.0, volume=500_000,
                        avg_volume_20d=1_000_000, turnover_jpy=10_000_000),
            _make_quote(code="cand1", change_pct=3.0, volume=2_000_000,
                        avg_volume_20d=1_000_000, turnover_jpy=800_000_000),
        ]
        result = run_screening(quotes, [], data_source="test")
        statuses = [s.status for s in result.signals]
        # CANDIDATE が SKIP より前
        if JP_STOCK_CANDIDATE in statuses and JP_STOCK_SKIP in statuses:
            assert statuses.index(JP_STOCK_CANDIDATE) < statuses.index(JP_STOCK_SKIP)

    def test_error_list_is_preserved(self):
        """エラーリストが ScreeningResult に保持される。"""
        errors = ["7203: タイムアウト", "8306: データ不足"]
        result = run_screening([], errors, data_source="test")
        assert result.errors == errors

    def test_stale_detection_majority(self):
        """過半数の銘柄が stale なら result.is_stale == True。"""
        quotes = [
            _make_quote(code="A", is_stale=True),
            _make_quote(code="B", is_stale=True),
            _make_quote(code="C", is_stale=False),
        ]
        result = run_screening(quotes, [], data_source="test")
        assert result.is_stale is True

    def test_not_stale_if_majority_fresh(self):
        """過半数が fresh なら result.is_stale == False。"""
        quotes = [
            _make_quote(code="A", is_stale=False),
            _make_quote(code="B", is_stale=False),
            _make_quote(code="C", is_stale=True),
        ]
        result = run_screening(quotes, [], data_source="test")
        assert result.is_stale is False

    def test_empty_universe(self):
        """銘柄ゼロでも正常に動く。"""
        result = run_screening([], [], data_source="test")
        assert result.total_screened == 0
        assert result.candidate_count == 0


# ── volume_ratio プロパティテスト ────────────────────────────────────

class TestVolumeRatio:
    def test_volume_ratio_calculation(self):
        q = _make_quote(volume=2_000_000, avg_volume_20d=1_000_000)
        assert q.volume_ratio == pytest.approx(2.0)

    def test_volume_ratio_zero_avg(self):
        """avg_volume_20d = 0 の場合は 0.0 を返す（ゼロ除算回避）。"""
        q = _make_quote(volume=1_000_000, avg_volume_20d=0)
        assert q.volume_ratio == 0.0
