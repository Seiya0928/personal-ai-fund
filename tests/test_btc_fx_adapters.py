import pytest
from src.alerts.order_proposal import OrderProposal
from src.fx.order_proposal import FXOrderProposal
from src.proposals.btc_adapter import btc_proposal_to_common
from src.proposals.fx_adapter import fx_proposal_to_common


def _btc_proposal(**kwargs) -> OrderProposal:
    defaults = dict(
        proposal_id="btc_jpy_20260509_buy_buy_candidate_11000000",
        created_at="2026-05-09T09:00:00+09:00",
        symbol="BTC_JPY",
        side="BUY",
        execution_type="LIMIT",
        suggested_price=11_000_000.0,
        suggested_size=0.001,
        estimated_jpy=11_000.0,
        reason="買い候補ライン到達",
        source_status="BUY_CANDIDATE",
        requires_manual_confirmation=True,
        send_to_exchange=False,
        stop_loss=9_900_000.0,
        take_profit=12_100_000.0,
        max_loss_jpy=1_100.0,
        rationale=["source_status=BUY_CANDIDATE"],
        invalidation_conditions=["STOP_TRADING が有効"],
    )
    defaults.update(kwargs)
    return OrderProposal(**defaults)


def _fx_proposal(**kwargs) -> FXOrderProposal:
    defaults = dict(
        proposal_id="fx_usdjpy_20260509_buy_proposal",
        created_at="2026-05-09T22:00:00+09:00",
        source_signal_id="usdjpy_20260509_220000_buy",
        symbol="USD/JPY",
        side="BUY",
        execution_type="LIMIT",
        suggested_price=155.12,
        suggested_size=1000.0,
        estimated_jpy=155_120.0,
        reason="BUY signal from USD/JPY research module",
        source_status="BUY",
        stop_loss=154.82,
        take_profit=155.72,
        max_loss_jpy=300.0,
        rationale=["EMA trend UP"],
        invalidation_conditions=["STOP_TRADING が有効"],
    )
    defaults.update(kwargs)
    return FXOrderProposal(**defaults)


class TestBtcAdapter:
    def test_buy_maps_to_buy(self):
        p = btc_proposal_to_common(_btc_proposal())
        assert p.side == "buy"
        assert p.asset_class == "crypto"
        assert p.instrument == "BTC_JPY"

    def test_sell_default_maps_to_sell(self):
        p = btc_proposal_to_common(_btc_proposal(side="SELL", source_status="SELL"))
        assert p.side == "sell"

    def test_take_profit_candidate_maps_to_take_profit(self):
        p = btc_proposal_to_common(_btc_proposal(side="SELL", source_status="TAKE_PROFIT_CANDIDATE"))
        assert p.side == "take_profit"

    def test_stop_loss_candidate_maps_to_stop_loss(self):
        p = btc_proposal_to_common(_btc_proposal(side="SELL", source_status="STOP_LOSS_CANDIDATE"))
        assert p.side == "stop_loss"

    def test_timeout_exit_candidate_maps_to_timeout_exit(self):
        p = btc_proposal_to_common(_btc_proposal(side="SELL", source_status="TIMEOUT_EXIT_CANDIDATE"))
        assert p.side == "timeout_exit"

    def test_status_proposed_preserved(self):
        p = btc_proposal_to_common(_btc_proposal(status="proposed"))
        assert p.status == "proposed"

    def test_status_dry_run_recorded_preserved(self):
        p = btc_proposal_to_common(_btc_proposal(status="dry_run_recorded"))
        assert p.status == "dry_run_recorded"

    def test_status_ignored_maps_to_rejected(self):
        p = btc_proposal_to_common(_btc_proposal(status="ignored"))
        assert p.status == "rejected"

    def test_status_manually_executed_maps_to_approved(self):
        p = btc_proposal_to_common(_btc_proposal(status="manually_executed"))
        assert p.status == "approved"

    def test_expected_rr_computed_for_buy(self):
        # price=11_000_000, sl=9_900_000 (risk=1_100_000), tp=12_100_000 (reward=1_100_000) → rr=1.0
        p = btc_proposal_to_common(_btc_proposal(
            suggested_price=11_000_000.0,
            stop_loss=9_900_000.0,
            take_profit=12_100_000.0,
        ))
        assert p.expected_rr == pytest.approx(1.0, rel=0.01)

    def test_expected_rr_none_if_stop_loss_missing(self):
        p = btc_proposal_to_common(_btc_proposal(stop_loss=None))
        assert p.expected_rr is None

    def test_max_loss_jpy_preserved(self):
        p = btc_proposal_to_common(_btc_proposal(max_loss_jpy=5000.0))
        assert p.max_loss_jpy == 5000.0
        assert p.risk_jpy == 5000.0

    def test_metadata_contains_original_fields(self):
        p = btc_proposal_to_common(_btc_proposal())
        assert p.metadata["source_status"] == "BUY_CANDIDATE"
        assert p.metadata["suggested_price"] == 11_000_000.0
        assert "rationale" in p.metadata

    def test_strategy_name_is_btc_dip_alert(self):
        p = btc_proposal_to_common(_btc_proposal())
        assert p.strategy_name == "btc_dip_alert"

    def test_original_proposal_not_modified(self):
        original = _btc_proposal()
        original_side = original.side
        btc_proposal_to_common(original)
        assert original.side == original_side


class TestFxAdapter:
    def test_buy_maps_to_buy(self):
        p = fx_proposal_to_common(_fx_proposal())
        assert p.side == "buy"
        assert p.asset_class == "fx"
        assert p.instrument == "USD_JPY"

    def test_sell_maps_to_sell(self):
        p = fx_proposal_to_common(_fx_proposal(side="SELL", source_status="SELL"))
        assert p.side == "sell"

    def test_status_proposed_preserved(self):
        p = fx_proposal_to_common(_fx_proposal(status="proposed"))
        assert p.status == "proposed"

    def test_status_dry_run_recorded_preserved(self):
        p = fx_proposal_to_common(_fx_proposal(status="dry_run_recorded"))
        assert p.status == "dry_run_recorded"

    def test_expected_rr_computed_for_buy(self):
        # price=155.12, sl=154.82 (risk=0.30), tp=155.72 (reward=0.60) → rr=2.0
        p = fx_proposal_to_common(_fx_proposal(
            suggested_price=155.12,
            stop_loss=154.82,
            take_profit=155.72,
        ))
        assert p.expected_rr == pytest.approx(2.0, rel=0.05)

    def test_expected_rr_none_if_zero_risk(self):
        p = fx_proposal_to_common(_fx_proposal(
            suggested_price=155.0,
            stop_loss=155.0,
            take_profit=156.0,
        ))
        assert p.expected_rr is None

    def test_max_loss_jpy_preserved(self):
        p = fx_proposal_to_common(_fx_proposal(max_loss_jpy=300.0))
        assert p.max_loss_jpy == 300.0
        assert p.risk_jpy == 300.0

    def test_metadata_contains_original_fields(self):
        p = fx_proposal_to_common(_fx_proposal())
        assert p.metadata["source_signal_id"] == "usdjpy_20260509_220000_buy"
        assert p.metadata["suggested_price"] == 155.12
        assert "rationale" in p.metadata

    def test_strategy_name_is_fx_ema_h1(self):
        p = fx_proposal_to_common(_fx_proposal())
        assert p.strategy_name == "fx_ema_h1"

    def test_original_proposal_not_modified(self):
        original = _fx_proposal()
        original_side = original.side
        fx_proposal_to_common(original)
        assert original.side == original_side
