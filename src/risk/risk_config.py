import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RiskConfig:
    # --- 動作モード ---
    dry_run: bool = True                     # True のまま = 実発注なし

    # --- 注文制限 ---
    allowed_symbols: list = field(default_factory=lambda: ["BTC_JPY"])
    allowed_order_types: list = field(default_factory=lambda: ["LIMIT"])
    max_order_amount_jpy: float = 1_000.0    # 1回あたり最大注文額
    max_daily_orders: int = 1                # 1日あたり最大注文回数

    # --- 損失制限 ---
    max_daily_loss_jpy: float = 300.0        # 1日最大損失額

    # --- ポジション制限 ---
    max_position_value_jpy: float = 3_000.0  # 最大保有BTC評価額

    # --- 緊急停止ファイル ---
    stop_trading_file: Path = ROOT / "STOP_TRADING"

    # --- 重複注文ガード ---
    duplicate_guard_seconds: int = 60        # 同一内容の注文を何秒間ブロックするか

    # --- 注文監視 ---
    order_timeout_seconds: int = 60          # 未約定注文を自動キャンセルするまでの秒数
    polling_interval_seconds: int = 2        # order_watcher のポーリング間隔（秒）


def load_config() -> RiskConfig:
    cfg = RiskConfig()
    # 環境変数でオーバーライド可能
    dry_run_env = os.getenv("DRY_RUN", "true").lower()
    cfg.dry_run = dry_run_env not in ("false", "0", "no")
    return cfg
