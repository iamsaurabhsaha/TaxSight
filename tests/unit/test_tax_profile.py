"""Tests for tax profile model."""



from ai_tax_prep.core.tax_profile import (
    Adjustments,
    CapitalGain,
    Income,
    InterestIncome,
    ItemizedDeductions,
    SelfEmploymentIncome,
    TaxProfile,
    W2Income,
)


class TestW2Income:
    def test_default_values(self):
        w2 = W2Income()
        assert w2.wages == 0.0
        assert w2.federal_withholding == 0.0
        assert w2.employer_name == ""

    def test_with_values(self):
        w2 = W2Income(employer_name="Test Co", wages=50000, federal_withholding=8000)
        assert w2.wages == 50000
        assert w2.federal_withholding == 8000


class TestSelfEmploymentIncome:
    def test_net_income(self):
        se = SelfEmploymentIncome(gross_income=100000, expenses=30000)
        assert se.net_income == 70000

    def test_zero_expenses(self):
        se = SelfEmploymentIncome(gross_income=50000, expenses=0)
        assert se.net_income == 50000


class TestCapitalGain:
    def test_gain(self):
        cg = CapitalGain(proceeds=10000, cost_basis=5000)
        assert cg.gain_loss == 5000

    def test_loss(self):
        cg = CapitalGain(proceeds=3000, cost_basis=10000)
        assert cg.gain_loss == -7000


class TestIncome:
    def test_total_wages(self):
        income = Income(w2s=[
            W2Income(wages=50000),
            W2Income(wages=30000),
        ])
        assert income.total_wages() == 80000

    def test_total_self_employment(self):
        income = Income(self_employment=[
            SelfEmploymentIncome(gross_income=100000, expenses=20000),
        ])
        assert income.total_self_employment() == 80000

    def test_total_interest_excludes_tax_exempt(self):
        income = Income(interest=[
            InterestIncome(amount=1000, is_tax_exempt=False),
            InterestIncome(amount=500, is_tax_exempt=True),
        ])
        assert income.total_interest() == 1000

    def test_total_capital_gains_mixed(self):
        income = Income(capital_gains=[
            CapitalGain(proceeds=10000, cost_basis=5000),
            CapitalGain(proceeds=3000, cost_basis=8000),
        ])
        assert income.total_capital_gains() == 0  # 5000 + (-5000)

    def test_total_federal_withholding(self):
        income = Income(w2s=[
            W2Income(federal_withholding=5000),
            W2Income(federal_withholding=3000),
        ])
        assert income.total_federal_withholding() == 8000

    def test_empty_income(self):
        income = Income()
        assert income.total_wages() == 0
        assert income.total_self_employment() == 0
        assert income.total_interest() == 0
        assert income.total_capital_gains() == 0


class TestItemizedDeductions:
    def test_total(self):
        item = ItemizedDeductions(
            mortgage_interest=12000,
            state_local_taxes=10000,
            charitable_cash=5000,
        )
        assert item.total() == 27000

    def test_empty(self):
        assert ItemizedDeductions().total() == 0


class TestAdjustments:
    def test_total(self):
        adj = Adjustments(
            hsa_contributions=3600,
            ira_contributions=6000,
            student_loan_interest=2500,
        )
        assert adj.total() == 12100


class TestTaxProfile:
    def test_serialization_roundtrip(self, sample_profile_single):
        json_str = sample_profile_single.to_json()
        restored = TaxProfile.from_json(json_str)
        assert restored.personal_info.first_name == "Jane"
        assert restored.income.total_wages() == 75000
        assert restored.payments.federal_withholding == 10000

    def test_summary(self, sample_profile_single):
        summary = sample_profile_single.summary()
        assert summary["filing_status"] == "single"
        assert summary["total_wages"] == 75000
        assert summary["state"] == "CA"

    def test_empty_profile(self):
        profile = TaxProfile()
        summary = profile.summary()
        assert summary["total_wages"] == 0
        assert summary["filing_status"] == ""

    def test_profile_with_dependents(self, sample_profile_married_with_dependents):
        profile = sample_profile_married_with_dependents
        assert len(profile.personal_info.dependents) == 2
        assert profile.summary()["dependents"] == 2
