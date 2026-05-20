"""日本株ユニバース管理のテスト。"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.jp_stocks.universe import (
    UniverseEntry,
    get_fixed_universe,
    get_universe,
    load_csv_universe,
)


# ── fixture ─────────────────────────────────────────────────────────

def _write_temp_csv(rows: list[dict]) -> Path:
    """テスト用 CSV を一時ファイルに書き込む。"""
    tmp = Path(tempfile.mktemp(suffix=".csv"))
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["code", "name", "market", "sector_33", "sector_17", "yfinance_symbol"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return tmp


SAMPLE_ROWS = [
    {"code": "7203", "name": "トヨタ自動車", "market": "Prime",    "sector_33": "輸送用機器", "sector_17": "自動車・輸送機", "yfinance_symbol": "7203.T"},
    {"code": "8306", "name": "三菱UFJ",      "market": "Prime",    "sector_33": "銀行業",    "sector_17": "銀行",          "yfinance_symbol": "8306.T"},
    {"code": "3697", "name": "SHIFT",        "market": "Prime",    "sector_33": "情報・通信", "sector_17": "情報通信・サービス", "yfinance_symbol": "3697.T"},
    {"code": "4385", "name": "メルカリ",     "market": "Growth",   "sector_33": "情報・通信", "sector_17": "情報通信・サービス", "yfinance_symbol": "4385.T"},
    {"code": "1234", "name": "スタンダード株", "market": "Standard", "sector_33": "小売業",    "sector_17": "小売",          "yfinance_symbol": "1234.T"},
    {"code": "130A", "name": "新形式株",     "market": "Growth",   "sector_33": "医薬品",    "sector_17": "医薬品",        "yfinance_symbol": "130A.T"},
]


# ── UniverseEntry テスト ─────────────────────────────────────────────

class TestUniverseEntry:
    def test_fields(self):
        e = UniverseEntry(
            code="7203", name="トヨタ自動車", market="Prime",
            sector_33="輸送用機器", sector_17="自動車・輸送機",
            yfinance_symbol="7203.T",
        )
        assert e.code == "7203"
        assert e.yfinance_symbol == "7203.T"

    def test_new_format_code(self):
        """130A 形式の新規上場コードも扱える。"""
        e = UniverseEntry(
            code="130A", name="新形式株", market="Growth",
            sector_33="医薬品", sector_17="医薬品",
            yfinance_symbol="130A.T",
        )
        assert e.yfinance_symbol == "130A.T"


# ── load_csv_universe テスト ─────────────────────────────────────────

class TestLoadCsvUniverse:
    def test_load_all(self):
        """全件読み込みできる。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path)
        assert len(entries) == len(SAMPLE_ROWS)

    def test_yfinance_symbol_generated(self):
        """yfinance_symbol が正しく設定される。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path)
        by_code = {e.code: e for e in entries}
        assert by_code["7203"].yfinance_symbol == "7203.T"
        assert by_code["130A"].yfinance_symbol == "130A.T"

    def test_market_filter_prime(self):
        """market_filter=prime でプライム株だけ返る。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, market_filter="prime")
        assert all(e.market == "Prime" for e in entries)
        assert len(entries) == 3  # 7203, 8306, 3697

    def test_market_filter_growth(self):
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, market_filter="growth")
        assert all(e.market == "Growth" for e in entries)
        assert len(entries) == 2  # 4385, 130A

    def test_market_filter_standard(self):
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, market_filter="standard")
        assert len(entries) == 1
        assert entries[0].code == "1234"

    def test_market_filter_all(self):
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, market_filter="all")
        assert len(entries) == len(SAMPLE_ROWS)

    def test_market_filter_case_insensitive(self):
        """大文字小文字を区別しない。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries_lower = load_csv_universe(csv_path, market_filter="prime")
        entries_upper = load_csv_universe(csv_path, market_filter="Prime")
        assert len(entries_lower) == len(entries_upper)

    def test_limit(self):
        """limit で上限件数が効く。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, limit=2)
        assert len(entries) == 2

    def test_limit_larger_than_total(self):
        """limit が総件数より大きくても全件返る。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path, limit=1000)
        assert len(entries) == len(SAMPLE_ROWS)

    def test_file_not_found_raises(self):
        """CSV がない場合 FileNotFoundError が発生する。"""
        with pytest.raises(FileNotFoundError):
            load_csv_universe(Path("/tmp/nonexistent_universe_xyzxyz.csv"))

    def test_entry_fields(self):
        """各フィールドが正しく読み込まれる。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = load_csv_universe(csv_path)
        toyota = next(e for e in entries if e.code == "7203")
        assert toyota.name == "トヨタ自動車"
        assert toyota.market == "Prime"
        assert toyota.sector_33 == "輸送用機器"
        assert toyota.sector_17 == "自動車・輸送機"


# ── get_fixed_universe テスト ────────────────────────────────────────

class TestGetFixedUniverse:
    def test_returns_entries(self):
        """固定ユニバースが空でないこと。"""
        entries = get_fixed_universe()
        assert len(entries) > 0

    def test_contains_known_stocks(self):
        """既知の銘柄が含まれること。"""
        entries = get_fixed_universe()
        codes = {e.code for e in entries}
        assert "7203" in codes   # トヨタ
        assert "8306" in codes   # 三菱UFJ

    def test_yfinance_symbol_format(self):
        """yfinance_symbol が code + .T の形式。"""
        entries = get_fixed_universe()
        for e in entries:
            assert e.yfinance_symbol == f"{e.code}.T"

    def test_market_is_set(self):
        """market が空でないこと。"""
        entries = get_fixed_universe()
        for e in entries:
            assert e.market


# ── get_universe テスト ──────────────────────────────────────────────

class TestGetUniverse:
    def test_fixed_source_returns_65_stocks(self):
        """固定ユニバースは 65 銘柄（デフォルト）を返す。"""
        entries = get_universe(source="fixed")
        # 9613 を除外した 65 銘柄
        assert len(entries) == 65

    def test_fixed_source_with_market_filter(self):
        """fixed + market=growth でグロース銘柄だけ返る。"""
        entries = get_universe(source="fixed", market_filter="growth")
        assert all(e.market.lower() == "growth" for e in entries)
        assert len(entries) >= 1  # フリー (4478) は Growth

    def test_fixed_source_with_limit(self):
        """fixed + limit=10 で 10 件だけ返る。"""
        entries = get_universe(source="fixed", limit=10)
        assert len(entries) == 10

    def test_jpx_source_with_csv(self):
        """jpx ソースで CSV から読み込める。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = get_universe(source="jpx", csv_path=csv_path)
        assert len(entries) == len(SAMPLE_ROWS)

    def test_jpx_source_market_filter(self):
        """jpx + market=prime でプライム株だけ返る。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = get_universe(source="jpx", market_filter="prime", csv_path=csv_path)
        assert all(e.market == "Prime" for e in entries)

    def test_jpx_source_limit(self):
        """jpx + limit=3 で 3 件だけ返る。"""
        csv_path = _write_temp_csv(SAMPLE_ROWS)
        entries = get_universe(source="jpx", limit=3, csv_path=csv_path)
        assert len(entries) == 3

    def test_invalid_source_raises(self):
        """不明なソースで ValueError が発生する。"""
        with pytest.raises(ValueError, match="不明な universe source"):
            get_universe(source="invalid")

    def test_jpx_missing_csv_raises(self):
        """jpx ソースで CSV がない場合 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            get_universe(source="jpx", csv_path=Path("/tmp/nonexistent.csv"))


# ── 実注文安全性テスト ────────────────────────────────────────────────

class TestUniverseSafety:
    def test_universe_module_has_no_forbidden_strings(self):
        """universe.py に実注文関連文字列が含まれないこと。"""
        universe_path = Path(__file__).resolve().parents[1] / "src" / "jp_stocks" / "universe.py"
        content = universe_path.read_text(encoding="utf-8")
        for forbidden in ["live_order", "place_order", "DRY_RUN=false", "gmo_private"]:
            assert forbidden not in content, f"universe.py に '{forbidden}' が含まれています"

    def test_update_script_has_no_forbidden_strings(self):
        """update_jp_stock_universe.py に実注文関連文字列が含まれないこと。"""
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "update_jp_stock_universe.py"
        content = script_path.read_text(encoding="utf-8")
        for forbidden in ["live_order", "place_order", "DRY_RUN=false", "gmo_private"]:
            assert forbidden not in content, f"update_jp_stock_universe.py に '{forbidden}' が含まれています"
