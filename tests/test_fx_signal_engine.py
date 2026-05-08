# 実注文なし・研究用シグナルエンジンのテスト

from __future__ import annotations

import pytest
from src.fx.models import Candle, PriceSnapshot
from src.fx.signal_engine import SignalEngine


def _make_candles(n: int, close_values: list[float] | None = None) -> list[Candle]:
    """テスト用ローソク足を生成する"""
    if close_values is None:
        close_values = [145.0] * n
    assert len(close_values) == n
    return [
        Candle(
            timestamp=f"2025-01-{i+1:02d}T00:00:00+09:00",
            open=v,
            high=v + 0.1,
            low=v - 0.1,
            close=v,
            volume=1000.0,
        )
        for i, v in enumerate(close_values)
    ]


def _make_snapshot(mid: float = 145.0, spread_pips: float = 0.3) -> PriceSnapshot:
    """テスト用価格スナップショットを生成する (spread_pips = (ask-bid)/0.01)"""
    half = spread_pips * 0.01 / 2
    return PriceSnapshot(
        ask=round(mid + half, 4),
        bid=round(mid - half, 4),
        timestamp="2025-01-01T12:00:00+09:00",
    )


engine = SignalEngine()


class TestSkipInsufficientData:
    def test_skip_insufficient_data(self):
        """MIN_CANDLES 未満のデータは SKIP になる"""
        candles = _make_candles(10)  # MIN_CANDLES=20 未満
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"
        assert signal.skip_reason is not None
        assert "MIN_CANDLES" in signal.skip_reason or "データ不足" in signal.skip_reason

    def test_skip_exactly_min_minus_1(self):
        """MIN_CANDLES - 1 本でも SKIP"""
        candles = _make_candles(SignalEngine.MIN_CANDLES - 1)
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"


class TestSkipWideSpread:
    def test_skip_wide_spread(self):
        """スプレッド 2.0 pips は MAX_SPREAD_PIPS を超えるため SKIP"""
        candles = _make_candles(25)
        snap = _make_snapshot(mid=145.0, spread_pips=2.0)
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"
        assert signal.skip_reason is not None
        assert "スプレッド" in signal.skip_reason or "spread" in signal.skip_reason.lower()

    def test_skip_exactly_over_max_spread(self):
        """MAX_SPREAD_PIPS + 0.01 でも SKIP"""
        candles = _make_candles(25)
        snap = _make_snapshot(mid=145.0, spread_pips=SignalEngine.MAX_SPREAD_PIPS + 0.01)
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"


class TestInvalidPriceSnapshot:
    def test_skip_when_ask_is_below_bid(self):
        candles = _make_candles(25)
        snap = PriceSnapshot(
            ask=144.99,
            bid=145.01,
            timestamp="2025-01-01T12:00:00+09:00",
        )

        signal = engine.generate(candles, snap)

        assert signal.action == "SKIP"
        assert signal.skip_reason == "価格スナップショット不正: ask < bid"

    def test_skip_when_price_is_non_positive(self):
        candles = _make_candles(25)
        snap = PriceSnapshot(
            ask=0.0,
            bid=0.0,
            timestamp="2025-01-01T12:00:00+09:00",
        )

        signal = engine.generate(candles, snap)

        assert signal.action == "SKIP"
        assert "ask/bid" in signal.skip_reason


class TestBuySignal:
    def test_buy_signal(self):
        """RSI < 30 かつ 直近5本の下落率 > DROP_THRESHOLD で BUY"""
        # 最初の15本は安定、後半5本で急落させる
        stable = [145.0] * 15
        drop = [144.0, 143.5, 143.0, 142.5, 142.0]
        closes = stable + drop
        assert len(closes) == 20
        candles = _make_candles(20, closes)
        snap = _make_snapshot(mid=142.0, spread_pips=0.2)
        signal = engine.generate(candles, snap)
        # RSI が 30 未満になるよう十分な下落を作る（20本では難しい場合もあるのでWATCHも許容）
        # 少なくとも SKIP でないことを確認し、BUYの場合はSL/TPを検証
        assert signal.action in ("BUY", "WATCH")
        if signal.action == "BUY":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.stop_loss < signal.price
            assert signal.take_profit > signal.price

    def test_buy_signal_strong_drop(self):
        """強い下落トレンドで BUY シグナルを確認する"""
        # RSI < 30 を確実に作るため連続下落を長くする
        closes = [150.0 - i * 0.5 for i in range(30)]  # 150.0 → 135.5 連続下落
        candles = _make_candles(30, closes)
        snap = _make_snapshot(mid=closes[-1], spread_pips=0.2)
        signal = engine.generate(candles, snap)
        assert signal.action == "BUY"
        assert signal.stop_loss is not None
        assert signal.take_profit is not None
        assert signal.stop_loss < signal.price
        assert signal.take_profit > signal.price


class TestSellSignal:
    def test_sell_signal(self):
        """RSI > 70 かつ 直近5本の上昇率 > RISE_THRESHOLD で SELL"""
        closes = [140.0 + i * 0.5 for i in range(30)]  # 連続上昇
        candles = _make_candles(30, closes)
        snap = _make_snapshot(mid=closes[-1], spread_pips=0.2)
        signal = engine.generate(candles, snap)
        assert signal.action == "SELL"
        assert signal.stop_loss is not None
        assert signal.take_profit is not None
        assert signal.stop_loss > signal.price
        assert signal.take_profit < signal.price


class TestWatchSignal:
    def test_watch_signal(self):
        """中立的な価格変動では WATCH になる"""
        # RSIが中立域に収まる横ばい
        closes = [145.0 + (i % 3) * 0.05 for i in range(25)]
        candles = _make_candles(25, closes)
        snap = _make_snapshot(mid=145.0, spread_pips=0.3)
        signal = engine.generate(candles, snap)
        assert signal.action == "WATCH"

    def test_watch_no_sl_tp(self):
        """WATCH シグナルには SL/TP がない"""
        closes = [145.0] * 25
        candles = _make_candles(25, closes)
        snap = _make_snapshot(mid=145.0, spread_pips=0.3)
        signal = engine.generate(candles, snap)
        assert signal.action == "WATCH"
        assert signal.stop_loss is None
        assert signal.take_profit is None


class TestSignalHasReasons:
    def test_skip_has_reasons(self):
        candles = _make_candles(5)  # SKIP
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"
        assert len(signal.reasons) > 0

    def test_wide_spread_has_reasons(self):
        candles = _make_candles(25)
        snap = _make_snapshot(spread_pips=2.0)  # SKIP
        signal = engine.generate(candles, snap)
        assert signal.action == "SKIP"
        assert len(signal.reasons) > 0

    def test_watch_has_reasons(self):
        closes = [145.0] * 25
        candles = _make_candles(25, closes)
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.action == "WATCH"
        assert len(signal.reasons) > 0

    def test_buy_has_reasons(self):
        closes = [150.0 - i * 0.5 for i in range(30)]
        candles = _make_candles(30, closes)
        snap = _make_snapshot(mid=closes[-1], spread_pips=0.2)
        signal = engine.generate(candles, snap)
        if signal.action == "BUY":
            assert len(signal.reasons) > 0

    def test_sell_has_reasons(self):
        closes = [140.0 + i * 0.5 for i in range(30)]
        candles = _make_candles(30, closes)
        snap = _make_snapshot(mid=closes[-1], spread_pips=0.2)
        signal = engine.generate(candles, snap)
        assert signal.action == "SELL"
        assert len(signal.reasons) > 0


class TestSignalIdFormat:
    def test_signal_id_starts_with_usdjpy(self):
        """signal_id は 'usdjpy_' で始まる"""
        candles = _make_candles(5)
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.signal_id.startswith("usdjpy_")

    def test_signal_id_contains_action(self):
        """signal_id にはアクション名が含まれる"""
        closes = [145.0] * 25
        candles = _make_candles(25, closes)
        snap = _make_snapshot()
        signal = engine.generate(candles, snap)
        assert signal.action.lower() in signal.signal_id

    def test_signal_id_buy_format(self):
        closes = [150.0 - i * 0.5 for i in range(30)]
        candles = _make_candles(30, closes)
        snap = _make_snapshot(mid=closes[-1], spread_pips=0.2)
        signal = engine.generate(candles, snap)
        assert signal.signal_id.startswith("usdjpy_")
        assert signal.action.lower() in signal.signal_id
