# CommonOrderProposalの保存・読み込み。実注文APIは呼ばない。
from __future__ import annotations

import json
from pathlib import Path

from src.proposals.common_proposal import (
    CommonOrderProposal,
    common_proposal_from_dict,
    common_proposal_to_dict,
)

DEFAULT_COMMON_PROPOSALS_PATH = Path(__file__).resolve().parents[2] / "state" / "common_proposals.json"


def load_common_proposals(path: Path = DEFAULT_COMMON_PROPOSALS_PATH) -> dict:
    if not path.exists():
        return {"proposals": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("proposals"), list):
        raise ValueError("common_proposals.json の形式が不正です。")
    return payload


def save_common_proposals(payload: dict, path: Path = DEFAULT_COMMON_PROPOSALS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_common_proposals(path: Path = DEFAULT_COMMON_PROPOSALS_PATH) -> list[dict]:
    return load_common_proposals(path)["proposals"]


def save_common_proposal(
    proposal: CommonOrderProposal,
    path: Path = DEFAULT_COMMON_PROPOSALS_PATH,
) -> tuple[dict, bool]:
    """重複（同じproposal_id）はスキップして (existing, False) を返す。"""
    payload = load_common_proposals(path)
    stored = common_proposal_to_dict(proposal)
    for existing in payload["proposals"]:
        if existing.get("proposal_id") == proposal.proposal_id:
            return existing, False
    payload["proposals"].append(stored)
    save_common_proposals(payload, path)
    return stored, True
