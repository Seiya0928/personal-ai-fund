# 実注文なし・研究用データ取得のみ
# データソース: yfinance (Yahoo Finance) — 15分以上遅延の無料データ
# 実注文API・発注処理は一切含まない
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.jp_stocks.models import STALE_DAYS_THRESHOLD, StockQuote

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DATA_SOURCE = "yfinance (Yahoo Finance, 遅延あり)"

# ── 銘柄ユニバース ────────────────────────────────────────────────────
# 流動性が高い代表的な日本株 65 銘柄（東証上場）
# yfinance では「銘柄コード.T」でアクセスする
STOCK_UNIVERSE: dict[str, dict[str, str]] = {
    # 銀行・金融
    "8306": {"name": "三菱UFJフィナンシャル・グループ", "market": "Prime", "sector": "銀行"},
    "8316": {"name": "三井住友フィナンシャルグループ",   "market": "Prime", "sector": "銀行"},
    "8411": {"name": "みずほフィナンシャルグループ",     "market": "Prime", "sector": "銀行"},
    "8591": {"name": "オリックス",                       "market": "Prime", "sector": "金融"},
    "8766": {"name": "東京海上ホールディングス",         "market": "Prime", "sector": "保険"},
    "8604": {"name": "野村ホールディングス",             "market": "Prime", "sector": "証券"},
    # 自動車
    "7203": {"name": "トヨタ自動車",     "market": "Prime", "sector": "自動車"},
    "7267": {"name": "本田技研工業",     "market": "Prime", "sector": "自動車"},
    "7201": {"name": "日産自動車",       "market": "Prime", "sector": "自動車"},
    "7269": {"name": "スズキ",           "market": "Prime", "sector": "自動車"},
    "7270": {"name": "SUBARU",           "market": "Prime", "sector": "自動車"},
    "7211": {"name": "三菱自動車工業",   "market": "Prime", "sector": "自動車"},
    # 半導体・精密機器
    "6857": {"name": "アドバンテスト",   "market": "Prime", "sector": "半導体"},
    "6920": {"name": "レーザーテック",   "market": "Prime", "sector": "半導体"},
    "8035": {"name": "東京エレクトロン", "market": "Prime", "sector": "半導体"},
    "6861": {"name": "キーエンス",       "market": "Prime", "sector": "精密機器"},
    "6954": {"name": "ファナック",       "market": "Prime", "sector": "精密機器"},
    "6645": {"name": "オムロン",         "market": "Prime", "sector": "電気機器"},
    "6146": {"name": "ディスコ",         "market": "Prime", "sector": "半導体"},
    # 電気機器・総合電機
    "6758": {"name": "ソニーグループ",   "market": "Prime", "sector": "電気機器"},
    "6501": {"name": "日立製作所",       "market": "Prime", "sector": "電気機器"},
    "6702": {"name": "富士通",           "market": "Prime", "sector": "電気機器"},
    "6752": {"name": "パナソニックHD",   "market": "Prime", "sector": "電気機器"},
    "6971": {"name": "京セラ",           "market": "Prime", "sector": "電気機器"},
    "6981": {"name": "村田製作所",       "market": "Prime", "sector": "電気機器"},
    # 商社
    "8058": {"name": "三菱商事",   "market": "Prime", "sector": "商社"},
    "8031": {"name": "三井物産",   "market": "Prime", "sector": "商社"},
    "8053": {"name": "住友商事",   "market": "Prime", "sector": "商社"},
    "8001": {"name": "伊藤忠商事", "market": "Prime", "sector": "商社"},
    "8002": {"name": "丸紅",       "market": "Prime", "sector": "商社"},
    # 通信・IT
    "9432": {"name": "日本電信電話(NTT)",    "market": "Prime", "sector": "通信"},
    "9433": {"name": "KDDI",                 "market": "Prime", "sector": "通信"},
    "9984": {"name": "ソフトバンクグループ", "market": "Prime", "sector": "情報通信"},
    "4689": {"name": "LINEヤフー",           "market": "Prime", "sector": "情報通信"},
    # 9613 NTTデータグループ: 2024年再編後 yfinance で取得不可 → 除外
    "4307": {"name": "野村総合研究所",       "market": "Prime", "sector": "情報サービス"},
    # 小売・消費財
    "9983": {"name": "ファーストリテイリング", "market": "Prime", "sector": "小売"},
    "3382": {"name": "セブン&アイHD",         "market": "Prime", "sector": "小売"},
    "8267": {"name": "イオン",                "market": "Prime", "sector": "小売"},
    "7564": {"name": "ワークマン",            "market": "Prime", "sector": "小売"},
    # 食品・飲料
    "2914": {"name": "日本たばこ産業(JT)", "market": "Prime", "sector": "食品"},
    "2502": {"name": "アサヒグループHD",   "market": "Prime", "sector": "食品"},
    "2503": {"name": "キリンHD",           "market": "Prime", "sector": "食品"},
    "2802": {"name": "味の素",             "market": "Prime", "sector": "食品"},
    # 化学・素材
    "4063": {"name": "信越化学工業", "market": "Prime", "sector": "化学"},
    "3407": {"name": "旭化成",       "market": "Prime", "sector": "化学"},
    "4183": {"name": "三井化学",     "market": "Prime", "sector": "化学"},
    # 製薬・医療
    "4503": {"name": "アステラス製薬", "market": "Prime", "sector": "医薬品"},
    "4568": {"name": "第一三共",       "market": "Prime", "sector": "医薬品"},
    "4519": {"name": "中外製薬",       "market": "Prime", "sector": "医薬品"},
    "4523": {"name": "エーザイ",       "market": "Prime", "sector": "医薬品"},
    # 不動産
    "8802": {"name": "三菱地所",   "market": "Prime", "sector": "不動産"},
    "8801": {"name": "三井不動産", "market": "Prime", "sector": "不動産"},
    # エネルギー・鉄鋼
    "5020": {"name": "ENEOSホールディングス", "market": "Prime", "sector": "石油"},
    "5401": {"name": "日本製鉄",             "market": "Prime", "sector": "鉄鋼"},
    "5411": {"name": "JFEホールディングス",  "market": "Prime", "sector": "鉄鋼"},
    # 重工・機械
    "7011": {"name": "三菱重工業", "market": "Prime", "sector": "機械"},
    "7013": {"name": "IHI",        "market": "Prime", "sector": "機械"},
    # 建設
    "1928": {"name": "積水ハウス",     "market": "Prime", "sector": "建設"},
    "1925": {"name": "大和ハウス工業", "market": "Prime", "sector": "建設"},
    # グロース・テック
    "4755": {"name": "楽天グループ", "market": "Prime",  "sector": "情報通信"},
    "2413": {"name": "エムスリー",   "market": "Prime",  "sector": "サービス"},
    "4385": {"name": "メルカリ",     "market": "Prime",  "sector": "情報通信"},
    "3659": {"name": "ネクソン",     "market": "Prime",  "sector": "情報通信"},
    "3697": {"name": "SHIFT",        "market": "Prime",  "sector": "情報サービス"},
    "4478": {"name": "フリー",       "market": "Growth", "sector": "情報サービス"},
}


# ── 公開 API ─────────────────────────────────────────────────────────

def fetch_all_quotes(delay_sec: float = 0.3) -> tuple[list[StockQuote], list[str]]:
    """全銘柄の日次データを yfinance から取得する。

    Parameters
    ----------
    delay_sec : float
        銘柄間の待機秒数（レート制限対策）

    Returns
    -------
    quotes : list[StockQuote]
        取得成功・失敗を含む全銘柄のリスト
    errors : list[str]
        エラーメッセージのリスト
    """
    quotes: list[StockQuote] = []
    errors: list[str] = []
    total = len(STOCK_UNIVERSE)

    for i, (code, meta) in enumerate(STOCK_UNIVERSE.items(), 1):
        try:
            quote = _fetch_single(code, meta)
            quotes.append(quote)
            if i % 10 == 0:
                logger.info(f"  取得進捗: {i}/{total} 銘柄")
        except Exception as exc:
            msg = f"{code} ({meta['name']}): {exc}"
            logger.warning(f"データ取得失敗 — {msg}")
            errors.append(msg)
            quotes.append(_failed_quote(code, meta, str(exc)))

        if i < total:
            time.sleep(delay_sec)

    logger.info(f"取得完了: {len(quotes)} 銘柄 / エラー {len(errors)} 件")
    return quotes, errors


def fetch_quotes_for_universe(
    entries: list,
    delay_sec: float = 0.3,
) -> tuple[list[StockQuote], list[str]]:
    """UniverseEntry のリストから全銘柄の日次データを取得する。

    Parameters
    ----------
    entries : list[UniverseEntry]
        universe.py の UniverseEntry インスタンスのリスト。
    delay_sec : float
        銘柄間の待機秒数（レート制限対策）。

    Returns
    -------
    quotes : list[StockQuote]
        取得成功・失敗を含む全銘柄のリスト。
    errors : list[str]
        エラーメッセージのリスト。
    """
    quotes: list[StockQuote] = []
    errors: list[str] = []
    total = len(entries)

    for i, entry in enumerate(entries, 1):
        meta = {
            "name": entry.name,
            "market": entry.market,
            "sector": entry.sector_33 or entry.sector_17 or "その他",
        }
        try:
            quote = _fetch_single(entry.code, meta)
            quotes.append(quote)
            if i % 20 == 0:
                logger.info(f"  取得進捗: {i}/{total} 銘柄")
        except Exception as exc:
            msg = f"{entry.code} ({entry.name}): {exc}"
            logger.warning(f"データ取得失敗 — {msg}")
            errors.append(msg)
            quotes.append(_failed_quote(entry.code, meta, str(exc)))

        if i < total:
            time.sleep(delay_sec)

    logger.info(f"取得完了: {len(quotes)} 銘柄 / エラー {len(errors)} 件")
    return quotes, errors


def fetch_quotes_from_fixture(fixture: list[dict]) -> tuple[list[StockQuote], list[str]]:
    """テスト・デモ用 fixture データから StockQuote リストを生成する。

    fixture 要素は StockQuote の各フィールドを持つ dict。
    """
    quotes = []
    for row in fixture:
        quotes.append(StockQuote(
            code=row["code"],
            name=row["name"],
            market=row.get("market", "Prime"),
            sector=row.get("sector", "その他"),
            prev_close=float(row.get("prev_close", 0)),
            current_price=float(row.get("current_price", 0)),
            change_pct=float(row.get("change_pct", 0)),
            volume=int(row.get("volume", 0)),
            avg_volume_20d=float(row.get("avg_volume_20d", 1)),
            turnover_jpy=float(row.get("turnover_jpy", 0)),
            high_52w=float(row.get("high_52w", 0)),
            low_52w=float(row.get("low_52w", 0)),
            data_date=row.get("data_date", datetime.now(JST).strftime("%Y-%m-%d")),
            is_stale=bool(row.get("is_stale", False)),
            fetch_error=row.get("fetch_error"),
        ))
    return quotes, []


# ── 内部関数 ─────────────────────────────────────────────────────────

def _fetch_single(code: str, meta: dict) -> StockQuote:
    """1銘柄のデータを yfinance から取得する。"""
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("yfinance がインストールされていません: pip install yfinance") from e

    ticker = yf.Ticker(f"{code}.T")
    hist = ticker.history(period="35d", auto_adjust=True)

    if hist is None or hist.empty:
        raise ValueError("yfinance からデータが返されませんでした")
    if len(hist) < 2:
        raise ValueError(f"データ行数不足 (rows={len(hist)}、最低 2 行必要)")

    # 直近 2 日
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]

    # 20 日平均出来高（当日を除く）
    hist_ex_today = hist.iloc[:-1]
    avg_vol_20d = float(hist_ex_today["Volume"].tail(20).mean())
    if avg_vol_20d == 0:
        avg_vol_20d = 1.0  # ゼロ除算回避

    current_price = float(latest["Close"])
    prev_close = float(prev["Close"])
    if prev_close == 0:
        raise ValueError("前日終値が 0 — 上場廃止・データ異常の可能性")

    change_pct = (current_price - prev_close) / prev_close * 100.0
    volume = int(latest["Volume"])
    turnover_jpy = current_price * volume

    # 52 週高値/安値
    high_52w = float(hist["High"].max())
    low_52w = float(hist["Low"].min())

    # データ日付の取得
    data_date = _extract_date_str(hist.index[-1])

    # stale 判定（週末をまたぐ 4 日を閾値）
    is_stale = _is_stale(data_date)

    return StockQuote(
        code=code,
        name=meta["name"],
        market=meta["market"],
        sector=meta["sector"],
        prev_close=prev_close,
        current_price=current_price,
        change_pct=change_pct,
        volume=volume,
        avg_volume_20d=avg_vol_20d,
        turnover_jpy=turnover_jpy,
        high_52w=high_52w,
        low_52w=low_52w,
        data_date=data_date,
        is_stale=is_stale,
    )


def _failed_quote(code: str, meta: dict, error: str) -> StockQuote:
    """取得失敗時のダミー StockQuote を返す。"""
    return StockQuote(
        code=code,
        name=meta["name"],
        market=meta["market"],
        sector=meta["sector"],
        prev_close=0.0,
        current_price=0.0,
        change_pct=0.0,
        volume=0,
        avg_volume_20d=1.0,
        turnover_jpy=0.0,
        high_52w=0.0,
        low_52w=0.0,
        data_date="",
        is_stale=True,
        fetch_error=error,
    )


def _extract_date_str(index_val) -> str:
    """yfinance の index 値から YYYY-MM-DD 文字列を取得する。"""
    try:
        if hasattr(index_val, "strftime"):
            return index_val.strftime("%Y-%m-%d")
        return str(index_val)[:10]
    except Exception:
        return ""


def _is_stale(data_date: str) -> bool:
    """データが STALE_DAYS_THRESHOLD 日以上古いかを判定する。"""
    if not data_date:
        return True
    try:
        data_dt = datetime.strptime(data_date, "%Y-%m-%d").date()
        today = datetime.now(JST).date()
        return (today - data_dt).days > STALE_DAYS_THRESHOLD
    except Exception:
        return True
