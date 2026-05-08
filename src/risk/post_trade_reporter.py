"""
post_trade_reporter.py — 発注後の検証レポートを生成・保存する。

live_order_once.py の終了時に呼ばれる。
レポート生成の失敗は発注処理の結果に影響しない（独立したステップ）。

生成物:
  reports/post_trade_YYYYMMDD_HHMMSS.md  — Markdown レポート
  logs/post_trade_YYYYMMDD_HHMMSS.log    — ログファイル

次回発注可否チェック（以下のいずれかで NG）:
  - pending_orders に OPEN が残っている
  - 注文ステータスが FILLED でも CANCELLED でもない
  - execution_state と API 残高がズレている（DRY_RUN=false のみ）
  - エラーが発生している
  - STOP_TRADING が存在する
  - 本日約定回数が上限に達している
"""
from __future__ import annotations

import time
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.risk.execution_state import ExecutionState, ExecutionStore
from src.risk.pending_orders import PendingOrderStore, DB_PATH, STATUS_FILLED, STATUS_CANCELLED
from src.risk.risk_config import RiskConfig
from src.utils.logger import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# 残高ズレ許容値
_BALANCE_JPY_TOLERANCE = 10.0      # 円
_BALANCE_BTC_TOLERANCE = 1e-6      # BTC


@dataclass
class PostTradeReport:
    # --- メタ ---
    generated_at: float             # unix time
    dry_run: bool

    # --- 注文情報 ---
    order_id: str
    symbol: str
    side: str
    order_type: str
    order_price: float
    order_quantity: float
    order_amount_jpy: float
    order_status: str               # FILLED / CANCELLED / OPEN / EXPIRED / UNKNOWN

    # --- 約定情報 ---
    fill_price: float               # 約定価格（FILLED 以外は 0.0）
    fill_quantity: float            # 約定数量
    fee_jpy: float                  # 手数料（GMOコイン現物は 0 が多い）

    # --- 残高・ポジション変化 ---
    balance_jpy_before: float
    balance_jpy_after: float
    btc_held_before: float
    btc_held_after: float

    # --- API残高との比較（DRY_RUN=false のみ）---
    api_balance_jpy: float          # API から取得した最新残高（-1 = 取得せず）
    api_btc_held: float             # API から取得した最新BTC量（-1 = 取得せず）
    balance_discrepancy: bool       # ズレがあれば True

    # --- 集計 ---
    open_orders_count: int
    executions_today_count: int

    # --- エラー ---
    errors: List[str] = field(default_factory=list)

    # --- 次回発注可否 ---
    next_order_allowed: bool = True
    next_order_blocked_reasons: List[str] = field(default_factory=list)

    @property
    def generated_at_str(self) -> str:
        return datetime.datetime.fromtimestamp(self.generated_at).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def file_suffix(self) -> str:
        return datetime.datetime.fromtimestamp(self.generated_at).strftime("%Y%m%d_%H%M%S")


def generate_report(
    order_id: str,
    state_before: ExecutionState,
    state_after: ExecutionState,
    config: RiskConfig,
    db_path: Path = DB_PATH,
    adapter=None,
    errors: Optional[List[str]] = None,
    stop_trading_file: Optional[Path] = None,
) -> PostTradeReport:
    """
    発注後レポートを生成して返す。

    state_before : place_order 前の ExecutionState（pre_trade_sync の結果）
    state_after  : watch_orders 完了後の ExecutionState（最新状態）
    adapter      : GMOPrivateAdapter（DRY_RUN=false 時に API 残高確認に使う）
    errors       : 発注〜監視中に発生したエラー文字列のリスト
    """
    errors = list(errors or [])
    now = time.time()
    dry_run = config.dry_run

    # --- 注文情報を pending_orders から取得 ---
    pending_store = PendingOrderStore(db_path=db_path)
    pending = pending_store.load_by_id(order_id)

    if pending is None:
        log.warning(f"注文 {order_id} が pending_orders に見つかりません")
        # 注文情報不明で最低限のレポートを返す
        return PostTradeReport(
            generated_at=now, dry_run=dry_run,
            order_id=order_id, symbol="UNKNOWN", side="UNKNOWN",
            order_type="UNKNOWN", order_price=0.0, order_quantity=0.0,
            order_amount_jpy=0.0, order_status="UNKNOWN",
            fill_price=0.0, fill_quantity=0.0, fee_jpy=0.0,
            balance_jpy_before=state_before.balance_jpy,
            balance_jpy_after=state_after.balance_jpy,
            btc_held_before=state_before.btc_held,
            btc_held_after=state_after.btc_held,
            api_balance_jpy=-1.0, api_btc_held=-1.0,
            balance_discrepancy=False,
            open_orders_count=pending_store.open_order_count(),
            executions_today_count=len(state_after.executions_today),
            errors=errors + [f"注文 {order_id} が DB に見つかりません"],
            next_order_allowed=False,
            next_order_blocked_reasons=["注文情報が DB に存在しません"],
        )

    order_status = pending.status

    # --- 約定情報（FILLED の場合は execution_store から取得）---
    fill_price = 0.0
    fill_quantity = 0.0
    fill_execution_id = f"fill_{order_id}"
    execution_store = ExecutionStore(db_path=db_path)
    today_execs = execution_store.load_today(pending.symbol)
    for ex in today_execs:
        if ex.execution_id == fill_execution_id:
            fill_price = ex.price
            fill_quantity = ex.quantity
            break
    if order_status == STATUS_FILLED and fill_price == 0.0:
        # execution_id が一致しない場合は直近の約定価格を使う
        fill_price = pending.price
        fill_quantity = pending.quantity

    # --- API 残高取得（DRY_RUN=false のみ）---
    api_balance_jpy = -1.0
    api_btc_held = -1.0
    balance_discrepancy = False
    if not dry_run and adapter is not None:
        try:
            bal = adapter.get_balance()
            api_balance_jpy = bal["jpy"]
            api_btc_held = bal["btc"]
            # ズレ判定
            jpy_diff = abs(state_after.balance_jpy - api_balance_jpy)
            btc_diff = abs(state_after.btc_held - api_btc_held)
            if jpy_diff > _BALANCE_JPY_TOLERANCE or btc_diff > _BALANCE_BTC_TOLERANCE:
                balance_discrepancy = True
                log.warning(
                    f"残高ズレ検出: "
                    f"JPY ローカル=¥{state_after.balance_jpy:,.0f} API=¥{api_balance_jpy:,.0f} "
                    f"差=¥{jpy_diff:,.0f} | "
                    f"BTC ローカル={state_after.btc_held:.8f} API={api_btc_held:.8f} "
                    f"差={btc_diff:.8f}"
                )
        except Exception as e:
            errors.append(f"API残高取得失敗: {e}")
            log.error(f"レポート用 API 残高取得失敗: {e}")

    # --- 集計 ---
    open_count = pending_store.open_order_count()
    exec_today = len(state_after.executions_today)

    # --- 次回発注可否チェック ---
    blocked_reasons: List[str] = []

    if open_count > 0:
        blocked_reasons.append(f"未処理注文が {open_count} 件残っています")

    terminal_statuses = {STATUS_FILLED, STATUS_CANCELLED, "EXPIRED"}
    if order_status not in terminal_statuses:
        blocked_reasons.append(
            f"注文ステータスが未確定です: {order_status}（FILLED または CANCELLED になるまで待ってください）"
        )

    if balance_discrepancy:
        blocked_reasons.append(
            f"残高ズレ: ローカル ¥{state_after.balance_jpy:,.0f} / API ¥{api_balance_jpy:,.0f}"
        )

    if errors:
        blocked_reasons.append(f"エラーが {len(errors)} 件発生しています: {errors[0]}")

    if stop_trading_file is None:
        stop_trading_file = config.stop_trading_file
    if stop_trading_file.exists():
        blocked_reasons.append("STOP_TRADING ファイルが存在します")

    if exec_today >= config.max_daily_orders:
        blocked_reasons.append(
            f"本日の約定回数が上限に達しています: {exec_today}/{config.max_daily_orders}"
        )

    next_allowed = len(blocked_reasons) == 0

    return PostTradeReport(
        generated_at=now,
        dry_run=dry_run,
        order_id=order_id,
        symbol=pending.symbol,
        side=pending.side,
        order_type=pending.order_type,
        order_price=pending.price,
        order_quantity=pending.quantity,
        order_amount_jpy=pending.amount_jpy,
        order_status=order_status,
        fill_price=fill_price,
        fill_quantity=fill_quantity,
        fee_jpy=0.0,   # GMOコイン現物は手数料0（メイカー/テイカーで変わるが一旦0）
        balance_jpy_before=state_before.balance_jpy,
        balance_jpy_after=state_after.balance_jpy,
        btc_held_before=state_before.btc_held,
        btc_held_after=state_after.btc_held,
        api_balance_jpy=api_balance_jpy,
        api_btc_held=api_btc_held,
        balance_discrepancy=balance_discrepancy,
        open_orders_count=open_count,
        executions_today_count=exec_today,
        errors=errors,
        next_order_allowed=next_allowed,
        next_order_blocked_reasons=blocked_reasons,
    )


def generate_failed_order_report(
    symbol: str,
    side: str,
    order_type: str,
    order_price: float,
    order_quantity: float,
    order_amount_jpy: float,
    state_before: ExecutionState,
    config: RiskConfig,
    errors: Optional[List[str]] = None,
) -> PostTradeReport:
    """発注前後で pending_orders が作られていない失敗時のレポート。"""
    errors = list(errors or [])
    return PostTradeReport(
        generated_at=time.time(),
        dry_run=config.dry_run,
        order_id="FAILED_TO_PLACE",
        symbol=symbol,
        side=side,
        order_type=order_type,
        order_price=order_price,
        order_quantity=order_quantity,
        order_amount_jpy=order_amount_jpy,
        order_status="FAILED",
        fill_price=0.0,
        fill_quantity=0.0,
        fee_jpy=0.0,
        balance_jpy_before=state_before.balance_jpy,
        balance_jpy_after=state_before.balance_jpy,
        btc_held_before=state_before.btc_held,
        btc_held_after=state_before.btc_held,
        api_balance_jpy=-1.0,
        api_btc_held=-1.0,
        balance_discrepancy=False,
        open_orders_count=0,
        executions_today_count=len(state_before.executions_today),
        errors=errors,
        next_order_allowed=False,
        next_order_blocked_reasons=["発注に失敗したため次回発注を停止"],
    )


def save_report(
    report: PostTradeReport,
    reports_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
) -> tuple[Path, Path]:
    """
    レポートを Markdown と ログファイルに保存する。

    Returns:
        (md_path, log_path)
    """
    if reports_dir is None:
        reports_dir = ROOT / "reports"
    if logs_dir is None:
        logs_dir = ROOT / "logs"

    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    suffix = report.file_suffix
    prefix = "failed_order" if report.order_status == "FAILED" else "post_trade"
    md_path = reports_dir / f"{prefix}_{suffix}.md"
    log_path = logs_dir / f"{prefix}_{suffix}.log"

    md_content = _render_markdown(report)
    log_content = _render_log(report)

    md_path.write_text(md_content, encoding="utf-8")
    log_path.write_text(log_content, encoding="utf-8")

    log.info(f"レポート保存: {md_path}")
    log.info(f"ログ保存: {log_path}")
    return md_path, log_path


def _render_markdown(r: PostTradeReport) -> str:
    next_status = "✅ OK" if r.next_order_allowed else "❌ NG"
    mode = "[DRY_RUN]" if r.dry_run else "[LIVE]"

    lines = [
        f"# 発注後検証レポート {mode}",
        f"",
        f"生成日時: {r.generated_at_str}",
        f"",
        f"## 注文情報",
        f"",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 注文ID | `{r.order_id}` |",
        f"| シンボル | {r.symbol} |",
        f"| 売買方向 | {r.side} |",
        f"| 注文タイプ | {r.order_type} |",
        f"| 注文価格 | ¥{r.order_price:,.0f} |",
        f"| 注文数量 | {r.order_quantity:.8f} BTC |",
        f"| 注文額 | ¥{r.order_amount_jpy:,.0f} |",
        f"| 注文ステータス | **{r.order_status}** |",
        f"",
        f"## 約定情報",
        f"",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 約定価格 | {'¥{:,.0f}'.format(r.fill_price) if r.fill_price > 0 else '—'} |",
        f"| 約定数量 | {r.fill_quantity:.8f} BTC |",
        f"| 手数料 | ¥{r.fee_jpy:,.2f} |",
        f"",
        f"## 残高・ポジション変化",
        f"",
        f"| 項目 | 発注前 | 発注後 | 変化 |",
        f"|---|---|---|---|",
        f"| 円残高 | ¥{r.balance_jpy_before:,.0f} | ¥{r.balance_jpy_after:,.0f}"
        f" | {'¥{:+,.0f}'.format(r.balance_jpy_after - r.balance_jpy_before)} |",
        f"| BTC 保有 | {r.btc_held_before:.8f} | {r.btc_held_after:.8f}"
        f" | {r.btc_held_after - r.btc_held_before:+.8f} |",
    ]

    if r.api_balance_jpy >= 0:
        discrepancy_mark = "⚠️ ズレあり" if r.balance_discrepancy else "✅ 一致"
        lines += [
            f"",
            f"## API 残高確認",
            f"",
            f"| 項目 | ローカル | API | 判定 |",
            f"|---|---|---|---|",
            f"| 円残高 | ¥{r.balance_jpy_after:,.0f} | ¥{r.api_balance_jpy:,.0f} | {discrepancy_mark} |",
            f"| BTC | {r.btc_held_after:.8f} | {r.api_btc_held:.8f} | {discrepancy_mark} |",
        ]

    lines += [
        f"",
        f"## 集計",
        f"",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 未処理注文（OPEN） | {r.open_orders_count} 件 |",
        f"| 本日約定件数 | {r.executions_today_count} 件 |",
    ]

    if r.errors:
        lines += [
            f"",
            f"## エラー",
            f"",
        ]
        for e in r.errors:
            lines.append(f"- ⚠️ {e}")

    lines += [
        f"",
        f"## 次回発注可否",
        f"",
        f"**{next_status}**",
    ]
    if r.next_order_blocked_reasons:
        lines.append("")
        for reason in r.next_order_blocked_reasons:
            lines.append(f"- ❌ {reason}")
    else:
        lines.append("")
        lines.append("全チェック通過。次回発注可能です。")

    return "\n".join(lines) + "\n"


def _render_log(r: PostTradeReport) -> str:
    mode = "DRY_RUN" if r.dry_run else "LIVE"
    lines = [
        f"[{r.generated_at_str}] post_trade_report [{mode}]",
        f"order_id={r.order_id} symbol={r.symbol} side={r.side} type={r.order_type}",
        f"order_price={r.order_price:.0f} quantity={r.order_quantity:.8f} amount_jpy={r.order_amount_jpy:.0f}",
        f"status={r.order_status} fill_price={r.fill_price:.0f} fill_qty={r.fill_quantity:.8f}",
        f"balance_jpy: {r.balance_jpy_before:.0f} -> {r.balance_jpy_after:.0f}",
        f"btc_held: {r.btc_held_before:.8f} -> {r.btc_held_after:.8f}",
        f"open_orders={r.open_orders_count} exec_today={r.executions_today_count}",
    ]
    if r.api_balance_jpy >= 0:
        lines.append(
            f"api_jpy={r.api_balance_jpy:.0f} api_btc={r.api_btc_held:.8f}"
            f" discrepancy={r.balance_discrepancy}"
        )
    if r.errors:
        lines.append(f"errors={r.errors}")
    next_label = "OK" if r.next_order_allowed else "NG"
    reasons = "; ".join(r.next_order_blocked_reasons) if r.next_order_blocked_reasons else "none"
    lines.append(f"next_order={next_label} reasons=[{reasons}]")
    return "\n".join(lines) + "\n"
