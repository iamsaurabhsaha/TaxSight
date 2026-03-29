"""Pydantic models for tax document data extraction."""


from pydantic import BaseModel, Field


class W2Data(BaseModel):
    employer_name: str = ""
    employer_ein: str = ""
    employee_name: str = ""
    wages: float = Field(0.0, description="Box 1: Wages, tips, other compensation")
    federal_withholding: float = Field(0.0, description="Box 2: Federal income tax withheld")
    ss_wages: float = Field(0.0, description="Box 3: Social security wages")
    ss_tax: float = Field(0.0, description="Box 4: Social security tax withheld")
    medicare_wages: float = Field(0.0, description="Box 5: Medicare wages and tips")
    medicare_tax: float = Field(0.0, description="Box 6: Medicare tax withheld")
    state: str = Field("", description="Box 15: State")
    state_wages: float = Field(0.0, description="Box 16: State wages")
    state_tax: float = Field(0.0, description="Box 17: State income tax")


class Form1099NEC(BaseModel):
    payer_name: str = ""
    payer_tin: str = ""
    recipient_name: str = ""
    nonemployee_compensation: float = Field(0.0, description="Box 1: Nonemployee compensation")
    federal_withholding: float = Field(0.0, description="Box 4: Federal income tax withheld")


class Form1099INT(BaseModel):
    payer_name: str = ""
    interest_income: float = Field(0.0, description="Box 1: Interest income")
    early_withdrawal_penalty: float = Field(0.0, description="Box 2: Early withdrawal penalty")
    us_savings_bond_interest: float = Field(0.0, description="Box 3: Interest on U.S. Savings Bonds")
    federal_withholding: float = Field(0.0, description="Box 4: Federal income tax withheld")
    tax_exempt_interest: float = Field(0.0, description="Box 8: Tax-exempt interest")


class Form1099DIV(BaseModel):
    payer_name: str = ""
    ordinary_dividends: float = Field(0.0, description="Box 1a: Total ordinary dividends")
    qualified_dividends: float = Field(0.0, description="Box 1b: Qualified dividends")
    capital_gain_distributions: float = Field(0.0, description="Box 2a: Total capital gain distributions")
    federal_withholding: float = Field(0.0, description="Box 4: Federal income tax withheld")


class Form1099B(BaseModel):
    description: str = Field("", description="Description of property")
    date_acquired: str = ""
    date_sold: str = ""
    proceeds: float = Field(0.0, description="Box 1d: Proceeds")
    cost_basis: float = Field(0.0, description="Box 1e: Cost or other basis")
    gain_loss: float = Field(0.0, description="Calculated gain or loss")
    is_long_term: bool = Field(False, description="Held for more than one year")
    federal_withholding: float = Field(0.0, description="Box 4: Federal income tax withheld")


class Form1099R(BaseModel):
    payer_name: str = ""
    gross_distribution: float = Field(0.0, description="Box 1: Gross distribution")
    taxable_amount: float = Field(0.0, description="Box 2a: Taxable amount")
    federal_withholding: float = Field(0.0, description="Box 4: Federal income tax withheld")
    distribution_code: str = Field("", description="Box 7: Distribution code")


DOC_TYPE_SCHEMAS = {
    "w2": W2Data,
    "1099_nec": Form1099NEC,
    "1099_int": Form1099INT,
    "1099_div": Form1099DIV,
    "1099_b": Form1099B,
    "1099_r": Form1099R,
}


DOC_TYPE_NAMES = {
    "w2": "W-2 (Wage and Tax Statement)",
    "1099_nec": "1099-NEC (Nonemployee Compensation)",
    "1099_int": "1099-INT (Interest Income)",
    "1099_div": "1099-DIV (Dividends and Distributions)",
    "1099_b": "1099-B (Proceeds from Broker Transactions)",
    "1099_r": "1099-R (Retirement Distributions)",
}
