"""
仮注文シミュレーター。実発注は一切しない。
BUY BTC_JPY LIMIT 1000円相当を仮注文 → 仮約定フローで処理する。

フロー:
  1. pre_trade_sync()  — 約定ベースの最新状態を取得
  2. check_order_allowed() — リスクチェック
  3. submit_dry_run_order() — 仮注文をpending_ordersに登録
  4. simulate_fill() — 仮約定 → ポジション更新 → executions保存
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.risk.risk_manager import RiskManager
from src.brokers.gmo_public import GMOPublicBroker
from src.utils.logger import get_logger

log = get_logger("simulate_order")

SYMBOL     = "BTC_JPY"
SIDE       = "BUY"
ORDER_TYPE = "LIMIT"
AMOUNT_JPY = 1_000.0


def main():
    rm = RiskManager()
    broker = GMOPublicBroker()

    ticker = broker.get_ticker(SYMBOL)
    current_price = ticker["last"]
    quantity = AMOUNT_JPY / current_price

    print()
    print("========== 仮注文シミュレーション ==========")
    print(f"  DRY_RUN    : {rm.config.dry_run}")
    print(f"  シンボル   : {SYMBOL}")
    print(f"  売買方向   : {SIDE}")
    print(f"  注文タイプ : {ORDER_TYPE}")
    print(f"  注文額     : ¥{AMOUNT_JPY:,.0f}")
    print(f"  現在価格   : ¥{current_price:,.0f}")
    print(f"  数量       : {quantity:.8f} BTC")
    print("--------------------------------------------")

    # Step 1: 状態同期（必須）
    state = rm.pre_trade_sync(SYMBOL)
    print(f"  本日約定数 : {state.daily_execution_count()}回")
    print(f"  保有BTC    : {state.btc_held:.8f}")
    print(f"  平均取得単価: ¥{state.avg_entry_price:,.0f}")
    print("--------------------------------------------")

    # Step 2: リスクチェック
    result = rm.check_order_allowed(
        symbol=SYMBOL,
        side=SIDE,
        order_type=ORDER_TYPE,
        amount_jpy=AMOUNT_JPY,
        current_price_jpy=current_price,
        state=state,
    )
    print(f"  チェック結果: {result}")
    print("============================================")
    print()

    if not result.allowed:
        print("❌ リスクチェックでブロックされました。発注しません。")
        return

    # Step 3: 仮注文登録
    order = rm.submit_dry_run_order(
        symbol=SYMBOL,
        side=SIDE,
        order_type=ORDER_TYPE,
        price=current_price,
        quantity=quantity,
        amount_jpy=AMOUNT_JPY,
    )
    print(f"✅ 仮注文登録: order_id={order.order_id}")

    # Step 4: 仮約定 → ポジション更新
    ex = rm.simulate_fill(order, fill_price=current_price)
    print(f"✅ 仮約定完了: {ex.quantity:.8f} BTC @ ¥{ex.price:,.0f}")

    # 約定後の状態表示
    s = rm._state
    print()
    print("---------- 約定後の状態 ----------")
    print(f"  保有BTC    : {s.btc_held:.8f}")
    print(f"  平均取得単価: ¥{s.avg_entry_price:,.0f}")
    print(f"  本日約定数 : {s.daily_execution_count()}回")
    print(f"  BTC評価額  : ¥{s.btc_held * current_price:,.0f}")
    print("----------------------------------")
    print()
    print("   実発注するには DRY_RUN=false かつ Private API実装後に行います。")


if __name__ == "__main__":
    main()
