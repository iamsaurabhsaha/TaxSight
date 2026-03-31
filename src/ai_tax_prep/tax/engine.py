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
        se_detail = calculate_se_tax_detail(profile)

        # Inject our SE tax into pe_result if PE didn't compute it
        if pe_result.get("self_employment_tax", 0) == 0 and se_detail["total_se_tax"] > 0:
            pe_result["self_employment_tax"] = se_detail["total_se_tax"]

        custom_result = calculate_withholding_and_refund(profile, pe_result)
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
            "warnings": pe_result.get("phaseout_warnings", []),
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
        from ai_tax_prep.tax.custom_calcs import apply_adjustment_phaseouts

        total_income = (
            profile.income.total_wages()
            + profile.income.total_self_employment()
            + profile.income.total_interest()
            + profile.income.total_dividends()
            + profile.income.total_capital_gains()
            + profile.income.total_rental()
            + profile.income.total_retirement()
        )

        # Rough standard deduction (2025)
        standard_deductions = {
            "single": 15_000,
            "married_filing_jointly": 30_000,
            "married_filing_separately": 15_000,
            "head_of_household": 22_500,
            "qualifying_surviving_spouse": 30_000,
        }
        std_ded = standard_deductions.get(profile.personal_info.filing_status, 15_000)

        # Compute preliminary AGI for phaseout calculations
        preliminary_agi = total_income - profile.adjustments.total()

        # Apply adjustment phaseouts (e.g., student loan interest)
        phaseout_result = apply_adjustment_phaseouts(profile, preliminary_agi)
        corrections = phaseout_result["corrections"]

        # Recalculate AGI with corrected adjustments
        corrected_adjustments = profile.adjustments.total()
        if "student_loan_interest" in corrections:
            corrected_adjustments -= profile.adjustments.student_loan_interest
            corrected_adjustments += corrections["student_loan_interest"]

        agi = total_income - corrected_adjustments
        taxable = max(0, agi - std_ded)

        # Separate qualified dividends for preferential tax rate
        qualified_divs = profile.income.total_qualified_dividends()
        ordinary_taxable = max(0, taxable - qualified_divs)

        # Tax ordinary income at regular rates
        ordinary_tax = self._rough_federal_tax(ordinary_taxable, profile.personal_info.filing_status)

        # Tax qualified dividends at preferential rate (0%/15%/20%)
        qualified_div_tax = self._qualified_dividend_tax(
            qualified_divs, ordinary_taxable, profile.personal_info.filing_status
        )

        federal_tax = ordinary_tax + qualified_div_tax

        # NJ state tax (use actual NJ brackets instead of flat 5%)
        state = profile.personal_info.state_of_residence
        state_tax = self._rough_state_tax(agi, state, profile.personal_info.filing_status)

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
            "child_tax_credit": sum(2000 for d in profile.personal_info.dependents if d.age < 17) ,
            "self_employment_tax": 0,
            "state_income_tax": state_tax,
            "phaseout_warnings": phaseout_result["warnings"],
        }

    def _rough_federal_tax(self, taxable_income: float, filing_status: str) -> float:
        """Federal tax estimate using 2025 tax brackets."""
        if filing_status == "married_filing_jointly":
            # 2025 MFJ brackets (actual IRS values)
            brackets = [
                (23_850, 0.10),
                (96_950, 0.12),
                (206_700, 0.22),
                (394_600, 0.24),
                (501_050, 0.32),
                (751_600, 0.35),
                (float("inf"), 0.37),
            ]
        elif filing_status == "head_of_household":
            brackets = [
                (17_000, 0.10),
                (64_850, 0.12),
                (103_350, 0.22),
                (197_300, 0.24),
                (250_500, 0.32),
                (626_350, 0.35),
                (float("inf"), 0.37),
            ]
        else:
            # Single / MFS brackets (2025)
            brackets = [
                (11_925, 0.10),
                (48_475, 0.12),
                (103_350, 0.22),
                (197_300, 0.24),
                (250_525, 0.32),
                (626_350, 0.35),
                (float("inf"), 0.37),
            ]

        tax = 0
        prev = 0
        for limit, rate in brackets:
            if taxable_income <= prev:
                break
            taxable_in_bracket = min(taxable_income, limit) - prev
            tax += taxable_in_bracket * rate
            prev = limit

        return tax

    def _qualified_dividend_tax(
        self, qualified_divs: float, ordinary_taxable: float, filing_status: str
    ) -> float:
        """Calculate tax on qualified dividends at preferential rates (0%/15%/20%)."""
        if qualified_divs <= 0:
            return 0

        # 2025 thresholds for 0%/15%/20% qualified dividend rates
        if filing_status == "married_filing_jointly":
            zero_pct_limit = 96_700
            fifteen_pct_limit = 600_050
        else:  # single
            zero_pct_limit = 48_350
            fifteen_pct_limit = 533_400

        # The rate depends on where the dividends fall in the tax bracket stack
        total_taxable = ordinary_taxable + qualified_divs

        if total_taxable <= zero_pct_limit:
            return 0
        elif ordinary_taxable >= fifteen_pct_limit:
            return qualified_divs * 0.20
        elif ordinary_taxable >= zero_pct_limit:
            # All qualified divs at 15% (or 20% if above threshold)
            in_15_band = min(qualified_divs, fifteen_pct_limit - ordinary_taxable)
            in_20_band = max(0, qualified_divs - in_15_band)
            return in_15_band * 0.15 + in_20_band * 0.20
        else:
            # Some at 0%, rest at 15%
            in_zero_band = min(qualified_divs, zero_pct_limit - ordinary_taxable)
            remaining = qualified_divs - in_zero_band
            in_15_band = min(remaining, fifteen_pct_limit - zero_pct_limit)
            in_20_band = max(0, remaining - in_15_band)
            return in_15_band * 0.15 + in_20_band * 0.20

    def _rough_state_tax(self, agi: float, state: str, filing_status: str) -> float:
        """Calculate rough state income tax. Uses actual brackets for common states."""
        if state in ("FL", "TX", "NV", "WA", "WY", "SD", "TN", "AK", "NH"):
            return 0  # No state income tax

        # NJ brackets (2025, single/MFJ)
        if state == "NJ":
            nj_brackets = [
                (20_000, 0.014),
                (35_000, 0.0175),
                (40_000, 0.035),
                (75_000, 0.05525),
                (500_000, 0.0637),
                (1_000_000, 0.0897),
                (float("inf"), 0.1075),
            ]
            tax = 0
            prev = 0
            for limit, rate in nj_brackets:
                if agi <= prev:
                    break
                taxable_in_bracket = min(agi, limit) - prev
                tax += taxable_in_bracket * rate
                prev = limit
            return tax

        # NY brackets (simplified, single)
        if state == "NY":
            ny_brackets = [
                (8_500, 0.04),
                (11_700, 0.045),
                (13_900, 0.0525),
                (80_650, 0.0585),
                (215_400, 0.0625),
                (1_077_550, 0.0685),
                (float("inf"), 0.0882),
            ]
            tax = 0
            prev = 0
            for limit, rate in ny_brackets:
                if agi <= prev:
                    break
                taxable_in_bracket = min(agi, limit) - prev
                tax += taxable_in_bracket * rate
                prev = limit
            return tax

        # CA brackets (simplified, single)
        if state == "CA":
            ca_brackets = [
                (10_412, 0.01),
                (24_684, 0.02),
                (38_959, 0.04),
                (54_081, 0.06),
                (68_350, 0.08),
                (349_137, 0.093),
                (418_961, 0.103),
                (698_271, 0.113),
                (float("inf"), 0.123),
            ]
            tax = 0
            prev = 0
            for limit, rate in ca_brackets:
                if agi <= prev:
                    break
                taxable_in_bracket = min(agi, limit) - prev
                tax += taxable_in_bracket * rate
                prev = limit
            return tax

        # Default: rough 5% for other states
        return agi * 0.05

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
