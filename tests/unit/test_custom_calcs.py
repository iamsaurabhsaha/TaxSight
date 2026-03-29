"""Tests for custom tax calculations."""

import pytest

from ai_tax_prep.core.tax_profile import (
    Income,
    Payments,
    PersonalInfo,
    SelfEmploymentIncome,
    TaxProfile,
    W2Income,
)
from ai_tax_prep.tax.custom_calcs import (
    calculate_effective_rates,
    calculate_schedule_c_detail,
    calculate_se_tax_detail,
    calculate_withholding_and_refund,
)


class TestWithholdingAndRefund:
    def test_refund(self):
        profile = TaxProfile(
            payments=Payments(federal_withholding=15000, state_withholding=5000),
        )
        pe_result = {"federal_income_tax": 10000, "self_employment_tax": 0, "state_income_tax": 4000}
        result = calculate_withholding_and_refund(profile, pe_result)
        assert result["federal_refund_or_owed"] == 5000  # 15000 - 10000
        assert result["state_refund_or_owed"] == 1000    # 5000 - 4000
        assert result["total_refund_or_owed"] == 6000

    def test_owed(self):
        profile = TaxProfile(
            payments=Payments(federal_withholding=5000, state_withholding=2000),
        )
        pe_result = {"federal_income_tax": 10000, "self_employment_tax": 0, "state_income_tax": 4000}
        result = calculate_withholding_and_refund(profile, pe_result)
        assert result["federal_refund_or_owed"] == -5000
        assert result["state_refund_or_owed"] == -2000

    def test_with_estimated_payments(self):
        profile = TaxProfile(
            payments=Payments(
                federal_withholding=5000,
                estimated_federal_payments=3000,
            ),
        )
        pe_result = {"federal_income_tax": 10000, "self_employment_tax": 0, "state_income_tax": 0}
        result = calculate_withholding_and_refund(profile, pe_result)
        assert result["federal_refund_or_owed"] == -2000  # (5000+3000) - 10000

    def test_with_se_tax(self):
        profile = TaxProfile(
            payments=Payments(federal_withholding=20000),
        )
        pe_result = {"federal_income_tax": 10000, "self_employment_tax": 5000, "state_income_tax": 0}
        result = calculate_withholding_and_refund(profile, pe_result)
        assert result["total_federal_tax"] == 15000  # 10000 + 5000
        assert result["federal_refund_or_owed"] == 5000  # 20000 - 15000


class TestSETaxDetail:
    def test_zero_se_income(self):
        profile = TaxProfile()
        result = calculate_se_tax_detail(profile)
        assert result["total_se_tax"] == 0

    def test_basic_se_tax(self):
        profile = TaxProfile(
            personal_info=PersonalInfo(filing_status="single"),
            income=Income(
                self_employment=[SelfEmploymentIncome(gross_income=50000, expenses=10000)],
            ),
        )
        result = calculate_se_tax_detail(profile)
        assert result["net_se_income"] == 40000
        assert result["se_tax_base"] == pytest.approx(40000 * 0.9235, rel=0.01)
        assert result["total_se_tax"] > 0
        assert result["se_tax_deduction"] == pytest.approx(result["total_se_tax"] / 2)

    def test_se_tax_deduction_is_half(self):
        profile = TaxProfile(
            personal_info=PersonalInfo(filing_status="single"),
            income=Income(
                self_employment=[SelfEmploymentIncome(gross_income=100000, expenses=0)],
            ),
        )
        result = calculate_se_tax_detail(profile)
        assert result["se_tax_deduction"] == pytest.approx(result["total_se_tax"] / 2)


class TestScheduleCDetail:
    def test_single_business(self):
        profile = TaxProfile(
            income=Income(
                self_employment=[
                    SelfEmploymentIncome(business_name="Consulting", gross_income=100000, expenses=30000),
                ],
            ),
        )
        details = calculate_schedule_c_detail(profile)
        assert len(details) == 1
        assert details[0]["net_profit"] == 70000

    def test_multiple_businesses(self):
        profile = TaxProfile(
            income=Income(
                self_employment=[
                    SelfEmploymentIncome(business_name="Biz A", gross_income=50000, expenses=10000),
                    SelfEmploymentIncome(business_name="Biz B", gross_income=30000, expenses=5000),
                ],
            ),
        )
        details = calculate_schedule_c_detail(profile)
        assert len(details) == 2

    def test_empty(self):
        profile = TaxProfile()
        details = calculate_schedule_c_detail(profile)
        assert len(details) == 0


class TestEffectiveRates:
    def test_basic_rates(self):
        profile = TaxProfile(
            income=Income(w2s=[W2Income(wages=100000)]),
        )
        pe_result = {"agi": 100000}
        custom_result = {"total_federal_tax": 15000, "total_state_tax": 5000}
        result = calculate_effective_rates(profile, pe_result, custom_result)
        assert result["effective_federal_rate"] == 15.0
        assert result["effective_state_rate"] == 5.0
        assert result["effective_total_rate"] == 20.0

    def test_zero_income(self, sample_profile_zero_income):
        pe_result = {"agi": 0}
        custom_result = {"total_federal_tax": 0, "total_state_tax": 0}
        result = calculate_effective_rates(sample_profile_zero_income, pe_result, custom_result)
        assert result["effective_total_rate"] == 0
