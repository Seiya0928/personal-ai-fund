from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.proposals.common_proposal import CommonOrderProposal
from src.reports.daily_personal_report import (
    render_daily_personal_report,
    save_daily_personal_report,
)

JST = ZoneInfo("Asia/Tokyo")


def _btc_proposal(**kwargs) -> CommonOrderProposal:
    defaults = dict(
        proposal_id="btc_001",
        asset_class="crypto",
        instrument="BTC_JPY",
        strategy_name="btc_dip_alert",
        side="buy",
        status="proposed",
        risk_jpy=1100.0,
        max_loss_jpy=1100.0,
        expected_rr=1.0,
        confidence=None,
        reason="買い候補ライン到達",
        created_at="2026-05-09T09:00:00+09:00",
        expires_at=None,
        metadata={
            "suggested_price": 11_000_000.0,
            "stop_loss": 9_900_000.0,
            "take_profit": 12_100_000.0,
            "rationale": ["source_status=BUY_CANDIDATE"],
            "invalidation_conditions": ["STOP_TRADING が有効"],
        },
    )
    defaults.update(kwargs)
    return CommonOrderProposal(**defaults)


def _fx_proposal(**kwargs) -> CommonOrderProposal:
    defaults = dict(
        proposal_id="fx_001",
        asset_class="fx",
        instrument="USD_JPY",
        strategy_name="fx_ema_h1",
        side="sell",
        status="proposed",
        risk_jpy=300.0,
        max_loss_jpy=300.0,
        expected_rr=2.0,
        confidence=None,
        reason="SELL signal",
        created_at="2026-05-09T22:00:00+09:00",
        expires_at=None,
        metadata={
            "source_signal_id": "usdjpy_sig_001",
            "suggested_price": 155.12,
            "stop_loss": 155.42,
            "take_profit": 154.52,
            "rationale": ["EMA trend DOWN"],
            "invalidation_conditions": ["STOP_TRADING が有効"],
        },
    )
    defaults.update(kwargs)
    return CommonOrderProposal(**defaults)


class TestRenderDailyPersonalReport:
    def _render(self, proposals, stop_trading=False, dry_run=True, read_only=True):
        return render_daily_personal_report(
            proposals,
            target_date=date(2026, 5, 9),
            generated_at=datetime(2026, 5, 9, 22, 0, tzinfo=JST),
            stop_trading_active=stop_trading,
            dry_run=dry_run,
            read_only=read_only,
        )

    def test_header_contains_date(self):
        report = self._render([])
        assert "Daily Personal Report 2026-05-09" in report

    def test_no_execution_claim(self):
        report = self._render([])
        assert "実注文APIは使用していません" in report

    def test_stop_trading_inactive_shown(self):
        report = self._render([], stop_trading=False)
        assert "inactive" in report

    def test_stop_trading_active_shown(self):
        report = self._render([], stop_trading=True)
        assert "ACTIVE" in report

    def test_dry_run_shown(self):
        report = self._render([], dry_run=True)
        assert "DRY_RUN" in report
        assert "true" in report

    def test_read_only_shown(self):
        report = self._render([], read_only=False)
        assert "READ_ONLY" in report
        assert "false" in report

    def test_btc_and_fx_in_same_report(self):
        proposals = [_btc_proposal(), _fx_proposal()]
        report = self._render(proposals)
        assert "crypto" in report
        assert "fx" in report
        assert "BTC_JPY" in report
        assert "USD_JPY" in report

    def test_total_risk_jpy_shown(self):
        proposals = [_btc_proposal(risk_jpy=1100.0), _fx_proposal(risk_jpy=300.0)]
        report = self._render(proposals)
        assert "1,400" in report

    def test_proposal_count_shown(self):
        proposals = [_btc_proposal(), _fx_proposal()]
        report = self._render(proposals)
        assert "2 件" in report

    def test_empty_proposals(self):
        report = self._render([])
        assert "none" in report

    def test_sections_by_status_present(self):
        report = self._render([])
        assert "未承認 (proposed)" in report
        assert "承認済み (approved)" in report
        assert "DRY_RUN記録済み" in report
        assert "棄却 (rejected)" in report
        assert "期限切れ (expired)" in report

    def test_proposed_proposal_in_proposed_section(self):
        proposals = [_btc_proposal(status="proposed")]
        report = self._render(proposals)
        assert "## 未承認 (proposed)" in report
        assert "btc_001" in report

    def test_approved_proposal_in_approved_section(self):
        proposals = [_fx_proposal(status="approved")]
        report = self._render(proposals)
        assert "## 承認済み (approved)" in report

    def test_expected_rr_shown(self):
        proposals = [_btc_proposal(expected_rr=1.5)]
        report = self._render(proposals)
        assert "1.50" in report

    def test_strategy_name_shown(self):
        proposals = [_btc_proposal()]
        report = self._render(proposals)
        assert "btc_dip_alert" in report

    def test_rationale_shown(self):
        proposals = [_btc_proposal()]
        report = self._render(proposals)
        assert "source_status=BUY_CANDIDATE" in report

    def test_no_execution_api_tokens_in_source(self):
        source = Path(__file__).resolve().parents[1] / "src" / "reports" / "daily_personal_report.py"
        text = source.read_text(encoding="utf-8")
        for forbidden in ["place_order", "live_order", "broker_adapter", "send_to_exchange", "/private/v1/order"]:
            assert forbidden not in text, f"Forbidden token found in source: {forbidden}"


class TestSaveDailyPersonalReport:
    def test_saves_with_expected_filename(self, tmp_path: Path):
        path = save_daily_personal_report(
            "content",
            target_date=date(2026, 5, 9),
            reports_dir=tmp_path,
        )
        assert path.name == "daily_personal_report_20260509.md"
        assert path.read_text(encoding="utf-8") == "content"

    def test_creates_reports_dir_if_missing(self, tmp_path: Path):
        reports_dir = tmp_path / "nested" / "reports"
        path = save_daily_personal_report(
            "content",
            target_date=date(2026, 5, 9),
            reports_dir=reports_dir,
        )
        assert path.exists()
