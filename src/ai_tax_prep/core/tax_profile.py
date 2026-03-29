"""Pydantic models representing a complete taxpayer profile."""

from typing import Optional

from pydantic import BaseModel, Field


class W2Income(BaseModel):
    employer_name: str = ""
    employer_ein: str = ""
    wages: float = 0.0
    federal_withholding: float = 0.0
    ss_wages: float = 0.0
    ss_tax: float = 0.0
    medicare_wages: float = 0.0
    medicare_tax: float = 0.0
    state: str = ""
    state_wages: float = 0.0
    state_withholding: float = 0.0


class SelfEmploymentIncome(BaseModel):
    business_name: str = ""
    gross_income: float = 0.0
    expenses: float = 0.0

    @property
    def net_income(self) -> float:
        return self.gross_income - self.expenses


class InterestIncome(BaseModel):
    payer_name: str = ""
    amount: float = 0.0
    is_tax_exempt: bool = False


class DividendIncome(BaseModel):
    payer_name: str = ""
    ordinary_dividends: float = 0.0
    qualified_dividends: float = 0.0


class CapitalGain(BaseModel):
    description: str = ""
    date_acquired: str = ""
    date_sold: str = ""
    proceeds: float = 0.0
    cost_basis: float = 0.0
    is_long_term: bool = False

    @property
    def gain_loss(self) -> float:
        return self.proceeds - self.cost_basis


class RetirementIncome(BaseModel):
    source: str = ""
    gross_distribution: float = 0.0
    taxable_amount: float = 0.0


class RentalIncome(BaseModel):
    property_description: str = ""
    gross_rent: float = 0.0
    expenses: float = 0.0

    @property
    def net_income(self) -> float:
        return self.gross_rent - self.expenses


class Income(BaseModel):
    w2s: list[W2Income] = Field(default_factory=list)
    self_employment: list[SelfEmploymentIncome] = Field(default_factory=list)
    interest: list[InterestIncome] = Field(default_factory=list)
    dividends: list[DividendIncome] = Field(default_factory=list)
    capital_gains: list[CapitalGain] = Field(default_factory=list)
    retirement: list[RetirementIncome] = Field(default_factory=list)
    rental: list[RentalIncome] = Field(default_factory=list)
    other_income: float = 0.0
    other_income_description: str = ""

    def total_wages(self) -> float:
        return sum(w.wages for w in self.w2s)

    def total_self_employment(self) -> float:
        return sum(s.net_income for s in self.self_employment)

    def total_interest(self) -> float:
        return sum(i.amount for i in self.interest if not i.is_tax_exempt)

    def total_dividends(self) -> float:
        return sum(d.ordinary_dividends for d in self.dividends)

    def total_qualified_dividends(self) -> float:
        return sum(d.qualified_dividends for d in self.dividends)

    def total_capital_gains(self) -> float:
        return sum(c.gain_loss for c in self.capital_gains)

    def total_rental(self) -> float:
        return sum(r.net_income for r in self.rental)

    def total_retirement(self) -> float:
        return sum(r.taxable_amount for r in self.retirement)

    def total_federal_withholding(self) -> float:
        return sum(w.federal_withholding for w in self.w2s)

    def total_state_withholding(self) -> float:
        return sum(w.state_withholding for w in self.w2s)


class ItemizedDeductions(BaseModel):
    medical_expenses: float = 0.0
    state_local_taxes: float = 0.0
    mortgage_interest: float = 0.0
    charitable_cash: float = 0.0
    charitable_noncash: float = 0.0
    other_deductions: float = 0.0

    def total(self) -> float:
        return (
            self.medical_expenses
            + self.state_local_taxes
            + self.mortgage_interest
            + self.charitable_cash
            + self.charitable_noncash
            + self.other_deductions
        )


class Adjustments(BaseModel):
    hsa_contributions: float = 0.0
    ira_contributions: float = 0.0
    student_loan_interest: float = 0.0
    educator_expenses: float = 0.0
    self_employment_tax_deduction: float = 0.0
    self_employment_health_insurance: float = 0.0
    alimony_paid: float = 0.0

    def total(self) -> float:
        return (
            self.hsa_contributions
            + self.ira_contributions
            + self.student_loan_interest
            + self.educator_expenses
            + self.self_employment_tax_deduction
            + self.self_employment_health_insurance
            + self.alimony_paid
        )


class Dependent(BaseModel):
    name: str = ""
    relationship: str = ""
    age: int = 0
    ssn_last_four: str = ""
    months_lived_with_you: int = 12


class PersonalInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""
    age: int = 0
    filing_status: str = ""
    state_of_residence: str = ""
    dependents: list[Dependent] = Field(default_factory=list)


class Payments(BaseModel):
    federal_withholding: float = 0.0
    state_withholding: float = 0.0
    estimated_federal_payments: float = 0.0
    estimated_state_payments: float = 0.0


class TaxProfile(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    income: Income = Field(default_factory=Income)
    adjustments: Adjustments = Field(default_factory=Adjustments)
    itemized_deductions: ItemizedDeductions = Field(default_factory=ItemizedDeductions)
    use_itemized: Optional[bool] = None  # None = auto-optimize
    payments: Payments = Field(default_factory=Payments)
    tax_year: int = 2025

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> "TaxProfile":
        return cls.model_validate_json(data)

    def summary(self) -> dict:
        return {
            "filing_status": self.personal_info.filing_status,
            "state": self.personal_info.state_of_residence,
            "total_wages": self.income.total_wages(),
            "total_self_employment": self.income.total_self_employment(),
            "total_interest": self.income.total_interest(),
            "total_dividends": self.income.total_dividends(),
            "total_capital_gains": self.income.total_capital_gains(),
            "total_rental": self.income.total_rental(),
            "total_retirement": self.income.total_retirement(),
            "dependents": len(self.personal_info.dependents),
            "adjustments": self.adjustments.total(),
            "itemized_deductions": self.itemized_deductions.total(),
        }
