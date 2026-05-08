#!/usr/bin/env python
# =============================================================================
# 実注文なし・研究用シグナルのみ
# このスクリプトは USD/JPY のシグナルを生成・保存するだけです。
# 実注文APIは一切呼びません。READ_ONLY/DRY_RUN 思想を守ります。
# =============================================================================

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from pathlib import Path

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import urllib.request
import json
from dotenv import load_dotenv

from src.fx.models import Candle, PriceSnapshot
from src.fx.signal_engine import SignalEngine
from src.fx.storage import FXSignalStorage
from src.fx.reporter import FXReporter
from src.fx.risk import EventCalendar
from src.fx.order_proposal import generate_fx_order_proposal, save_fx_order_proposal
from src.utils.logger import get_logger

log = get_logger("run_fx_usdjpy_signal")


def _env_true(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def ensure_research_safety() -> None:
    """
    FX検証は実注文機能を持たないが、運用思想として常に
    DRY_RUN=true / READ_ONLY=true の環境でだけ動かす。
    """
    if not _env_true("DRY_RUN", True):
        raise RuntimeError("FX signal research requires DRY_RUN=true")
    if not _env_true("READ_ONLY", True):
        raise RuntimeError("FX signal research requires READ_ONLY=true")


def fetch_latest_price() -> PriceSnapshot:
    """
    Frankfurter API から USD/JPY の最新レートを取得する。
    ask = mid * 1.0001, bid = mid * 0.9999 (合成スプレッド 0.2pips)
    実注文は一切行わない。
    """
    url = "https://api.frankfurter.app/latest?from=USD&to=JPY"
    log.info(f"価格取得: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "personal-ai-fund/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    mid = float(data["rates"]["JPY"])
    # 研究用の合成スプレッド。USD/JPY は 1 pip = 0.01。
    half_spread = 0.2 * 0.01 / 2
    ask = round(mid + half_spread, 4)
    bid = round(mid - half_spread, 4)
    timestamp = data.get("date", "") + "T00:00:00+09:00"
    log.info(f"USD/JPY mid={mid:.4f} ask={ask:.4f} bid={bid:.4f}")
    return PriceSnapshot(ask=ask, bid=bid, timestamp=timestamp)


def fetch_ohlcv_candles(days: int = 30) -> list[Candle]:
    """
    Frankfurter API から過去 days 日分の日次 OHLCV を取得して Candle リストに変換する。
    実注文は一切行わない。
    Frankfurter は OHLCV を提供しないため、日次終値を close/open/high/low に利用する。
    """
    end = date.today()
    start = end - timedelta(days=days)
    url = (
        f"https://api.frankfurter.app/{start}..{end}?from=USD&to=JPY"
    )
    log.info(f"OHLCV取得: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "personal-ai-fund/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    rates = data.get("rates", {})
    candles: list[Candle] = []
    sorted_dates = sorted(rates.keys())
    for d_str in sorted_dates:
        rate = float(rates[d_str]["JPY"])
        # Frankfurter は日次終値のみ提供。OHLC はすべて同値として Candle を生成。
        candles.append(
            Candle(
                timestamp=f"{d_str}T00:00:00+09:00",
                open=rate,
                high=rate,
                low=rate,
                close=rate,
                volume=0.0,
            )
        )
    log.info(f"Candle {len(candles)}本 取得完了 ({start} ~ {end})")
    return candles


def main() -> None:
    load_dotenv()
    log.info("=" * 60)
    log.info("FX USD/JPY シグナル検証開始（実注文なし・研究用）")
    log.info("=" * 60)

    try:
        ensure_research_safety()
    except Exception as e:
        log.error(str(e))
        sys.exit(1)

    # 1. 価格取得
    try:
        price_snapshot = fetch_latest_price()
    except Exception as e:
        log.error(f"価格取得エラー: {e}")
        sys.exit(1)

    # 2. OHLCV取得（過去30日分）
    try:
        candles = fetch_ohlcv_candles(days=30)
    except Exception as e:
        log.error(f"OHLCV取得エラー: {e}")
        sys.exit(1)

    # 3. シグナル生成（実注文は一切なし）
    engine = SignalEngine()
    calendar = EventCalendar()
    signal = engine.generate(candles, price_snapshot, event_calendar=calendar)

    log.info(f"シグナル: {signal.signal_id}")
    log.info(f"  action       : {signal.action}")
    log.info(f"  price (mid)  : {signal.price:.4f}")
    log.info(f"  ask          : {signal.ask:.4f}")
    log.info(f"  bid          : {signal.bid:.4f}")
    log.info(f"  spread       : {signal.spread_pips:.2f} pips")
    log.info(f"  stop_loss    : {signal.stop_loss}")
    log.info(f"  take_profit  : {signal.take_profit}")
    log.info(f"  reasons      : {signal.reasons}")
    if signal.skip_reason:
        log.info(f"  skip_reason  : {signal.skip_reason}")

    # 4. FXSignalStorage に保存（実注文は一切なし）
    storage = FXSignalStorage()
    saved = storage.save(signal)
    if saved:
        log.info(f"シグナルをDBに保存しました: {signal.signal_id}")
    else:
        log.info(f"シグナルは重複のためスキップ: {signal.signal_id}")

    # 5. BUY/SELL の場合だけ、実行しない注文提案を保存
    proposal, proposal_reason = generate_fx_order_proposal(signal)
    if proposal:
        stored_proposal, proposal_saved = save_fx_order_proposal(proposal)
        if proposal_saved:
            log.info(f"FX注文提案を保存しました（実注文なし）: {stored_proposal['proposal_id']}")
        else:
            log.info(f"FX注文提案は重複のためスキップ: {stored_proposal['proposal_id']}")
    else:
        log.info(f"FX注文提案なし: {proposal_reason}")

    # 6. レポート生成
    recent_signals = storage.get_latest(n=50)
    reporter = FXReporter()
    report_text = reporter.generate_summary(recent_signals)
    report_path = reporter.save_report(report_text)

    print("\n" + report_text)
    print(f"\nレポート保存先: {report_path}")
    log.info("FX USD/JPY シグナル検証完了（実注文なし）")


if __name__ == "__main__":
    main()
