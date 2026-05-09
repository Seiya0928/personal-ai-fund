import json
import pytest
from pathlib import Path

from src.proposals.common_proposal import (
    CommonOrderProposal,
    COMMON_SIDE_VALUES,
    COMMON_STATUS_VALUES,
    common_proposal_to_dict,
    common_proposal_from_dict,
)
from src.proposals.storage import (
    save_common_proposal,
    list_common_proposals,
    load_common_proposals,
)


def _make_proposal(**kwargs) -> CommonOrderProposal:
    defaults = dict(
        proposal_id="test_001",
        asset_class="crypto",
        instrument="BTC_JPY",
        strategy_name="btc_dip_alert",
        side="buy",
        status="proposed",
        risk_jpy=1000.0,
        max_loss_jpy=1000.0,
        expected_rr=2.0,
        confidence=None,
        reason="test reason",
        created_at="2026-05-09T09:00:00+09:00",
        expires_at=None,
        metadata={},
    )
    defaults.update(kwargs)
    return CommonOrderProposal(**defaults)


class TestCommonOrderProposalValidation:
    def test_valid_proposal_created(self):
        p = _make_proposal()
        assert p.asset_class == "crypto"
        assert p.instrument == "BTC_JPY"
        assert p.side == "buy"
        assert p.status == "proposed"

    def test_all_valid_sides(self):
        for side in COMMON_SIDE_VALUES:
            p = _make_proposal(side=side)
            assert p.side == side

    def test_all_valid_statuses(self):
        for status in COMMON_STATUS_VALUES:
            p = _make_proposal(status=status)
            assert p.status == status

    def test_invalid_asset_class_raises(self):
        with pytest.raises(ValueError, match="asset_class"):
            _make_proposal(asset_class="stocks")

    def test_invalid_instrument_raises(self):
        with pytest.raises(ValueError, match="instrument"):
            _make_proposal(instrument="ETH_JPY")

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            _make_proposal(side="LONG")

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            _make_proposal(status="pending")

    def test_fx_proposal_valid(self):
        p = _make_proposal(asset_class="fx", instrument="USD_JPY", side="sell", status="dry_run_recorded")
        assert p.asset_class == "fx"
        assert p.instrument == "USD_JPY"

    def test_metadata_defaults_to_empty_dict(self):
        p = _make_proposal()
        assert p.metadata == {}

    def test_optional_fields_can_be_none(self):
        p = _make_proposal(expected_rr=None, confidence=None, expires_at=None)
        assert p.expected_rr is None
        assert p.confidence is None
        assert p.expires_at is None


class TestCommonProposalSerialization:
    def test_to_dict_round_trip(self):
        p = _make_proposal(metadata={"foo": "bar"})
        d = common_proposal_to_dict(p)
        assert d["proposal_id"] == "test_001"
        assert d["metadata"] == {"foo": "bar"}
        restored = common_proposal_from_dict(d)
        assert restored == p

    def test_from_dict_validates_on_reconstruction(self):
        d = common_proposal_to_dict(_make_proposal())
        d["side"] = "INVALID"
        with pytest.raises(ValueError, match="side"):
            common_proposal_from_dict(d)


class TestCommonProposalStorage:
    def test_save_and_list(self, tmp_path: Path):
        p = _make_proposal()
        path = tmp_path / "common_proposals.json"
        stored, is_new = save_common_proposal(p, path=path)
        assert is_new is True
        assert stored["proposal_id"] == "test_001"
        proposals = list_common_proposals(path=path)
        assert len(proposals) == 1
        assert proposals[0]["asset_class"] == "crypto"

    def test_duplicate_skipped(self, tmp_path: Path):
        p = _make_proposal()
        path = tmp_path / "common_proposals.json"
        _, is_new1 = save_common_proposal(p, path=path)
        _, is_new2 = save_common_proposal(p, path=path)
        assert is_new1 is True
        assert is_new2 is False
        assert len(list_common_proposals(path=path)) == 1

    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        assert list_common_proposals(path=path) == []

    def test_invalid_json_raises(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text('{"proposals": "not_a_list"}', encoding="utf-8")
        with pytest.raises(ValueError):
            list_common_proposals(path=path)

    def test_multiple_proposals_stored(self, tmp_path: Path):
        path = tmp_path / "common_proposals.json"
        p1 = _make_proposal(proposal_id="btc_001", asset_class="crypto", instrument="BTC_JPY")
        p2 = _make_proposal(proposal_id="fx_001", asset_class="fx", instrument="USD_JPY")
        save_common_proposal(p1, path=path)
        save_common_proposal(p2, path=path)
        proposals = list_common_proposals(path=path)
        assert len(proposals) == 2
        asset_classes = {p["asset_class"] for p in proposals}
        assert asset_classes == {"crypto", "fx"}
