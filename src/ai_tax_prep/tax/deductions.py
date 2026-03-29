"""Deduction and credit finder — surfaces applicable deductions/credits using rules + LLM."""


from ai_tax_prep.core.tax_profile import TaxProfile
from ai_tax_prep.llm.client import LLMClient


def find_deductions_and_credits(profile: TaxProfile, pe_result: dict) -> list[dict]:
    """Analyze the profile and return a list of applicable deductions/credits with explanations."""
    suggestions = []

    filing_status = profile.personal_info.filing_status
    total_wages = profile.income.total_wages()
    total_se = profile.income.total_self_employment()
    agi = pe_result.get("agi", 0)
    num_dependents = len(profile.personal_info.dependents)

    # --- Credits ---

    # Child Tax Credit
    children_under_17 = sum(1 for d in profile.personal_info.dependents if d.age < 17)
    if children_under_17 > 0:
        ctc_amount = children_under_17 * 2_000
        suggestions.append({
            "type": "credit",
            "name": "Child Tax Credit",
            "estimated_value": ctc_amount,
            "applies": True,
            "explanation": f"You have {children_under_17} child(ren) under 17. "
            f"The Child Tax Credit is up to $2,000 per qualifying child, "
            f"potentially worth ${ctc_amount:,.0f}.",
        })

    # Earned Income Tax Credit
    eitc = pe_result.get("eitc", 0)
    if eitc and eitc > 0:
        suggestions.append({
            "type": "credit",
            "name": "Earned Income Tax Credit (EITC)",
            "estimated_value": eitc,
            "applies": True,
            "explanation": f"Based on your income and family size, you may qualify for "
            f"the EITC worth approximately ${eitc:,.0f}. This is a refundable credit.",
        })

    # Child and Dependent Care Credit
    if children_under_17 > 0 and (total_wages > 0 or total_se > 0):
        suggestions.append({
            "type": "credit",
            "name": "Child and Dependent Care Credit",
            "estimated_value": None,
            "applies": None,
            "explanation": "If you paid for daycare, after-school care, or a babysitter "
            "so you could work, you may qualify for the Child and Dependent Care Credit. "
            "Did you have childcare expenses this year?",
        })

    # Education Credits
    dependents_college_age = sum(1 for d in profile.personal_info.dependents if 17 <= d.age <= 24)
    if dependents_college_age > 0 or profile.personal_info.age <= 30:
        suggestions.append({
            "type": "credit",
            "name": "Education Credits (AOC / Lifetime Learning)",
            "estimated_value": None,
            "applies": None,
            "explanation": "If you or a dependent paid college tuition, you may qualify for "
            "the American Opportunity Credit (up to $2,500) or the Lifetime Learning Credit "
            "(up to $2,000). Did you have education expenses?",
        })

    # Saver's Credit
    if agi < 76_500 and profile.adjustments.ira_contributions > 0:
        rate = 0.5 if agi <= 23_000 else (0.2 if agi <= 25_000 else 0.1)
        credit = min(profile.adjustments.ira_contributions, 2_000) * rate
        suggestions.append({
            "type": "credit",
            "name": "Retirement Savings Credit (Saver's Credit)",
            "estimated_value": credit,
            "applies": True,
            "explanation": f"Your IRA contribution of ${profile.adjustments.ira_contributions:,.0f} "
            f"qualifies for the Saver's Credit, potentially worth ${credit:,.0f}.",
        })

    # --- Deductions / Adjustments ---

    # HSA
    if profile.adjustments.hsa_contributions == 0 and total_wages > 0:
        suggestions.append({
            "type": "deduction",
            "name": "HSA Contributions",
            "estimated_value": None,
            "applies": None,
            "explanation": "If you have a high-deductible health plan, HSA contributions are "
            "tax-deductible. For 2025, the limit is $4,300 (self) or $8,550 (family). "
            "Do you contribute to an HSA?",
        })

    # IRA
    if profile.adjustments.ira_contributions == 0 and agi > 0:
        max_ira = 7_000 if profile.personal_info.age < 50 else 8_000
        suggestions.append({
            "type": "deduction",
            "name": "Traditional IRA Contribution",
            "estimated_value": None,
            "applies": None,
            "explanation": f"You can deduct up to ${max_ira:,} in Traditional IRA contributions "
            f"(you have until April 15 to contribute for the prior tax year). "
            f"This directly reduces your taxable income.",
        })

    # Student Loan Interest
    if profile.adjustments.student_loan_interest == 0 and profile.personal_info.age <= 40:
        suggestions.append({
            "type": "deduction",
            "name": "Student Loan Interest Deduction",
            "estimated_value": None,
            "applies": None,
            "explanation": "You can deduct up to $2,500 in student loan interest paid. "
            "Did you pay student loan interest this year?",
        })

    # Self-Employment Deductions
    if total_se > 0:
        if profile.adjustments.self_employment_health_insurance == 0:
            suggestions.append({
                "type": "deduction",
                "name": "Self-Employed Health Insurance",
                "estimated_value": None,
                "applies": None,
                "explanation": "As a self-employed individual, you can deduct 100% of health "
                "insurance premiums for yourself, your spouse, and dependents. "
                "Did you pay for your own health insurance?",
            })

        suggestions.append({
            "type": "deduction",
            "name": "Home Office Deduction",
            "estimated_value": None,
            "applies": None,
            "explanation": "If you use part of your home regularly and exclusively for business, "
            "you may deduct home office expenses. The simplified method allows $5/sq ft, "
            "up to 300 sq ft ($1,500 max).",
        })

    # Standard vs Itemized comparison
    standard_deduction = pe_result.get("standard_deduction", 0)
    itemized_total = profile.itemized_deductions.total()
    if itemized_total > 0 and standard_deduction > 0:
        if itemized_total > standard_deduction:
            savings = itemized_total - standard_deduction
            suggestions.append({
                "type": "deduction",
                "name": "Itemize Your Deductions",
                "estimated_value": savings * 0.22,  # rough tax savings estimate
                "applies": True,
                "explanation": f"Your itemized deductions (${itemized_total:,.0f}) exceed the "
                f"standard deduction (${standard_deduction:,.0f}). Itemizing could save you "
                f"approximately ${savings * 0.22:,.0f} in taxes.",
            })
        else:
            suggestions.append({
                "type": "deduction",
                "name": "Take the Standard Deduction",
                "estimated_value": None,
                "applies": True,
                "explanation": f"Your itemized deductions (${itemized_total:,.0f}) are less than "
                f"the standard deduction (${standard_deduction:,.0f}). The standard deduction "
                f"is the better choice for you.",
            })

    return suggestions


def explain_deductions_with_llm(
    suggestions: list[dict],
    profile: TaxProfile,
    llm: LLMClient | None = None,
) -> str:
    """Use LLM to generate a plain-English summary of deduction/credit findings."""
    if not llm:
        llm = LLMClient()

    applicable = [s for s in suggestions if s.get("applies") is True]
    possible = [s for s in suggestions if s.get("applies") is None]

    prompt = f"""Based on this taxpayer's profile, provide a brief, friendly summary of their
tax deduction and credit situation.

Filing status: {profile.personal_info.filing_status}
AGI estimate: approximate based on income provided

Confirmed applicable:
{chr(10).join(f"- {s['name']}: {s['explanation']}" for s in applicable) or "None identified yet"}

Worth investigating:
{chr(10).join(f"- {s['name']}: {s['explanation']}" for s in possible) or "None"}

Keep it concise (3-5 sentences). Focus on the biggest potential savings.
Remind them this is an estimate and to consult a tax professional for complex situations."""

    messages = [
        {"role": "system", "content": "You are a helpful tax assistant providing plain-English explanations."},
        {"role": "user", "content": prompt},
    ]

    return llm.chat(messages)
