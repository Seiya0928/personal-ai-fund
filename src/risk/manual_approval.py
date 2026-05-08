"""
manual_approval.py — 実発注前の手動承認ゲート。

READ_ONLY=false にしただけでは実注文できない。
承認フレーズを端末に正確に入力しないと place_order は絶対に呼ばれない。

設計方針:
  - 承認フレーズはハードコード（変更・設定不可）
  - 承認フレーズそのものはログに出力しない
  - 非対話環境（CI・パイプ・ファイルリダイレクト）では必ず False
  - タイムアウト（30秒）で自動キャンセル
"""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)

# 承認フレーズ（完全一致のみ通過）
_APPROVAL_PHRASE = "EXECUTE LIVE ORDER"

# 入力タイムアウト（秒）。signal.alarm は Unix のみ有効。
_INPUT_TIMEOUT_SECONDS = 30


@dataclass
class OrderPlan:
    """approve_order に渡す注文計画。"""
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: float
    amount_jpy: float


def _is_interactive() -> bool:
    """標準入力が端末（tty）かどうかを返す。パイプ・リダイレクト時は False。"""
    return sys.stdin.isatty()


def require_manual_approval(order_plan: OrderPlan) -> bool:
    """
    注文内容を表示して手動承認を求める。

    Returns:
        True  : 承認フレーズが完全一致 → 発注してよい
        False : 入力が違う / タイムアウト / 非対話環境 → 発注禁止
    """
    log.info("=" * 60)
    log.info("【手動承認ゲート】実発注の承認が必要です")
    log.info("-" * 60)
    log.info(f"  シンボル   : {order_plan.symbol}")
    log.info(f"  売買方向   : {order_plan.side}")
    log.info(f"  注文タイプ : {order_plan.order_type}")
    log.info(f"  指値価格   : ¥{order_plan.price:>15,.0f}")
    log.info(f"  数量       : {order_plan.quantity:.8f} BTC")
    log.info(f"  注文金額   : ¥{order_plan.amount_jpy:>10,.0f}")
    log.info("-" * 60)

    # 非対話環境では必ず拒否
    if not _is_interactive():
        log.warning("⛔ 非対話環境（CI・パイプ）を検出。手動承認をスキップして発注を中止します。")
        log.warning("   実発注は必ず端末から直接 live_order_once.py を実行してください。")
        return False

    # 承認フレーズの入力を求める（フレーズ自体はログに残さない）
    print(f"\n  承認するには以下のフレーズを正確に入力してください ({_INPUT_TIMEOUT_SECONDS}秒以内):")
    print(f"  > {_APPROVAL_PHRASE}\n")

    try:
        answer = _read_with_timeout("  入力 > ", _INPUT_TIMEOUT_SECONDS)
    except _TimeoutError:
        log.warning(f"⛔ {_INPUT_TIMEOUT_SECONDS}秒以内に入力がありませんでした。発注を中止します。")
        return False
    except (EOFError, KeyboardInterrupt):
        log.warning("⛔ 入力がキャンセルされました。発注を中止します。")
        return False

    approved = (answer == _APPROVAL_PHRASE)

    if approved:
        # 承認フレーズはログに出さない。承認された事実だけ記録する。
        log.info("✅ 手動承認: 発注を承認しました")
    else:
        # 入力内容もログに出さない（意図しない情報が残るのを防ぐ）
        log.warning("⛔ 手動承認: フレーズが一致しません。発注を中止します。")

    log.info("=" * 60)
    return approved


# ---------------------------------------------------------------------------
# タイムアウト付き入力（Unix / Windows 両対応）
# ---------------------------------------------------------------------------

class _TimeoutError(Exception):
    pass


def _read_with_timeout(prompt: str, timeout: int) -> str:
    """
    タイムアウト付きで標準入力を1行読む。
    Unix では signal.alarm、Windows では threading で実装。
    """
    # Unix 系: signal.SIGALRM が使える
    if hasattr(os, "fork"):  # Unix の判定（Windows には fork がない）
        import signal

        def _handler(signum, frame):
            raise _TimeoutError()

        old = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            return input(prompt)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    else:
        # Windows: threading で代替
        import threading
        result: list = []
        exception: list = []

        def _read():
            try:
                result.append(input(prompt))
            except Exception as e:
                exception.append(e)

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise _TimeoutError()
        if exception:
            raise exception[0]
        return result[0] if result else ""
