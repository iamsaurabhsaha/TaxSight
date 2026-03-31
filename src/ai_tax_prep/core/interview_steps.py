"""Interview step definitions and DAG registry for the tax interview flow."""

from collections.abc import Callable
from dataclasses import dataclass, field

from ai_tax_prep.core.tax_profile import TaxProfile


@dataclass
class InterviewStep:
    id: str
    category: str  # basics, income, adjustments, deductions, credits, payments, review
    title: str
    description: str
    required_fields: list[str] = field(default_factory=list)
    next_step: str | Callable[[TaxProfile], str] = ""
    skippable: bool = False
    repeatable: bool = False  # For steps like W-2 where user may have multiple


# --- Routing functions ---

def route_after_dependents(profile: TaxProfile) -> str:
    return "document_upload"


def route_income_sources(profile: TaxProfile) -> str:
    """After the user tells us what income types they have, route to the first one."""
    data = profile.income
    if data.w2s or _has_pending(profile, "w2"):
        return "w2_income"
    if data.self_employment or _has_pending(profile, "self_employment"):
        return "self_employment_income"
    if data.interest or _has_pending(profile, "interest"):
        return "interest_income"
    if data.dividends or _has_pending(profile, "dividends"):
        return "dividend_income"
    if data.capital_gains or _has_pending(profile, "capital_gains"):
        return "capital_gains_income"
    if data.retirement or _has_pending(profile, "retirement"):
        return "retirement_income"
    if data.rental or _has_pending(profile, "rental"):
        return "rental_income"
    return "other_income"


def route_after_w2(profile: TaxProfile) -> str:
    return "w2_more"


def route_w2_more(profile: TaxProfile) -> str:
    """Ask if they have another W-2, or move on."""
    return "self_employment_check"


def route_after_income_type(profile: TaxProfile, next_check: str) -> str:
    return next_check


def route_self_employment_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "self_employment"):
        return "self_employment_income"
    return "interest_check"


def route_interest_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "interest"):
        return "interest_income"
    return "dividend_check"


def route_dividend_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "dividends"):
        return "dividend_income"
    return "capital_gains_check"


def route_capital_gains_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "capital_gains"):
        return "capital_gains_income"
    return "retirement_check"


def route_retirement_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "retirement"):
        return "retirement_income"
    return "rental_check"


def route_rental_check(profile: TaxProfile) -> str:
    if _has_pending(profile, "rental"):
        return "rental_income"
    return "other_income"


def route_after_other_income(profile: TaxProfile) -> str:
    return "adjustments"


def route_after_adjustments(profile: TaxProfile) -> str:
    return "deductions_choice"


def route_deductions_choice(profile: TaxProfile) -> str:
    if profile.use_itemized is True:
        return "itemized_deductions"
    elif profile.use_itemized is False:
        return "credits"
    # Auto-optimize: will be decided later
    return "itemized_deductions"


def route_after_itemized(profile: TaxProfile) -> str:
    return "credits"


def route_after_credits(profile: TaxProfile) -> str:
    return "payments_withholding"


def route_after_payments(profile: TaxProfile) -> str:
    return "review_summary"


def _has_pending(profile: TaxProfile, income_type: str) -> bool:
    """Check if the user indicated they have this income type during income_sources step."""
    # This is tracked via a metadata field set during the income_sources step
    # Stored in profile as a transient routing hint
    return False  # Default; the interview engine sets this dynamically


# --- Step Registry ---

STEPS: dict[str, InterviewStep] = {}


def _register(step: InterviewStep) -> InterviewStep:
    STEPS[step.id] = step
    return step


# ===== BASICS =====

_register(InterviewStep(
    id="welcome",
    category="basics",
    title="Welcome & Filing Status",
    description="Welcome the user and ask filing status in one step.",
    required_fields=["filing_status"],
    next_step="personal_info",
))

_register(InterviewStep(
    id="filing_status",
    category="basics",
    title="Filing Status",
    description="Confirm filing status if not already captured.",
    required_fields=["filing_status"],
    next_step="personal_info",
))

_register(InterviewStep(
    id="personal_info",
    category="basics",
    title="Personal Information",
    description="Collect only what's needed: state of residence and whether 65+.",
    required_fields=["state_of_residence", "is_65_or_older"],
    next_step="dependents",
))

_register(InterviewStep(
    id="dependents",
    category="basics",
    title="Dependents",
    description="Ask about dependents (children, qualifying relatives).",
    required_fields=[],
    skippable=True,
    next_step=route_after_dependents,
))

# ===== DOCUMENT UPLOAD =====

_register(InterviewStep(
    id="document_upload",
    category="income",
    title="Document Upload",
    description="Ask the user to upload tax documents (W-2s, 1099s, etc.) for automatic parsing.",
    required_fields=[],
    skippable=True,
    next_step="document_review",
))

_register(InterviewStep(
    id="document_review",
    category="income",
    title="Document Review",
    description="Show what was extracted from uploaded documents and ask the user to confirm.",
    required_fields=[],
    next_step="income_gaps",
))

_register(InterviewStep(
    id="income_gaps",
    category="income",
    title="Additional Income",
    description="Ask about any income NOT covered by uploaded documents.",
    required_fields=[],
    skippable=True,
    next_step=route_after_other_income,
))

# ===== INCOME (manual fallback) =====

_register(InterviewStep(
    id="income_sources",
    category="income",
    title="Income Sources Overview",
    description="Ask which types of income the user received this year (W-2, 1099, investments, etc).",
    required_fields=["income_types"],
    next_step="w2_income",  # Will be dynamically routed by the engine
))

_register(InterviewStep(
    id="w2_income",
    category="income",
    title="W-2 Wage Income",
    description="Collect W-2 details: employer, wages, withholding, state info.",
    required_fields=["employer_name", "wages", "federal_withholding"],
    repeatable=True,
    next_step="w2_more",
))

_register(InterviewStep(
    id="w2_more",
    category="income",
    title="Additional W-2?",
    description="Ask if the user has another W-2 to enter.",
    required_fields=["has_more_w2"],
    next_step=route_self_employment_check,
))

_register(InterviewStep(
    id="self_employment_check",
    category="income",
    title="Self-Employment Check",
    description="Route based on whether user has self-employment income.",
    next_step=route_self_employment_check,
))

_register(InterviewStep(
    id="self_employment_income",
    category="income",
    title="Self-Employment Income",
    description="Collect 1099-NEC/self-employment details: business name, gross income, expenses.",
    required_fields=["business_name", "gross_income", "expenses"],
    repeatable=True,
    skippable=True,
    next_step=route_interest_check,
))

_register(InterviewStep(
    id="interest_check",
    category="income",
    title="Interest Income Check",
    description="Route based on whether user has interest income.",
    next_step=route_interest_check,
))

_register(InterviewStep(
    id="interest_income",
    category="income",
    title="Interest Income",
    description="Collect 1099-INT details: payer, interest amount, tax-exempt status.",
    required_fields=["payer_name", "amount"],
    repeatable=True,
    skippable=True,
    next_step=route_dividend_check,
))

_register(InterviewStep(
    id="dividend_check",
    category="income",
    title="Dividend Income Check",
    description="Route based on whether user has dividend income.",
    next_step=route_dividend_check,
))

_register(InterviewStep(
    id="dividend_income",
    category="income",
    title="Dividend Income",
    description="Collect 1099-DIV details: ordinary and qualified dividends.",
    required_fields=["payer_name", "ordinary_dividends", "qualified_dividends"],
    repeatable=True,
    skippable=True,
    next_step=route_capital_gains_check,
))

_register(InterviewStep(
    id="capital_gains_check",
    category="income",
    title="Capital Gains Check",
    description="Route based on whether user has capital gains/losses.",
    next_step=route_capital_gains_check,
))

_register(InterviewStep(
    id="capital_gains_income",
    category="income",
    title="Capital Gains & Losses",
    description="Collect 1099-B details: description, proceeds, cost basis, long/short term.",
    required_fields=["description", "proceeds", "cost_basis", "is_long_term"],
    repeatable=True,
    skippable=True,
    next_step=route_retirement_check,
))

_register(InterviewStep(
    id="retirement_check",
    category="income",
    title="Retirement Income Check",
    description="Route based on whether user has retirement income.",
    next_step=route_retirement_check,
))

_register(InterviewStep(
    id="retirement_income",
    category="income",
    title="Retirement Income",
    description="Collect 1099-R details: source, gross distribution, taxable amount.",
    required_fields=["source", "gross_distribution", "taxable_amount"],
    repeatable=True,
    skippable=True,
    next_step=route_rental_check,
))

_register(InterviewStep(
    id="rental_check",
    category="income",
    title="Rental Income Check",
    description="Route based on whether user has rental income.",
    next_step=route_rental_check,
))

_register(InterviewStep(
    id="rental_income",
    category="income",
    title="Rental Income",
    description="Collect rental property details: property description, gross rent, expenses.",
    required_fields=["property_description", "gross_rent", "expenses"],
    repeatable=True,
    skippable=True,
    next_step=route_after_other_income,
))

_register(InterviewStep(
    id="other_income",
    category="income",
    title="Other Income",
    description="Ask about any other income not covered above.",
    required_fields=[],
    skippable=True,
    next_step=route_after_other_income,
))

# ===== ADJUSTMENTS =====

_register(InterviewStep(
    id="adjustments",
    category="adjustments",
    title="Adjustments to Income",
    description="Ask about above-the-line deductions: HSA, IRA, student loan interest, educator expenses, etc.",
    required_fields=[],
    skippable=True,
    next_step=route_after_adjustments,
))

# ===== DEDUCTIONS =====

_register(InterviewStep(
    id="deductions_choice",
    category="deductions",
    title="Standard vs. Itemized Deductions",
    description="Explain standard vs itemized deductions and help the user decide, or let the system auto-optimize.",
    required_fields=["deduction_preference"],
    next_step=route_deductions_choice,
))

_register(InterviewStep(
    id="itemized_deductions",
    category="deductions",
    title="Itemized Deductions",
    description="Collect itemized deduction details: medical, SALT, mortgage interest, charitable contributions.",
    required_fields=[],
    skippable=True,
    next_step=route_after_itemized,
))

# ===== CREDITS =====

_register(InterviewStep(
    id="credits",
    category="credits",
    title="Tax Credits",
    description="Ask about potential tax credits: child tax credit, education credits, energy credits, etc. The system will also auto-detect eligible credits.",
    required_fields=[],
    skippable=True,
    next_step=route_after_credits,
))

# ===== PAYMENTS =====

_register(InterviewStep(
    id="payments_withholding",
    category="payments",
    title="Payments & Withholding",
    description="Confirm total withholding from W-2s and ask about estimated tax payments made during the year.",
    required_fields=[],
    next_step=route_after_payments,
))

# ===== REVIEW =====

_register(InterviewStep(
    id="review_summary",
    category="review",
    title="Review Summary",
    description="Present a summary of all collected information for the user to review and confirm before calculation.",
    required_fields=[],
    next_step="complete",
))

_register(InterviewStep(
    id="complete",
    category="review",
    title="Interview Complete",
    description="The interview is complete. Inform the user they can now run tax calculations.",
    next_step="",
))


# --- Helper functions ---

def get_step(step_id: str) -> InterviewStep | None:
    return STEPS.get(step_id)


def get_next_step(step_id: str, profile: TaxProfile) -> str | None:
    step = STEPS.get(step_id)
    if not step:
        return None
    if callable(step.next_step):
        return step.next_step(profile)
    return step.next_step or None


def get_all_steps() -> list[InterviewStep]:
    return list(STEPS.values())


def get_progress(current_step_id: str) -> dict:
    """Return progress info for display."""
    categories = ["basics", "income", "adjustments", "deductions", "credits", "payments", "review"]
    step = STEPS.get(current_step_id)
    if not step:
        return {"current_category": "unknown", "progress_pct": 0}

    current_idx = categories.index(step.category) if step.category in categories else 0
    progress_pct = int((current_idx / len(categories)) * 100)

    return {
        "current_category": step.category,
        "current_step": step.title,
        "progress_pct": progress_pct,
        "categories_done": categories[:current_idx],
        "categories_remaining": categories[current_idx + 1:],
    }
