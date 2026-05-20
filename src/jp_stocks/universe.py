# 実注文なし・研究用銘柄ユニバース管理のみ
# このモジュールは実注文APIを一切呼びません。
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = _PROJECT_ROOT / "data" / "jp_stock_universe.csv"

# 有効な universe source
UNIVERSE_SOURCES = ("fixed", "jpx")
# 有効な market filter
MARKET_FILTERS = ("prime", "standard", "growth", "all")


@dataclass
class UniverseEntry:
    """1銘柄のユニバース情報。"""

    code: str             # "7203"
    name: str             # "トヨタ自動車"
    market: str           # "Prime" / "Standard" / "Growth"
    sector_33: str        # 33業種区分（例: "輸送用機器"）
    sector_17: str        # 17業種区分（例: "自動車・輸送機"）
    yfinance_symbol: str  # "7203.T"


def load_csv_universe(
    csv_path: Path = DEFAULT_CSV_PATH,
    market_filter: str = "all",
    limit: Optional[int] = None,
) -> list[UniverseEntry]:
    """CSV から銘柄ユニバースを読み込む。

    Parameters
    ----------
    csv_path : Path
        jp_stock_universe.csv のパス。
    market_filter : str
        "prime" / "standard" / "growth" / "all"。
        大文字小文字を区別しない。
    limit : int | None
        読み込み上限件数。None なら全件。

    Returns
    -------
    list[UniverseEntry]

    Raises
    ------
    FileNotFoundError
        CSV が存在しない場合。
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"ユニバース CSV が見つかりません: {csv_path}\n"
            "scripts/update_jp_stock_universe.py を先に実行してください。"
        )

    entries: list[UniverseEntry] = []
    mf = market_filter.lower()

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if mf != "all" and row["market"].lower() != mf:
                continue
            entries.append(UniverseEntry(
                code=row["code"],
                name=row["name"],
                market=row["market"],
                sector_33=row.get("sector_33", ""),
                sector_17=row.get("sector_17", ""),
                yfinance_symbol=row.get("yfinance_symbol") or f"{row['code']}.T",
            ))
            if limit is not None and len(entries) >= limit:
                break

    logger.info(
        f"JPX universe loaded: {len(entries)} 銘柄 "
        f"(market_filter={market_filter}, limit={limit})"
    )
    return entries


def get_fixed_universe() -> list[UniverseEntry]:
    """既存の固定 65 銘柄を UniverseEntry リストとして返す。

    fetcher.py の STOCK_UNIVERSE を参照するため、追加インポートが必要。
    循環インポートを避けるため関数内でインポートする。
    """
    from src.jp_stocks.fetcher import STOCK_UNIVERSE  # noqa: PLC0415

    entries = []
    for code, meta in STOCK_UNIVERSE.items():
        entries.append(UniverseEntry(
            code=code,
            name=meta["name"],
            market=meta["market"],
            sector_33=meta.get("sector", ""),
            sector_17=meta.get("sector", ""),
            yfinance_symbol=f"{code}.T",
        ))
    return entries


def get_universe(
    source: str = "fixed",
    market_filter: str = "all",
    limit: Optional[int] = None,
    csv_path: Optional[Path] = None,
) -> list[UniverseEntry]:
    """銘柄ユニバースを返す統合エントリーポイント。

    Parameters
    ----------
    source : str
        "fixed" → 既存 65 銘柄
        "jpx"   → data/jp_stock_universe.csv
    market_filter : str
        "prime" / "standard" / "growth" / "all"
    limit : int | None
        取得銘柄の上限件数。
    csv_path : Path | None
        jpx ソース時の CSV パス。None なら DEFAULT_CSV_PATH を使う。
    """
    if source == "fixed":
        entries = get_fixed_universe()
        if market_filter.lower() != "all":
            mf = market_filter.lower()
            entries = [e for e in entries if e.market.lower() == mf]
        if limit is not None:
            entries = entries[:limit]
        logger.info(
            f"Fixed universe: {len(entries)} 銘柄 "
            f"(market_filter={market_filter}, limit={limit})"
        )
        return entries
    elif source == "jpx":
        return load_csv_universe(
            csv_path=csv_path or DEFAULT_CSV_PATH,
            market_filter=market_filter,
            limit=limit,
        )
    else:
        raise ValueError(
            f"不明な universe source: {source!r}。"
            f"有効な値: {UNIVERSE_SOURCES}"
        )
