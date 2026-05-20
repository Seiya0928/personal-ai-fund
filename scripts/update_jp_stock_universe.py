#!/usr/bin/env python3
"""JPX上場銘柄一覧から銘柄ユニバース CSV を生成する。

実行方法:
    ./venv/bin/python scripts/update_jp_stock_universe.py
    ./venv/bin/python scripts/update_jp_stock_universe.py --output data/jp_stock_universe.csv
    ./venv/bin/python scripts/update_jp_stock_universe.py --no-download --xls /tmp/data_j.xls

禁止事項:
    - 実注文・証券API発注は一切行わない
    - DRY_RUN / READ_ONLY を false にしない
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# JPX 上場銘柄一覧 Excel のダウンロード URL
JPX_XLS_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

# 対象市場区分マッピング（日本語 → 正規化名）
MARKET_MAP = {
    "プライム（内国株式）": "Prime",
    "スタンダード（内国株式）": "Standard",
    "グロース（内国株式）": "Growth",
}

CSV_FIELDS = ["code", "name", "market", "sector_33", "sector_17", "yfinance_symbol"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JPX上場銘柄一覧から銘柄ユニバース CSV を生成する（実注文なし）"
    )
    parser.add_argument(
        "--output",
        default="data/jp_stock_universe.csv",
        help="出力 CSV パス（デフォルト: data/jp_stock_universe.csv）",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="ダウンロードをスキップして既存の XLS ファイルを使う",
    )
    parser.add_argument(
        "--xls",
        default=None,
        help="--no-download 時に使う XLS ファイルパス",
    )
    parser.add_argument(
        "--url",
        default=JPX_XLS_URL,
        help=f"JPX XLS ダウンロード URL（デフォルト: {JPX_XLS_URL}）",
    )
    return parser.parse_args()


def download_xls(url: str, dest: Path) -> Path:
    """JPX から XLS ファイルをダウンロードする。"""
    import urllib.request

    logger.info(f"JPX XLS をダウンロード中: {url}")
    try:
        urllib.request.urlretrieve(url, dest)
        size_kb = dest.stat().st_size // 1024
        logger.info(f"ダウンロード完了: {dest} ({size_kb} KB)")
        return dest
    except Exception as exc:
        raise RuntimeError(f"ダウンロード失敗: {exc}") from exc


def normalize_code(raw) -> str:
    """float 1301.0 → "1301"、str "130A" → "130A"。"""
    if isinstance(raw, float):
        return str(int(raw)).zfill(4)
    s = str(raw).strip()
    try:
        return str(int(float(s))).zfill(4)
    except ValueError:
        return s  # 新形式コード (例: "130A")


def normalize_text(s) -> str:
    """全角英数 → 半角、余白除去。"""
    return unicodedata.normalize("NFKC", str(s)).strip()


def parse_xls(xls_path: Path) -> list[dict]:
    """JPX XLS ファイルを解析して銘柄リストを返す。"""
    try:
        import xlrd
    except ImportError:
        raise RuntimeError(
            "xlrd がインストールされていません。\n"
            "pip install xlrd を実行してください。"
        )

    wb = xlrd.open_workbook(str(xls_path))
    ws = wb.sheet_by_index(0)
    logger.info(f"XLS 読み込み: {ws.nrows} 行 × {ws.ncols} 列")

    rows: list[dict] = []
    skipped = 0

    for i in range(1, ws.nrows):
        raw_market = ws.cell_value(i, 3)
        if raw_market not in MARKET_MAP:
            skipped += 1
            continue

        sec33 = ws.cell_value(i, 5)
        sec17 = ws.cell_value(i, 7)
        # セクター情報がない行をスキップ（ETF等の混入対策）
        if sec33 in ("-", "", None) or sec17 in ("-", "", None):
            skipped += 1
            continue

        code = normalize_code(ws.cell_value(i, 1))
        name = normalize_text(ws.cell_value(i, 2))
        market = MARKET_MAP[raw_market]

        rows.append({
            "code": code,
            "name": name,
            "market": market,
            "sector_33": normalize_text(sec33),
            "sector_17": normalize_text(sec17),
            "yfinance_symbol": f"{code}.T",
        })

    logger.info(f"パース完了: {len(rows)} 銘柄 / スキップ {skipped} 件")
    return rows


def save_csv(rows: list[dict], output: Path) -> None:
    """銘柄リストを CSV に保存する。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"CSV 保存: {output} ({len(rows)} 銘柄)")


def main() -> None:
    args = parse_args()
    output = Path(args.output)

    logger.info("=" * 55)
    logger.info("JPX 銘柄ユニバース更新スクリプト")
    logger.info("※ 実注文なし・研究用データ取得のみ")
    logger.info("=" * 55)

    # XLS の取得
    if args.no_download:
        if not args.xls:
            logger.error("--no-download 時は --xls でファイルパスを指定してください")
            sys.exit(1)
        xls_path = Path(args.xls)
        if not xls_path.exists():
            logger.error(f"XLS ファイルが見つかりません: {xls_path}")
            sys.exit(1)
        logger.info(f"既存 XLS を使用: {xls_path}")
    else:
        import tempfile
        xls_path = Path(tempfile.mktemp(suffix=".xls"))
        download_xls(args.url, xls_path)

    # パース
    rows = parse_xls(xls_path)

    # 市場別内訳
    from collections import Counter
    market_counts = Counter(r["market"] for r in rows)
    for market, count in sorted(market_counts.items()):
        logger.info(f"  {market}: {count} 銘柄")

    # CSV 保存
    save_csv(rows, output)

    logger.info("=" * 55)
    logger.info(f"完了: {len(rows)} 銘柄 → {output}")
    logger.info("Next: ./venv/bin/python scripts/run_jp_stock_screener.py --universe-source jpx --limit 50")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
