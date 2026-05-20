# 実注文なし・研究用スクリーニングのみ
# このモジュールは実注文APIを一切呼びません。
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── ステータス定数 ────────────────────────────────────────────────────
JP_STOCK_SKIP = "JP_STOCK_SKIP"
JP_STOCK_WATCH = "JP_STOCK_WATCH"
JP_STOCK_CANDIDATE = "JP_STOCK_CANDIDATE"

# データが何日以上古い場合を stale とみなすか（週末をまたぐ 4 日が閾値）
STALE_DAYS_THRESHOLD = 4


@dataclass
class StockQuote:
    """1銘柄の価格・出来高スナップショット（日次終値ベース）。"""

    code: str            # 銘柄コード (例: "7203")
    name: str            # 銘柄名
    market: str          # 市場区分 (Prime / Standard / Growth)
    sector: str          # セクター
    prev_close: float    # 前日終値
    current_price: float # 直近終値
    change_pct: float    # 前日比 (%)
    volume: int          # 当日出来高
    avg_volume_20d: float  # 直近 20 日平均出来高
    turnover_jpy: float    # 売買代金 (円) = current_price × volume
    high_52w: float      # 52 週高値
    low_52w: float       # 52 週安値
    data_date: str       # データ日付 YYYY-MM-DD
    is_stale: bool = False
    fetch_error: Optional[str] = None

    @property
    def volume_ratio(self) -> float:
        """当日出来高 / 20 日平均出来高。"""
        if self.avg_volume_20d <= 0:
            return 0.0
        return self.volume / self.avg_volume_20d

    @property
    def gap_rate(self) -> float:
        """ギャップ率 = 前日比 (%)。"""
        return self.change_pct


@dataclass
class ScreeningSignal:
    """1銘柄に対するスクリーニング判定結果。"""

    code: str
    name: str
    market: str
    sector: str
    status: str          # JP_STOCK_SKIP / JP_STOCK_WATCH / JP_STOCK_CANDIDATE
    reasons: list[str]   # 判定理由
    quote: Optional[StockQuote] = None
    fetch_error: Optional[str] = None


@dataclass
class ScreeningResult:
    """1回のスクリーニング実行全体の結果。"""

    run_at: datetime
    data_source: str
    data_date: Optional[str]    # 取得データの日付 (YYYY-MM-DD)
    is_stale: bool
    total_screened: int
    skip_count: int
    watch_count: int
    candidate_count: int
    signals: list[ScreeningSignal]
    errors: list[str] = field(default_factory=list)

    @property
    def candidate_signals(self) -> list[ScreeningSignal]:
        return [s for s in self.signals if s.status == JP_STOCK_CANDIDATE]

    @property
    def watch_signals(self) -> list[ScreeningSignal]:
        return [s for s in self.signals if s.status == JP_STOCK_WATCH]
