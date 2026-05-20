"""日本株スクリーニング bot の安全性テスト。

実注文関連の文字列・関数・モジュールが含まれていないことを検証する。
"""
from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

# スキャン対象のソースファイル
JP_STOCK_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "jp_stocks"
JP_STOCK_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

# 絶対に含まれてはいけないキーワード
FORBIDDEN_STRINGS = [
    "live_order",
    "place_order",
    "submit_order",
    "create_order",
    "DRY_RUN=false",
    "DRY_RUN = false",
    "READ_ONLY=false",
    "READ_ONLY = false",
    "gmo_private",          # 認証済み Private API への参照
    "private_adapter",
    "margin_trade",         # 信用取引
    "short_sell",           # 空売り
    "kabu_station",         # 有料リアルタイム API
]

# スクリーニング固有スクリプト（安全性チェック対象）
SCREENER_SCRIPTS = [
    "run_jp_stock_screener.py",
    "check_jp_stock_screener_health.py",
]


def _collect_src_files() -> list[Path]:
    """src/jp_stocks/ 以下の .py ファイルを収集する。"""
    return list(JP_STOCK_SRC_ROOT.glob("*.py"))


def _collect_script_files() -> list[Path]:
    return [JP_STOCK_SCRIPTS / name for name in SCREENER_SCRIPTS
            if (JP_STOCK_SCRIPTS / name).exists()]


class TestNoLiveOrderCode:
    @pytest.mark.parametrize("src_file", _collect_src_files())
    def test_no_forbidden_strings_in_src(self, src_file: Path):
        """src/jp_stocks/ 内に実注文関連の文字列が含まれないこと。"""
        content = src_file.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in content, (
                f"{src_file.name} に禁止文字列 '{forbidden}' が含まれています"
            )

    @pytest.mark.parametrize("script_file", _collect_script_files())
    def test_no_forbidden_strings_in_scripts(self, script_file: Path):
        """スクリーニングスクリプトに実注文関連の文字列が含まれないこと。"""
        content = script_file.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in content, (
                f"{script_file.name} に禁止文字列 '{forbidden}' が含まれています"
            )


class TestModuleImportSafety:
    def test_models_importable_without_side_effects(self):
        """models.py がインポート時に副作用なく読み込める。"""
        from src.jp_stocks import models
        assert hasattr(models, "JP_STOCK_CANDIDATE")
        assert hasattr(models, "JP_STOCK_WATCH")
        assert hasattr(models, "JP_STOCK_SKIP")

    def test_screener_importable_without_side_effects(self):
        """screener.py がインポート時に外部接続・副作用なく読み込める。"""
        from src.jp_stocks import screener
        assert hasattr(screener, "screen_quote")
        assert hasattr(screener, "run_screening")

    def test_reporter_importable_without_side_effects(self):
        from src.jp_stocks import reporter
        assert hasattr(reporter, "generate_report")
        assert hasattr(reporter, "save_report")

    def test_health_importable_without_side_effects(self):
        from src.jp_stocks import health
        assert hasattr(health, "check_health")
        assert hasattr(health, "render_health")


class TestStatusConstants:
    def test_status_constants_are_strings(self):
        from src.jp_stocks.models import JP_STOCK_CANDIDATE, JP_STOCK_SKIP, JP_STOCK_WATCH
        assert isinstance(JP_STOCK_CANDIDATE, str)
        assert isinstance(JP_STOCK_WATCH, str)
        assert isinstance(JP_STOCK_SKIP, str)

    def test_status_constants_are_distinct(self):
        from src.jp_stocks.models import JP_STOCK_CANDIDATE, JP_STOCK_SKIP, JP_STOCK_WATCH
        statuses = {JP_STOCK_CANDIDATE, JP_STOCK_WATCH, JP_STOCK_SKIP}
        assert len(statuses) == 3

    def test_status_names_contain_jp_stock_prefix(self):
        from src.jp_stocks.models import JP_STOCK_CANDIDATE, JP_STOCK_SKIP, JP_STOCK_WATCH
        for status in (JP_STOCK_CANDIDATE, JP_STOCK_WATCH, JP_STOCK_SKIP):
            assert status.startswith("JP_STOCK_")


class TestFetcherSafety:
    def test_fixture_mode_works_without_network(self):
        """fixture モードはネットワーク接続なしで動く。"""
        from src.jp_stocks.fetcher import fetch_quotes_from_fixture
        fixture = [
            {
                "code": "7203",
                "name": "トヨタ自動車",
                "market": "Prime",
                "sector": "自動車",
                "prev_close": 2000.0,
                "current_price": 2100.0,
                "change_pct": 5.0,
                "volume": 2_000_000,
                "avg_volume_20d": 1_000_000,
                "turnover_jpy": 4_200_000_000,
                "high_52w": 2500.0,
                "low_52w": 1500.0,
                "data_date": "2026-05-19",
            }
        ]
        quotes, errors = fetch_quotes_from_fixture(fixture)
        assert len(quotes) == 1
        assert errors == []
        assert quotes[0].code == "7203"

    def test_stock_universe_has_codes(self):
        """STOCK_UNIVERSE が少なくとも 50 銘柄を含むこと。"""
        from src.jp_stocks.fetcher import STOCK_UNIVERSE
        assert len(STOCK_UNIVERSE) >= 50

    def test_stock_universe_codes_are_numeric_strings(self):
        """全銘柄コードが 4 桁の数字文字列であること。"""
        from src.jp_stocks.fetcher import STOCK_UNIVERSE
        for code in STOCK_UNIVERSE:
            assert code.isdigit(), f"銘柄コード '{code}' が数字ではありません"
            assert len(code) == 4, f"銘柄コード '{code}' が 4 桁ではありません"

    def test_stock_universe_has_required_meta(self):
        """全銘柄メタデータに name / market / sector が含まれること。"""
        from src.jp_stocks.fetcher import STOCK_UNIVERSE
        for code, meta in STOCK_UNIVERSE.items():
            assert "name" in meta, f"{code}: name がありません"
            assert "market" in meta, f"{code}: market がありません"
            assert "sector" in meta, f"{code}: sector がありません"


class TestDataDegradation:
    """データ欠損・失敗時の挙動テスト。"""

    def test_failed_quote_screened_as_skip(self):
        """fetch_error を持つ StockQuote は SKIP になる。"""
        from src.jp_stocks.models import StockQuote
        from src.jp_stocks.screener import screen_quote
        q = StockQuote(
            code="9999", name="失敗銘柄", market="Prime", sector="テスト",
            prev_close=0, current_price=0, change_pct=0,
            volume=0, avg_volume_20d=1, turnover_jpy=0,
            high_52w=0, low_52w=0, data_date="",
            is_stale=True, fetch_error="Connection error",
        )
        sig = screen_quote(q)
        assert sig.status == "JP_STOCK_SKIP"

    def test_all_failed_quotes_gives_empty_candidates(self):
        """全銘柄エラーでも run_screening がクラッシュしない。"""
        from src.jp_stocks.models import StockQuote
        from src.jp_stocks.screener import run_screening
        failed = [
            StockQuote(
                code=str(i), name=f"失敗{i}", market="Prime", sector="テスト",
                prev_close=0, current_price=0, change_pct=0,
                volume=0, avg_volume_20d=1, turnover_jpy=0,
                high_52w=0, low_52w=0, data_date="",
                is_stale=True, fetch_error="error",
            )
            for i in range(5)
        ]
        result = run_screening(failed, ["error1", "error2"], data_source="test")
        assert result.candidate_count == 0
        assert result.total_screened == 5
        assert result.errors == ["error1", "error2"]
