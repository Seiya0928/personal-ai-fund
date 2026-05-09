#!/usr/bin/env python
"""
FX USD/JPY 日次シグナル・記録スクリプト（BTC型統合版）
実注文なし・研究用のみ。DRY_RUN=true / READ_ONLY=true 必須。

使用方法:
    python scripts/run_fx_daily.py
    python scripts/run_fx_daily.py --no-paper-trade
    python scripts/run_fx_daily.py --dry-run-record PROPOSAL_ID

処理フロー:
    1. DRY_RUN/READ_ONLY 確認
    2. Frankfurter API で価格・OHLCV 取得
    3. stale 判定
    4. SignalEngine でシグナル生成
    5. open FX paper trades を現在価格で更新
    6. 既存 open paper trade の決済候補チェック → fx_status 決定
    7. FX signal record を fx_signal_history.json に保存
    8. FX_CANDIDATE + stale非invalidの場合:
       a. FX order proposal 生成・保存
       b. FX paper trade 生成・保存
    9. 既存 SQLite + reporter も引き続き実行
   10. Markdown report 生成

禁止事項:
    - 実注文API呼び出し
    - DRY_RUN=false
    - READ_ONLY=false
    - GMO Private API
    - live_order_once.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from src.fx.models import Candle, PriceSnapshot
from src.fx.signal_engine import SignalEngine
from src.fx.risk import EventCalendar
from src.fx.storage import FXSignalStorage
from src.fx.reporter import FXReporter
from src.fx.order_proposal import generate_fx_order_proposal, save_fx_order_proposal
from src.fx.fx_status import FXAssessment, signal_action_to_fx_status, get_next_action
from src.fx.fx_stale_checker import check_stale
from src.fx.fx_signal_history import build_fx_signal_record, save_fx_signal_record
from src.fx.fx_paper_trade import (
    create_fx_paper_trades_from_proposal,
    update_open_fx_paper_trades,
    DEFAULT_FX_PAPER_TRADES_PATH,
)
from src.fx.fx_dry_run_recorder import record_fx_dry_run_order, DEFAULT_FX_DRY_RUN_ORDERS_PATH
from src.utils.logger import get_logger

log = get_logger("run_fx_daily")
JST = ZoneInfo("Asia/Tokyo")


def _env_true(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def ensure_research_safety() -> None:
    """DRY_RUN=true / READ_ONLY=true の環境でだけ動かす。"""
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
    """
    end = date.today()
    start = end - timedelta(days=days)
    url = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=JPY"
    log.info(f"OHLCV取得: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "personal-ai-fund/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rates = data.get("rates", {})
    candles: list[Candle] = []
    for d_str in sorted(rates.keys()):
        rate = float(rates[d_str]["JPY"])
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


def handle_dry_run_record(proposal_id: str) -> None:
    """指定 proposal_id の dry-run 注文記録を対話的に実行する。"""
    from src.fx.order_proposal import load_fx_order_proposals, DEFAULT_FX_ORDER_PROPOSALS_PATH
    proposals = load_fx_order_proposals(DEFAULT_FX_ORDER_PROPOSALS_PATH)["proposals"]
    proposal = next((p for p in proposals if p.get("proposal_id") == proposal_id), None)
    if not proposal:
        print(f"[ERROR] proposal_id '{proposal_id}' が見つかりません。")
        sys.exit(1)

    print(f"[DRY-RUN RECORD] proposal_id: {proposal_id}")
    print(f"  symbol: {proposal.get('symbol')}, side: {proposal.get('side')}")
    print(f"  price: {proposal.get('suggested_price')}, SL: {proposal.get('stop_loss')}, TP: {proposal.get('take_profit')}")
    approval = input("承認フレーズを入力してください: ").strip()

    order, reason = record_fx_dry_run_order(
        proposal=proposal,
        approval_input=approval,
        dry_run=True,
        read_only=True,
        path=DEFAULT_FX_DRY_RUN_ORDERS_PATH,
    )
    if order:
        print(f"[OK] {reason}: order_id={order.get('order_id')}")
    else:
        print(f"[SKIP] {reason}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="FX USD/JPY 日次シグナル・記録スクリプト（実注文なし）")
    parser.add_argument("--no-paper-trade", action="store_true", help="paper trade作成をスキップ")
    parser.add_argument("--dry-run-record", metavar="PROPOSAL_ID", help="指定proposal_idをdry-run記録")
    parser.add_argument("--report-only", action="store_true", help="シグナル生成・記録のみ（paper trade/proposal 作成なし）")
    args = parser.parse_args()

    # dry-run record サブコマンド
    if args.dry_run_record:
        handle_dry_run_record(args.dry_run_record)
        return

    print("=" * 60)
    print("FX USD/JPY 日次シグナル（BTC型統合版）実注文なし・研究用")
    print("=" * 60)

    # Step 1: Safety check
    try:
        ensure_research_safety()
        print("[1/9] Safety check: OK (DRY_RUN=true, READ_ONLY=true)")
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Step 2: 価格・OHLCV 取得
    try:
        price_snapshot = fetch_latest_price()
        print(f"[2/9] 価格取得: USD/JPY mid≈{(price_snapshot.ask + price_snapshot.bid) / 2:.4f}")
    except Exception as e:
        print(f"[ERROR] 価格取得エラー: {e}")
        sys.exit(1)

    try:
        candles = fetch_ohlcv_candles(days=30)
        print(f"[2/9] OHLCV取得: {len(candles)}本")
    except Exception as e:
        print(f"[ERROR] OHLCV取得エラー: {e}")
        sys.exit(1)

    current_price = round((price_snapshot.ask + price_snapshot.bid) / 2, 4)
    as_of_jst = datetime.now(JST).isoformat(timespec="seconds")

    # Step 3: Stale 判定
    stale = check_stale(price_snapshot.timestamp)
    print(f"[3/9] Stale check: {stale.level} ({stale.reason})")

    # Step 4: SignalEngine でシグナル生成
    engine = SignalEngine()
    calendar = EventCalendar()
    signal = engine.generate(candles, price_snapshot, event_calendar=calendar)
    print(f"[4/9] Signal: action={signal.action}, price={signal.price:.4f}, SL={signal.stop_loss}, TP={signal.take_profit}")

    # Step 5: open FX paper trades を現在価格で更新
    try:
        updated_trades, update_count = update_open_fx_paper_trades(
            current_price=current_price,
            as_of_jst=as_of_jst,
            path=DEFAULT_FX_PAPER_TRADES_PATH,
        )
        print(f"[5/9] Paper trades更新: {update_count}件")
    except Exception as e:
        print(f"[WARN] Paper trades更新エラー（続行）: {e}")
        updated_trades = []

    # Step 6: open position exit reason 判定 → fx_status 決定
    closed_current = [t for t in updated_trades if t.get("rule_id") == "Current" and t.get("exit_reason")]
    open_position_exit_reason: Optional[str] = closed_current[0]["exit_reason"] if closed_current else None

    fx_status = signal_action_to_fx_status(
        action=signal.action,
        is_stale_invalid=stale.is_invalid,
        open_position_exit_reason=open_position_exit_reason,
    )
    next_action_text = get_next_action(fx_status)
    print(f"[6/9] FX Status: {fx_status}")

    assessment = FXAssessment(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        action=signal.action,
        fx_status=fx_status,
        next_action=next_action_text,
        current_price=current_price,
        market_data_timestamp=price_snapshot.timestamp,
        stale_level=stale.level,
        stale_reason=stale.reason,
        is_stale_invalid=stale.is_invalid,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        reasons=list(signal.reasons),
        skip_reason=signal.skip_reason,
        open_position_exit_reason=open_position_exit_reason,
    )

    # Step 7: FX signal record 保存
    record = build_fx_signal_record(assessment, created_at=as_of_jst)
    try:
        stored_record, is_new = save_fx_signal_record(record)
        status_str = "保存" if is_new else "重複スキップ"
        print(f"[7/9] Signal history: {status_str} ({stored_record['signal_id']})")
    except Exception as e:
        print(f"[WARN] Signal history保存エラー（続行）: {e}")
        stored_record = record

    # Step 8: FX_CANDIDATE + stale非invalid → proposal + paper trade
    proposal_dict: Optional[dict] = None
    paper_trades: list[dict] = []

    if not args.report_only and fx_status == "FX_CANDIDATE" and not stale.is_invalid:
        # 8a. Order proposal 生成・保存
        try:
            proposal_dict, proposal_reason = generate_fx_order_proposal(signal)
            if proposal_dict:
                saved_proposal, proposal_is_new = save_fx_order_proposal(proposal_dict)
                assessment.order_proposal_id = saved_proposal.get("proposal_id")
                p_status = "保存" if proposal_is_new else "重複スキップ"
                print(f"[8a/9] Order proposal: {p_status} ({saved_proposal.get('proposal_id')})")
            else:
                print(f"[8a/9] Order proposal なし: {proposal_reason}")
        except Exception as e:
            print(f"[WARN] Order proposal エラー（続行）: {e}")

        # 8b. Paper trade 生成・保存
        if not args.no_paper_trade and proposal_dict:
            try:
                paper_trades, pt_reason = create_fx_paper_trades_from_proposal(
                    signal_record=stored_record,
                    proposal=proposal_dict,
                )
                assessment.paper_trade_ids = [t["paper_trade_id"] for t in paper_trades]
                print(f"[8b/9] Paper trades: {len(paper_trades)}件 ({pt_reason})")
            except Exception as e:
                print(f"[WARN] Paper trade エラー（続行）: {e}")
    else:
        reason_skip = "report-only" if args.report_only else f"fx_status={fx_status}"
        print(f"[8/9] Proposal/Paper trade: スキップ ({reason_skip})")

    # Step 9: 既存 SQLite + reporter も実行
    try:
        storage = FXSignalStorage()
        saved_sqlite = storage.save(signal)
        sqlite_status = "保存" if saved_sqlite else "重複スキップ"
        print(f"[9/9] SQLite: {sqlite_status} ({signal.signal_id})")
    except Exception as e:
        print(f"[WARN] SQLite保存エラー（続行）: {e}")

    try:
        recent_signals = storage.get_latest(n=50)
        reporter = FXReporter()
        report_text = reporter.generate_summary(recent_signals)
        report_path = reporter.save_report(report_text)
    except Exception as e:
        print(f"[WARN] レポート生成エラー（続行）: {e}")
        report_text = ""
        report_path = None

    # Markdown サマリー出力
    print("\n" + "=" * 60)
    print("## FX USD/JPY Daily Report")
    print(f"- 実行時刻: {as_of_jst}")
    print(f"- 現在価格: {current_price:.4f} JPY/USD")
    print(f"- Stale: {stale.level} ({stale.reason})")
    print(f"- Signal action: {signal.action}")
    print(f"- FX Status: **{fx_status}**")
    print(f"- Next Action: {next_action_text}")
    if signal.stop_loss:
        print(f"- Stop Loss: {signal.stop_loss:.4f}")
    if signal.take_profit:
        print(f"- Take Profit: {signal.take_profit:.4f}")
    if signal.reasons:
        print(f"- Reasons: {', '.join(signal.reasons)}")
    if assessment.order_proposal_id:
        print(f"- Order Proposal ID: {assessment.order_proposal_id}")
    if paper_trades:
        print(f"- Paper Trades: {len(paper_trades)}件")
        for pt in paper_trades:
            print(f"  - {pt['paper_trade_id']} ({pt['rule_id']}, deadline={pt['max_holding_deadline']})")
    if report_path:
        print(f"\nレポート保存先: {report_path}")
    print("=" * 60)

    log.info("FX USD/JPY 日次シグナル（BTC型統合版）完了（実注文なし）")


if __name__ == "__main__":
    main()
