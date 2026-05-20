# 実注文なし・研究用スクリーニングのみ
# このモジュールは実注文APIを一切呼びません。
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from src.jp_stocks.models import (
    JP_STOCK_CANDIDATE,
    JP_STOCK_SKIP,
    JP_STOCK_WATCH,
    ScreeningResult,
    ScreeningSignal,
    StockQuote,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# ── スクリーニング閾値 ────────────────────────────────────────────────
# JP_STOCK_CANDIDATE 条件
CANDIDATE_GAP_UP_PCT = 2.0          # ギャップアップ閾値 (%)
CANDIDATE_GAP_DOWN_PCT = -5.0       # 急落リバウンド候補の閾値 (%)
CANDIDATE_VOLUME_RATIO = 1.5        # 出来高比（ギャップアップ時）
CANDIDATE_VOLUME_RATIO_REBOUND = 2.0  # 出来高比（リバウンド時）
CANDIDATE_TURNOVER_JPY = 500_000_000  # 最低売買代金 ¥5億

# JP_STOCK_WATCH 条件
WATCH_GAP_PCT = 1.0                 # モメンタム監視の下限 (%)
WATCH_DIP_PCT = -3.0                # 下落監視の下限 (%)
WATCH_VOLUME_RATIO = 1.2            # 出来高比（モメンタム時）
WATCH_VOLUME_SPIKE_RATIO = 2.0      # 出来高急増の閾値
WATCH_DIP_VOLUME_RATIO = 1.5        # 出来高比（下落監視時）
WATCH_TURNOVER_JPY = 100_000_000    # 最低売買代金 ¥1億
WATCH_VOLUME_SPIKE_TURNOVER = 200_000_000  # ¥2億（出来高急増時）


def screen_quote(quote: StockQuote) -> ScreeningSignal:
    """1銘柄をスクリーニングして ScreeningSignal を返す。

    判定優先度: CANDIDATE > WATCH > SKIP
    """
    base = dict(
        code=quote.code,
        name=quote.name,
        market=quote.market,
        sector=quote.sector,
        quote=quote,
    )

    # データ取得失敗
    if quote.fetch_error:
        return ScreeningSignal(
            **base,
            status=JP_STOCK_SKIP,
            reasons=["データ取得失敗"],
            fetch_error=quote.fetch_error,
        )

    # stale データ
    if quote.is_stale:
        return ScreeningSignal(
            **base,
            status=JP_STOCK_SKIP,
            reasons=["データが古い (stale)"],
        )

    candidate_reasons = _candidate_reasons(quote)
    if candidate_reasons:
        return ScreeningSignal(**base, status=JP_STOCK_CANDIDATE, reasons=candidate_reasons)

    watch_reasons = _watch_reasons(quote)
    if watch_reasons:
        return ScreeningSignal(**base, status=JP_STOCK_WATCH, reasons=watch_reasons)

    return ScreeningSignal(**base, status=JP_STOCK_SKIP, reasons=[])


def run_screening(
    quotes: list[StockQuote],
    errors: list[str],
    data_source: str,
) -> ScreeningResult:
    """全銘柄をスクリーニングして ScreeningResult を返す。"""
    signals = [screen_quote(q) for q in quotes]

    skip_count = sum(1 for s in signals if s.status == JP_STOCK_SKIP)
    watch_count = sum(1 for s in signals if s.status == JP_STOCK_WATCH)
    candidate_count = sum(1 for s in signals if s.status == JP_STOCK_CANDIDATE)

    # 全体の stale 判定: 有効銘柄の過半数が stale ならレポート全体を stale とする
    valid = [q for q in quotes if not q.fetch_error]
    stale_ratio = sum(1 for q in valid if q.is_stale) / max(len(valid), 1)
    is_stale = stale_ratio > 0.5

    # データ日付: 成功銘柄の最新日付を使用
    data_dates = [q.data_date for q in quotes if q.data_date and not q.fetch_error]
    data_date = max(data_dates) if data_dates else None

    # CANDIDATE を先頭に、次いで WATCH、SKIP は末尾に並べ替え
    order = {JP_STOCK_CANDIDATE: 0, JP_STOCK_WATCH: 1, JP_STOCK_SKIP: 2}
    signals.sort(key=lambda s: (order[s.status], -(s.quote.turnover_jpy if s.quote else 0)))

    logger.info(
        f"スクリーニング完了: 全{len(signals)}銘柄 "
        f"CANDIDATE={candidate_count} WATCH={watch_count} SKIP={skip_count}"
    )

    return ScreeningResult(
        run_at=datetime.now(JST),
        data_source=data_source,
        data_date=data_date,
        is_stale=is_stale,
        total_screened=len(signals),
        skip_count=skip_count,
        watch_count=watch_count,
        candidate_count=candidate_count,
        signals=signals,
        errors=errors,
    )


# ── 内部判定関数 ─────────────────────────────────────────────────────

def _candidate_reasons(q: StockQuote) -> list[str]:
    reasons = []

    # ① ギャップアップ候補
    if (
        q.gap_rate >= CANDIDATE_GAP_UP_PCT
        and q.volume_ratio >= CANDIDATE_VOLUME_RATIO
        and q.turnover_jpy >= CANDIDATE_TURNOVER_JPY
    ):
        reasons.append(
            f"ギャップアップ {q.gap_rate:+.1f}% / "
            f"出来高比 {q.volume_ratio:.1f}x / "
            f"売買代金 {q.turnover_jpy / 1e8:.1f}億円"
        )

    # ② 急落リバウンド候補（出来高急増を伴う急落）
    if (
        q.gap_rate <= CANDIDATE_GAP_DOWN_PCT
        and q.volume_ratio >= CANDIDATE_VOLUME_RATIO_REBOUND
        and q.turnover_jpy >= CANDIDATE_TURNOVER_JPY
    ):
        reasons.append(
            f"急落リバウンド候補 {q.gap_rate:+.1f}% / "
            f"出来高比 {q.volume_ratio:.1f}x / "
            f"売買代金 {q.turnover_jpy / 1e8:.1f}億円"
        )

    return reasons


def _watch_reasons(q: StockQuote) -> list[str]:
    reasons = []

    # ① モメンタム監視
    if (
        q.gap_rate >= WATCH_GAP_PCT
        and q.volume_ratio >= WATCH_VOLUME_RATIO
        and q.turnover_jpy >= WATCH_TURNOVER_JPY
    ):
        reasons.append(
            f"モメンタム {q.gap_rate:+.1f}% / 出来高比 {q.volume_ratio:.1f}x"
        )

    # ② 出来高急増（価格変動が小さくても要注意）
    if (
        q.volume_ratio >= WATCH_VOLUME_SPIKE_RATIO
        and q.turnover_jpy >= WATCH_VOLUME_SPIKE_TURNOVER
        and q.gap_rate < WATCH_GAP_PCT  # モメンタムと重複回避
    ):
        reasons.append(
            f"出来高急増 {q.volume_ratio:.1f}x / "
            f"売買代金 {q.turnover_jpy / 1e8:.1f}億円"
        )

    # ③ 急落監視（リバウンド予備軍）
    if (
        q.gap_rate <= WATCH_DIP_PCT
        and q.volume_ratio >= WATCH_DIP_VOLUME_RATIO
        and q.turnover_jpy >= WATCH_VOLUME_SPIKE_TURNOVER
    ):
        reasons.append(
            f"急落監視 {q.gap_rate:+.1f}% / 出来高比 {q.volume_ratio:.1f}x"
        )

    return reasons
