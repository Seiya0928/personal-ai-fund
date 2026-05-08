# 実注文なし・研究用シグナルのみ
# このモジュールは実注文APIを一切呼びません。

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.fx.models import Candle, FXSignal, PriceSnapshot, SignalAction
from src.fx.risk import EventCalendar
from src.utils.logger import get_logger

log = get_logger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class SignalEngine:
    """
    USD/JPY 専用シグナルエンジン（研究用・実注文なし）
    実注文APIは一切呼ばない。READ_ONLY/DRY_RUN思想を守る。
    """

    SYMBOL = "USD/JPY"
    MIN_CANDLES = 20          # 20本未満はSKIP
    MAX_SPREAD_PIPS = 1.0     # スプレッド1pip超はSKIP
    RSI_PERIOD = 14
    DROP_THRESHOLD = 0.003    # 0.3%下落でBUY候補
    RISE_THRESHOLD = 0.003    # 0.3%上昇でSELL候補

    # SL/TP オフセット（円）
    BUY_SL_OFFSET = 0.30
    BUY_TP_OFFSET = 0.50
    SELL_SL_OFFSET = 0.30
    SELL_TP_OFFSET = 0.50

    def generate(
        self,
        candles: list[Candle],
        price_snapshot: PriceSnapshot,
        event_calendar: Optional[EventCalendar] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> FXSignal:
        """
        シグナルを生成する（実注文は一切行わない）。

        判定順序:
          1. candles 本数チェック（MIN_CANDLES未満 → SKIP）
          2. スプレッドチェック（MAX_SPREAD_PIPS超 → SKIP）
          3. 重要イベント近傍チェック（event_calendar → SKIP）
          4. RSI計算
          5. RSI < 30 and drop > DROP_THRESHOLD → BUY
          6. RSI > 70 and rise > RISE_THRESHOLD → SELL
          7. 上記以外 → WATCH
        """
        now_jst = evaluation_time or datetime.now(JST)
        if now_jst.tzinfo is None:
            now_jst = now_jst.replace(tzinfo=JST)
        now_jst = now_jst.astimezone(JST)
        ts_str = now_jst.strftime("%Y%m%d_%H%M%S")
        mid = price_snapshot.mid
        spread = price_snapshot.spread_pips

        def _make_signal(
            action: SignalAction,
            reasons: list[str],
            stop_loss: Optional[float] = None,
            take_profit: Optional[float] = None,
            skip_reason: Optional[str] = None,
        ) -> FXSignal:
            signal_id = f"usdjpy_{ts_str}_{action.lower()}"
            return FXSignal(
                signal_id=signal_id,
                symbol=self.SYMBOL,
                action=action,
                price=round(mid, 4),
                ask=round(price_snapshot.ask, 4),
                bid=round(price_snapshot.bid, 4),
                spread_pips=round(spread, 4),
                timestamp=now_jst.isoformat(),
                reasons=reasons,
                stop_loss=stop_loss,
                take_profit=take_profit,
                skip_reason=skip_reason,
            )

        # 0. 価格スナップショット妥当性チェック
        if price_snapshot.ask <= 0 or price_snapshot.bid <= 0:
            reason = "価格スナップショット不正: ask/bid must be positive"
            log.info(f"[SignalEngine] SKIP: {reason}")
            return _make_signal("SKIP", [reason], skip_reason=reason)
        if price_snapshot.ask < price_snapshot.bid:
            reason = "価格スナップショット不正: ask < bid"
            log.info(f"[SignalEngine] SKIP: {reason}")
            return _make_signal("SKIP", [reason], skip_reason=reason)

        # 1. candles 本数チェック
        if len(candles) < self.MIN_CANDLES:
            reason = f"データ不足: {len(candles)}本 < MIN_CANDLES={self.MIN_CANDLES}"
            log.info(f"[SignalEngine] SKIP: {reason}")
            return _make_signal("SKIP", [reason], skip_reason=reason)

        # 2. スプレッドチェック
        if spread > self.MAX_SPREAD_PIPS:
            reason = f"スプレッド過大: spread={spread:.2f}pips > MAX={self.MAX_SPREAD_PIPS}pips"
            log.info(f"[SignalEngine] SKIP: {reason}")
            return _make_signal("SKIP", [reason], skip_reason=reason)

        # 3. 重要イベント近傍チェック
        if event_calendar is not None:
            near, ev_reason = event_calendar.is_near_event(now_jst)
            if near:
                reason = f"重要イベント近傍: {ev_reason}"
                log.info(f"[SignalEngine] SKIP: {reason}")
                return _make_signal("SKIP", [reason], skip_reason=reason)

        # 4. RSI計算
        closes = [c.close for c in candles]
        rsi = self._compute_rsi(closes, self.RSI_PERIOD)
        change = self._recent_change(closes, n=5)

        reasons_base = [
            f"RSI={rsi:.2f}",
            f"直近5本変化率={change*100:.3f}%",
            f"spread={spread:.2f}pips",
            f"mid={mid:.4f}",
        ]

        # 5. BUYシグナル: RSI < 30 and 直近5本の変化率 < -DROP_THRESHOLD
        if rsi < 30 and change < -self.DROP_THRESHOLD:
            reasons = [
                f"RSI={rsi:.2f} < 30 (過売り)",
                f"直近5本変化率={change*100:.3f}% < -{self.DROP_THRESHOLD*100:.1f}% (下落)",
                f"spread={spread:.2f}pips",
                f"mid={mid:.4f}",
            ]
            sl = round(mid - self.BUY_SL_OFFSET, 4)
            tp = round(mid + self.BUY_TP_OFFSET, 4)
            log.info(f"[SignalEngine] BUY: RSI={rsi:.2f}, change={change*100:.3f}%")
            return _make_signal("BUY", reasons, stop_loss=sl, take_profit=tp)

        # 6. SELLシグナル: RSI > 70 and 直近5本の変化率 > RISE_THRESHOLD
        if rsi > 70 and change > self.RISE_THRESHOLD:
            reasons = [
                f"RSI={rsi:.2f} > 70 (過買い)",
                f"直近5本変化率={change*100:.3f}% > {self.RISE_THRESHOLD*100:.1f}% (上昇)",
                f"spread={spread:.2f}pips",
                f"mid={mid:.4f}",
            ]
            sl = round(mid + self.SELL_SL_OFFSET, 4)
            tp = round(mid - self.SELL_TP_OFFSET, 4)
            log.info(f"[SignalEngine] SELL: RSI={rsi:.2f}, change={change*100:.3f}%")
            return _make_signal("SELL", reasons, stop_loss=sl, take_profit=tp)

        # 7. WATCH: 上記以外
        reasons = [
            f"RSI={rsi:.2f} (中立域)",
            f"直近5本変化率={change*100:.3f}%",
            f"spread={spread:.2f}pips",
            f"mid={mid:.4f}",
        ]
        log.info(f"[SignalEngine] WATCH: RSI={rsi:.2f}, change={change*100:.3f}%")
        return _make_signal("WATCH", reasons)

    def _compute_rsi(self, closes: list[float], period: int) -> float:
        """
        RSIを計算する（Wilder法）。
        closes は古い順。最低 period+1 本必要。
        """
        if len(closes) < period + 1:
            return 50.0  # データ不足時は中立値

        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        # 最初のperiod本で初期平均
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Wilder平滑化
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 4)

    def _recent_change(self, closes: list[float], n: int = 5) -> float:
        """
        直近 n 本の変化率を返す。
        (closes[-1] - closes[-n-1]) / closes[-n-1]
        """
        if len(closes) < n + 1:
            return 0.0
        base = closes[-(n + 1)]
        if base == 0:
            return 0.0
        return (closes[-1] - base) / base
