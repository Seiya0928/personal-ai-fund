import pytest
from src.strategies.moving_average import MovingAverageCross


def _make_rows(prices: list[float]) -> list[dict]:
    return [
        {"open": p, "high": p, "low": p, "close": p, "volume": 1.0, "timestamp": str(i * 3_600_000)}
        for i, p in enumerate(prices)
    ]


def test_signal_buy():
    # 後半が上昇トレンド → 最後はBUY(1)
    prices = [100] * 10 + [110, 120, 130, 140, 150, 160, 170, 180, 190, 200] + [210] * 10
    strategy = MovingAverageCross(short=5, long=20)
    df = strategy.generate_signals(_make_rows(prices))
    assert df.iloc[-1]["signal"] == 1


def test_signal_sell():
    # 後半が下降トレンド → 最後はSELL(-1)
    prices = [200] * 10 + [190, 180, 170, 160, 150, 140, 130, 120, 110, 100] + [90] * 10
    strategy = MovingAverageCross(short=5, long=20)
    df = strategy.generate_signals(_make_rows(prices))
    assert df.iloc[-1]["signal"] == -1


def test_insufficient_data():
    prices = [100] * 5
    strategy = MovingAverageCross(short=5, long=20)
    with pytest.raises(ValueError):
        strategy.generate_signals(_make_rows(prices))
