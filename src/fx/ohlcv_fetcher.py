"""
USD/JPY OHLCV データフェッチャー（読み取り専用・実注文なし）
データソース: yfinance (Yahoo Finance)
実注文API・発注処理は一切含まない
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.fx.data_loader import FXDataLoader
from src.utils.logger import get_logger

log = get_logger(__name__)

SYMBOL = "USDJPY=X"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAVE_DIR = _PROJECT_ROOT / "state" / "fx_ohlcv" / "usdjpy"

_REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class YFinanceFetcher:
    """
    yfinance から USD/JPY の OHLCV データを取得する。
    実注文API・発注処理は一切含まない（READ_ONLY 設計）。
    """

    def __init__(self, save_dir: Path = DEFAULT_SAVE_DIR) -> None:
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, interval: str, period: str) -> pd.DataFrame:
        """
        yfinance から OHLCV を取得し、正規化して返す。
        取得失敗時は例外を上げず、ログに残して空 DataFrame を返す。

        Parameters
        ----------
        interval : str
            "15m", "1h" など
        period : str
            "60d", "730d" など

        Returns
        -------
        pd.DataFrame
            カラム: timestamp, open, high, low, close, volume
            タイムゾーン: UTC
        """
        try:
            import yfinance as yf
        except ImportError:
            log.error("yfinance がインストールされていません: pip install yfinance")
            return pd.DataFrame()

        try:
            log.info("yfinance fetch: symbol=%s, interval=%s, period=%s", SYMBOL, interval, period)
            raw = yf.download(
                SYMBOL,
                interval=interval,
                period=period,
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.error("yfinance fetch 失敗: %s", exc)
            return pd.DataFrame()

        if raw is None or raw.empty:
            log.warning("yfinance: 空のデータが返されました (symbol=%s, interval=%s, period=%s)", SYMBOL, interval, period)
            return pd.DataFrame()

        return self._normalize(raw)

    def fetch_m15(self, period: str = "60d") -> pd.DataFrame:
        """
        15分足を取得する。

        注意: yfinance の M15 データは直近60日分のみ取得可能。
        長期検証には fetch_h1() を使用してください。
        """
        return self.fetch(interval="15m", period=period)

    def fetch_h1(self, period: str = "730d") -> pd.DataFrame:
        """H1（1時間足）データを取得"""
        return self.fetch("1h", period)

    def fetch_d1(self, period: str = "5y") -> pd.DataFrame:
        """D1（日足）データを取得"""
        return self.fetch("1d", period)

    def fetch_h4(self, period: str = "730d") -> pd.DataFrame:
        """
        1時間足で取得して4時間足にリサンプルする。
        yfinance では4時間足が直接取得できないため、1時間足からリサンプルする。
        """
        df_h1 = self.fetch(interval="1h", period=period)
        if df_h1.empty:
            return pd.DataFrame()
        loader = FXDataLoader()
        df_h4 = loader.resample(df_h1, to="4h")
        log.info("fetch_h4: H1=%d本 → H4=%d本", len(df_h1), len(df_h4))
        return df_h4

    def save(self, df: pd.DataFrame, timeframe: str) -> Path:
        """
        CSV として保存する。
        ファイル名: state/fx_ohlcv/usdjpy/usdjpy_{timeframe}_{YYYYMMDD}.csv
        既存ファイルがあれば読み込んで重複を除いてマージし上書き保存する。

        Parameters
        ----------
        df : pd.DataFrame
            保存する OHLCV DataFrame
        timeframe : str
            時間足識別子（例: "M15", "H4"）

        Returns
        -------
        Path
            保存先ファイルパス
        """
        if df.empty:
            log.warning("save: 空の DataFrame は保存をスキップします (timeframe=%s)", timeframe)
            return self.save_dir / f"usdjpy_{timeframe}_empty.csv"

        from datetime import date
        today_str = date.today().strftime("%Y%m%d")
        filename = f"usdjpy_{timeframe}_{today_str}.csv"
        filepath = self.save_dir / filename

        # 既存ファイルがあればマージ
        if filepath.exists():
            try:
                existing = pd.read_csv(filepath)
                existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
                merged = pd.concat([existing, df], ignore_index=True)
            except Exception as exc:
                log.warning("既存ファイル読み込み失敗、新規保存します: %s", exc)
                merged = df.copy()
        else:
            merged = df.copy()

        # 重複除去・ソート
        if "timestamp" in merged.columns:
            merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
            merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        merged.to_csv(filepath, index=False)
        log.info("save: %s, rows=%d", filepath, len(merged))
        return filepath

    def load_latest(self, timeframe: str) -> pd.DataFrame:
        """
        保存済みの最新 CSV を読み込む。
        ファイルが複数ある場合は全てマージして返す（重複除去・時系列ソート）。
        ファイルがない場合は空 DataFrame を返す。

        Parameters
        ----------
        timeframe : str
            時間足識別子（例: "M15", "H4"）

        Returns
        -------
        pd.DataFrame
        """
        pattern = f"usdjpy_{timeframe}_*.csv"
        files = sorted(self.save_dir.glob(pattern))

        if not files:
            log.info("load_latest: ファイルが見つかりません (timeframe=%s, dir=%s)", timeframe, self.save_dir)
            return pd.DataFrame()

        dfs = []
        for f in files:
            try:
                tmp = pd.read_csv(f)
                dfs.append(tmp)
                log.debug("load_latest: %s, rows=%d", f, len(tmp))
            except Exception as exc:
                log.warning("load_latest: %s 読み込み失敗: %s", f, exc)

        if not dfs:
            return pd.DataFrame()

        merged = pd.concat(dfs, ignore_index=True)
        if "timestamp" in merged.columns:
            merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)
            merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        log.info("load_latest: timeframe=%s, total_rows=%d, files=%d", timeframe, len(merged), len(files))
        return merged

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
        """
        yfinance の MultiIndex カラムを正規化する。
        ("Close","USDJPY=X") → "close" などに変換し、
        timestamp 列を UTC で追加する。
        """
        df = raw.copy()

        # MultiIndex カラムの場合はフラット化
        if isinstance(df.columns, pd.MultiIndex):
            # 第1レベルのカラム名のみを使用
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [str(col).lower() for col in df.columns]

        # インデックス (Datetime) を timestamp 列に変換
        df = df.reset_index()

        # インデックス列の名前を "timestamp" に統一
        # yfinance のインデックス列は "Datetime" または "Date" という名前
        rename_map = {}
        for col in df.columns:
            if col.lower() in ("datetime", "date", "index"):
                rename_map[col] = "timestamp"
                break
        if rename_map:
            df = df.rename(columns=rename_map)
        elif df.columns[0] != "timestamp":
            # 最初の列が timestamp と想定
            df = df.rename(columns={df.columns[0]: "timestamp"})

        # タイムゾーンを UTC に統一
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize("UTC")
            else:
                ts = ts.dt.tz_convert("UTC")
            df["timestamp"] = ts

        # 必須カラムの確認・順序整理
        available = set(df.columns)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required - available
        if missing:
            log.warning("正規化後に必須カラムが不足: %s", missing)

        # カラム順序を整える（存在するものだけ）
        ordered_cols = [c for c in _REQUIRED_COLUMNS if c in df.columns]
        extra_cols = [c for c in df.columns if c not in ordered_cols]
        df = df[ordered_cols + extra_cols]

        # NaN 行の削除（close が NaN の行）
        if "close" in df.columns:
            df = df.dropna(subset=["close"]).reset_index(drop=True)

        log.info("_normalize: rows=%d", len(df))
        return df
