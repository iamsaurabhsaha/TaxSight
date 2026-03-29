"""Hybrid tax calculation engine — orchestrates PolicyEngine + custom logic."""

import json

from ai_tax_prep.config.settings import get_settings
from ai_tax_prep.core.tax_profile import TaxProfile
from ai_tax_prep.db.database import get_session_factory, init_db
from ai_tax_prep.db.models import CalculationResult
from ai_tax_prep.llm.client import LLMClient
from ai_tax_prep.tax.custom_calcs import (
    calculate_effective_rates,
    calculate_schedule_c_detail,
    calculate_se_tax_detail,
    calculate_withholding_and_refund,
)
from ai_tax_prep.tax.deductions import find_deductions_and_credits
from ai_tax_prep.tax.policyengine_adapter import calculate_local, calculate_via_api


class TaxEngine:
    """Orchestrates tax calculations using PolicyEngine + custom logic."""

    def __init__(self, session_id: str, llm: LLMClient | None = None):
        self.session_id = session_id
        self.settings = get_settings()
        self.llm = llm or LLMClient()
        init_db()
        self._db_factory = get_session_factory()

    def _get_db(self):
        return self._db_factory()

    def calculate(self, profile: TaxProfile) -> dict:
        """Run full tax calculation and return comprehensive results."""

        # Step 1: PolicyEngine calculation
        if self.settings.pe_mode == "local":
            pe_result = calculate_local(profile)
        else:
            pe_result = calculate_via_api(profile)

        if not pe_result.get("success"):
            # Fallback: return what we can compute ourselves
            pe_result = self._fallback_estimate(profile)

        # Step 2: Custom calculations (withholding, refund, SE detail)
        custom_result = calculate_withholding_and_refund(profile, pe_result)
        se_detail = calculate_se_tax_detail(profile)
        schedule_c = calculate_schedule_c_detail(profile)
        rates = calculate_effective_rates(profile, pe_result, custom_result)

        # Step 3: Deduction/credit finder
        suggestions = find_deductions_and_credits(profile, pe_result)

        # Step 4: Combine results
        result = {
            "tax_year": profile.tax_year,
            "filing_status": profile.personal_info.filing_status,
            "state": profile.personal_info.state_of_residence,

            # Income
            "total_gross_income": rates["total_gross_income"],
            "agi": pe_result.get("agi", 0),
            "taxable_income": pe_result.get("taxable_income", 0),

            # Deductions
            "standard_deduction": pe_result.get("standard_deduction", 0),
            "itemizes": pe_result.get("itemizes", False),
            "itemized_total": profile.itemized_deductions.total(),

            # Federal Tax
            "federal_income_tax": pe_result.get("federal_income_tax", 0),
            "income_tax_before_credits": pe_result.get("income_tax_before_credits", 0),

            # Self-Employment
            "se_tax_detail": se_detail,
            "schedule_c": schedule_c,

            # Credits
            "eitc": pe_result.get("eitc", 0),
            "child_tax_credit": pe_result.get("child_tax_credit", 0),

            # State
            "state_income_tax": pe_result.get("state_income_tax", 0),

            # Withholding & Refund
            **custom_result,

            # Rates
            **rates,

            # Suggestions
            "deduction_credit_suggestions": suggestions,

            # Engine info
            "engine_used": pe_result.get("engine", "unknown"),
            "warnings": [],
        }

        # Add warnings
        if not pe_result.get("success"):
            result["warnings"].append(
                "PolicyEngine calculation failed. Results are based on simplified estimates."
            )

        if profile.use_itemized is None:
            # Auto-optimize
            if profile.itemized_deductions.total() > pe_result.get("standard_deduction", 0):
                result["deduction_recommendation"] = "itemized"
            else:
                result["deduction_recommendation"] = "standard"

        # Step 5: Save to database
        self._save_result(profile, result)

        return result

    def what_if(self, profile: TaxProfile, changes: dict) -> dict:
        """Run a what-if scenario: apply temporary changes and compare results.

        Args:
            profile: Current tax profile
            changes: Dict of changes to apply, e.g.:
                {"ira_contribution": 5000}
                {"filing_status": "married_filing_jointly"}
                {"additional_income": 10000}

        Returns:
            Dict with "baseline", "scenario", and "difference" results.
        """
        import copy

        # Calculate baseline
        baseline = self.calculate(profile)

        # Apply changes to a copy
        modified = copy.deepcopy(profile)

        if "ira_contribution" in changes:
            modified.adjustments.ira_contributions = float(changes["ira_contribution"])

        if "hsa_contribution" in changes:
            modified.adjustments.hsa_contributions = float(changes["hsa_contribution"])

        if "filing_status" in changes:
            modified.personal_info.filing_status = changes["filing_status"]

        if "additional_income" in changes:
            modified.income.other_income += float(changes["additional_income"])

        if "charitable_donation" in changes:
            modified.itemized_deductions.charitable_cash += float(changes["charitable_donation"])

        if "use_itemized" in changes:
            modified.use_itemized = changes["use_itemized"]

        if "retirement_contribution" in changes:
            modified.adjustments.ira_contributions += float(changes["retirement_contribution"])

        # Calculate scenario
        scenario = self.calculate(modified)

        # Compare
        difference = {
            "federal_tax_change": scenario["federal_income_tax"] - baseline["federal_income_tax"],
            "state_tax_change": scenario["state_income_tax"] - baseline["state_income_tax"],
            "total_tax_change": (
                (scenario["total_federal_tax"] + scenario["state_income_tax"])
                - (baseline["total_federal_tax"] + baseline["state_income_tax"])
            ),
            "refund_change": scenario["total_refund_or_owed"] - baseline["total_refund_or_owed"],
            "agi_change": scenario["agi"] - baseline["agi"],
        }

        return {
            "baseline": baseline,
            "scenario": scenario,
            "difference": difference,
            "changes_applied": changes,
        }

    def explain_results(self, result: dict) -> str:
        """Use LLM to generate plain-English explanation of tax results."""
        prompt = f"""Explain this tax calculation result in plain English. Be concise and helpful.

Tax Year: {result['tax_year']}
Filing Status: {result['filing_status']}
State: {result['state']}

Income:
- Total Gross Income: ${result['total_gross_income']:,.2f}
- Adjusted Gross Income: ${result['agi']:,.2f}
- Taxable Income: ${result['taxable_income']:,.2f}

Deductions:
- Standard Deduction: ${result['standard_deduction']:,.2f}
- Using: {'Itemized' if result['itemizes'] else 'Standard'} deduction

Taxes:
- Federal Income Tax: ${result['federal_income_tax']:,.2f}
- Self-Employment Tax: ${result['se_tax_detail']['total_se_tax']:,.2f}
- State Income Tax: ${result['state_income_tax']:,.2f}

Payments & Refund:
- Federal Withholding: ${result['federal_withholding']:,.2f}
- Estimated Payments: ${result['estimated_federal_payments']:,.2f}
- Federal Refund/Owed: ${result['federal_refund_or_owed']:,.2f}
- State Refund/Owed: ${result['state_refund_or_owed']:,.2f}

Effective Rate: {result['effective_total_rate']:.1f}%

Provide a 4-6 sentence summary. If they're getting a refund, mention it. If they owe, explain why.
Mention the effective tax rate. End with the disclaimer that this is an estimate.
"""
        messages = [
            {"role": "system", "content": "You are a helpful tax assistant explaining results in plain English."},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages)

    def _fallback_estimate(self, profile: TaxProfile) -> dict:
        """Simple fallback if PolicyEngine is unavailable."""
        total_income = (
            profile.income.total_wages()
            + profile.income.total_self_employment()
            + profile.income.total_interest()
            + profile.income.total_dividends()
            + profile.income.total_capital_gains()
            + profile.income.total_rental()
            + profile.income.total_retirement()
        )

        # Rough standard deduction
        standard_deductions = {
            "single": 15_000,
            "married_filing_jointly": 30_000,
            "married_filing_separately": 15_000,
            "head_of_household": 22_500,
            "qualifying_surviving_spouse": 30_000,
        }
        std_ded = standard_deductions.get(profile.personal_info.filing_status, 15_000)

        agi = total_income - profile.adjustments.total()
        taxable = max(0, agi - std_ded)

        # Rough federal tax using 2025 brackets (single)
        federal_tax = self._rough_federal_tax(taxable, profile.personal_info.filing_status)

        return {
            "engine": "fallback",
            "success": True,
            "federal_income_tax": federal_tax,
            "income_tax_before_credits": federal_tax,
            "taxable_income": taxable,
            "agi": agi,
            "standard_deduction": std_ded,
            "itemizes": False,
            "eitc": 0,
            "child_tax_credit": len(profile.personal_info.dependents) * 2000,
            "self_employment_tax": 0,
            "state_income_tax": agi * 0.05,  # Rough 5% state estimate
        }

    def _rough_federal_tax(self, taxable_income: float, filing_status: str) -> float:
        """Rough federal tax estimate using simplified brackets."""
        # 2025 brackets (single)
        brackets = [
            (11_925, 0.10),
            (48_475, 0.12),
            (103_350, 0.22),
            (197_300, 0.24),
            (250_525, 0.32),
            (626_350, 0.35),
            (float("inf"), 0.37),
        ]

        if filing_status == "married_filing_jointly":
            brackets = [(b * 2, r) for b, r in brackets]

        tax = 0
        prev = 0
        for limit, rate in brackets:
            if taxable_income <= prev:
                break
            taxable_in_bracket = min(taxable_income, limit) - prev
            tax += taxable_in_bracket * rate
            prev = limit

        return tax

    def _save_result(self, profile: TaxProfile, result: dict):
        """Save calculation result to database."""
        db = self._get_db()
        try:
            # Serialize only JSON-safe parts
            safe_result = {k: v for k, v in result.items() if k != "deduction_credit_suggestions"}
            safe_result["deduction_credit_suggestions"] = [
                {k: v for k, v in s.items()} for s in result.get("deduction_credit_suggestions", [])
            ]

            calc = CalculationResult(
                session_id=self.session_id,
                calc_type="combined",
                engine_used=result.get("engine_used", "unknown"),
                input_snapshot=profile.to_json(),
                result_data=json.dumps(safe_result, default=str),
                warnings=json.dumps(result.get("warnings", [])),
            )
            db.add(calc)
            db.commit()
        finally:
            db.close()
