from datetime import datetime, timezone
from src.brokers.gmo_public import GMOPublicBroker
from src.storage.sqlite_store import SQLiteStore
from src.strategies.moving_average import MovingAverageCross
from src.utils.logger import get_logger

log = get_logger(__name__)


def generate(symbol: str = "BTC_JPY") -> str:
    broker = GMOPublicBroker()
    store = SQLiteStore()
    strategy = MovingAverageCross(short=5, long=20)

    ticker = broker.get_ticker(symbol)
    current_price = ticker["last"]

    daily_rows = store.load_ohlcv(symbol, "1day", limit=100)
    hourly_rows = store.load_ohlcv(symbol, "1hour", limit=100)
    signal_text = "データ不足"
    change_1h = None

    if len(daily_rows) >= 21:
        df = strategy.generate_signals(daily_rows)
        last_signal = df.iloc[-1]["signal"]
        if last_signal == 1:
            signal_text = "BUY (短期MA > 長期MA)"
        elif last_signal == -1:
            signal_text = "SELL (短期MA < 長期MA)"
        else:
            signal_text = "NEUTRAL"

    if len(hourly_rows) >= 2:
        prev_close = hourly_rows[-2]["close"]
        change_1h = (current_price - float(prev_close)) / float(prev_close) * 100

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"========== Daily Report ==========",
        f"生成日時  : {now}",
        f"銘柄      : {symbol}",
        f"現在価格  : ¥{current_price:,.0f}",
    ]
    if change_1h is not None:
        arrow = "▲" if change_1h >= 0 else "▼"
        lines.append(f"1時間変化率: {arrow}{abs(change_1h):.2f}%")
    lines += [
        f"売買シグナル: {signal_text}",
        "==================================",
    ]
    report = "\n".join(lines)
    log.info(f"\n{report}")
    return report
