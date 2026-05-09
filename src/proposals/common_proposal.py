# 実注文なし・研究用。このモジュールは取引所APIを一切呼びません。
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

COMMON_SIDE_VALUES = frozenset({"buy", "sell", "skip", "take_profit", "stop_loss", "timeout_exit"})
COMMON_STATUS_VALUES = frozenset({"proposed", "approved", "rejected", "expired", "dry_run_recorded"})
ASSET_CLASS_VALUES = frozenset({"crypto", "fx"})
INSTRUMENT_VALUES = frozenset({"BTC_JPY", "USD_JPY"})


@dataclass
class CommonOrderProposal:
    proposal_id: str
    asset_class: str        # "crypto" | "fx"
    instrument: str         # "BTC_JPY" | "USD_JPY"
    strategy_name: str
    side: str               # COMMON_SIDE_VALUES
    status: str             # COMMON_STATUS_VALUES
    risk_jpy: float
    max_loss_jpy: float
    expected_rr: Optional[float]
    confidence: Optional[float]   # 0.0 – 1.0, None if not computed
    reason: str
    created_at: str
    expires_at: Optional[str]
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.asset_class not in ASSET_CLASS_VALUES:
            raise ValueError(f"asset_class must be one of {sorted(ASSET_CLASS_VALUES)}, got {self.asset_class!r}")
        if self.instrument not in INSTRUMENT_VALUES:
            raise ValueError(f"instrument must be one of {sorted(INSTRUMENT_VALUES)}, got {self.instrument!r}")
        if self.side not in COMMON_SIDE_VALUES:
            raise ValueError(f"side must be one of {sorted(COMMON_SIDE_VALUES)}, got {self.side!r}")
        if self.status not in COMMON_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(COMMON_STATUS_VALUES)}, got {self.status!r}")


def common_proposal_to_dict(proposal: CommonOrderProposal) -> dict:
    return asdict(proposal)


def common_proposal_from_dict(d: dict) -> CommonOrderProposal:
    return CommonOrderProposal(**d)
