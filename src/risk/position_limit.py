from src.utils.logger import get_logger

log = get_logger(__name__)


class PositionLimitChecker:
    """現在の保有BTC評価額が上限を超えていないか確認する。"""

    def __init__(self, max_position_value_jpy: float):
        self.max_position_value_jpy = max_position_value_jpy

    def check(self, btc_held: float, current_price_jpy: float) -> tuple[bool, str]:
        """
        Returns (ok, reason).
        ok=True なら注文可能。
        """
        position_value = btc_held * current_price_jpy
        if position_value >= self.max_position_value_jpy:
            reason = (
                f"ポジション上限超過: 現在評価額 ¥{position_value:,.0f} "
                f">= 上限 ¥{self.max_position_value_jpy:,.0f}"
            )
            log.warning(reason)
            return False, reason
        return True, "OK"
