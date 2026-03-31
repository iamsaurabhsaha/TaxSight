"""Custom calculations for gaps PolicyEngine doesn't cover."""

from ai_tax_prep.core.tax_profile import TaxProfile


def apply_adjustment_phaseouts(profile: TaxProfile, agi: float) -> dict:
    """Apply income-based phaseouts to adjustments.

    Returns dict of corrected adjustment amounts and any warnings.
    """
    corrections = {}
    warnings = []

    # Student loan interest deduction phaseout (2025)
    # Single: phaseout starts at $85,000, fully phased out at $100,000
    # MFJ: phaseout starts at $170,000, fully phased out at $200,000
    sli = profile.adjustments.student_loan_interest
    if sli > 0:
        if profile.personal_info.filing_status == "married_filing_jointly":
            phase_start, phase_end = 170_000, 200_000
        else:
            phase_start, phase_end = 85_000, 100_000

        if agi >= phase_end:
            corrections["student_loan_interest"] = 0
            warnings.append(
                f"Student loan interest deduction (${sli:,.2f}) is fully phased out "
                f"because your AGI (${agi:,.0f}) exceeds ${phase_end:,}."
            )
        elif agi > phase_start:
            # Partial phaseout
            ratio = (agi - phase_start) / (phase_end - phase_start)
            allowed = sli * (1 - ratio)
            corrections["student_loan_interest"] = round(allowed, 2)
            warnings.append(
                f"Student loan interest deduction reduced from ${sli:,.2f} to "
                f"${allowed:,.2f} due to income phaseout."
            )
        else:
            corrections["student_loan_interest"] = min(sli, 2_500)  # Cap at $2,500

    return {"corrections": corrections, "warnings": warnings}


def calculate_withholding_and_refund(profile: TaxProfile, pe_result: dict) -> dict:
    """Calculate total withholding and refund/amount owed.

    PolicyEngine doesn't track withholding — we compute it from W-2 data + estimated payments.
    """
    federal_withholding = profile.payments.federal_withholding
    state_withholding = profile.payments.state_withholding
    estimated_federal = profile.payments.estimated_federal_payments
    estimated_state = profile.payments.estimated_state_payments

    federal_tax = pe_result.get("federal_income_tax", 0)
    se_tax = pe_result.get("self_employment_tax", 0)
    state_tax = pe_result.get("state_income_tax", 0)

    total_federal_tax = federal_tax + se_tax
    total_federal_payments = federal_withholding + estimated_federal

    federal_refund = total_federal_payments - total_federal_tax
    state_refund = (state_withholding + estimated_state) - state_tax

    return {
        "federal_withholding": federal_withholding,
        "state_withholding": state_withholding,
        "estimated_federal_payments": estimated_federal,
        "estimated_state_payments": estimated_state,
        "total_federal_tax": total_federal_tax,
        "total_state_tax": state_tax,
        "federal_refund_or_owed": federal_refund,
        "state_refund_or_owed": state_refund,
        "total_refund_or_owed": federal_refund + state_refund,
    }


def calculate_se_tax_detail(profile: TaxProfile) -> dict:
    """Calculate detailed self-employment tax breakdown."""
    net_se_income = profile.income.total_self_employment()

    if net_se_income <= 0:
        return {
            "net_se_income": 0,
            "se_tax_base": 0,
            "ss_portion": 0,
            "medicare_portion": 0,
            "total_se_tax": 0,
            "se_tax_deduction": 0,
        }

    # 92.35% of net SE income is subject to SE tax
    se_tax_base = net_se_income * 0.9235

    # Social Security: 12.4% on first $168,600 (2025)
    ss_wage_base = 168_600
    existing_ss_wages = sum(w.ss_wages for w in profile.income.w2s)
    ss_taxable = min(se_tax_base, max(0, ss_wage_base - existing_ss_wages))
    ss_portion = ss_taxable * 0.124

    # Medicare: 2.9% on all SE income (no cap)
    medicare_portion = se_tax_base * 0.029

    # Additional Medicare: 0.9% on earnings over $200k (single) / $250k (MFJ)
    threshold = 250_000 if profile.personal_info.filing_status == "married_filing_jointly" else 200_000
    total_earnings = existing_ss_wages + se_tax_base
    additional_medicare = max(0, (total_earnings - threshold) * 0.009)

    total_se_tax = ss_portion + medicare_portion + additional_medicare

    # Half of SE tax is deductible
    se_tax_deduction = total_se_tax / 2

    return {
        "net_se_income": net_se_income,
        "se_tax_base": se_tax_base,
        "ss_portion": ss_portion,
        "medicare_portion": medicare_portion,
        "additional_medicare": additional_medicare,
        "total_se_tax": total_se_tax,
        "se_tax_deduction": se_tax_deduction,
    }


def calculate_schedule_c_detail(profile: TaxProfile) -> list[dict]:
    """Generate Schedule C detail for each self-employment activity."""
    details = []
    for se in profile.income.self_employment:
        details.append({
            "business_name": se.business_name,
            "gross_income": se.gross_income,
            "expenses": se.expenses,
            "net_profit": se.net_income,
        })
    return details


def calculate_effective_rates(profile: TaxProfile, pe_result: dict, custom_result: dict) -> dict:
    """Calculate effective and marginal tax rates."""
    total_income = (
        profile.income.total_wages()
        + profile.income.total_self_employment()
        + profile.income.total_interest()
        + profile.income.total_dividends()
        + profile.income.total_capital_gains()
        + profile.income.total_rental()
        + profile.income.total_retirement()
        + profile.income.other_income
    )

    if total_income <= 0:
        return {
            "total_gross_income": 0,
            "effective_federal_rate": 0,
            "effective_state_rate": 0,
            "effective_total_rate": 0,
        }

    federal_tax = custom_result.get("total_federal_tax", 0)
    state_tax = custom_result.get("total_state_tax", 0)
    total_tax = federal_tax + state_tax

    return {
        "total_gross_income": total_income,
        "effective_federal_rate": (federal_tax / total_income * 100) if total_income else 0,
        "effective_state_rate": (state_tax / total_income * 100) if total_income else 0,
        "effective_total_rate": (total_tax / total_income * 100) if total_income else 0,
    }
