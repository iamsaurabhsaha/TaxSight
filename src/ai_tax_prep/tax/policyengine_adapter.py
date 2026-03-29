"""PolicyEngine adapter — translates TaxProfile to PolicyEngine API format and runs calculations."""


import httpx

from ai_tax_prep.core.tax_profile import TaxProfile

PE_API_URL = "https://household.api.policyengine.org/us/calculate"

# State name mapping for PolicyEngine
STATE_CODES_TO_NAMES = {
    "AL": "AL", "AK": "AK", "AZ": "AZ", "AR": "AR", "CA": "CA",
    "CO": "CO", "CT": "CT", "DE": "DE", "FL": "FL", "GA": "GA",
    "HI": "HI", "ID": "ID", "IL": "IL", "IN": "IN", "IA": "IA",
    "KS": "KS", "KY": "KY", "LA": "LA", "ME": "ME", "MD": "MD",
    "MA": "MA", "MI": "MI", "MN": "MN", "MS": "MS", "MO": "MO",
    "MT": "MT", "NE": "NE", "NV": "NV", "NH": "NH", "NJ": "NJ",
    "NM": "NM", "NY": "NY", "NC": "NC", "ND": "ND", "OH": "OH",
    "OK": "OK", "OR": "OR", "PA": "PA", "RI": "RI", "SC": "SC",
    "SD": "SD", "TN": "TN", "TX": "TX", "UT": "UT", "VT": "VT",
    "VA": "VA", "WA": "WA", "WV": "WV", "WI": "WI", "WY": "WY",
    "DC": "DC",
}

FILING_STATUS_MAP = {
    "single": "SINGLE",
    "married_filing_jointly": "JOINT",
    "married_filing_separately": "SEPARATE",
    "head_of_household": "HEAD_OF_HOUSEHOLD",
    "qualifying_surviving_spouse": "SURVIVING_SPOUSE",
}


def build_household(profile: TaxProfile) -> dict:
    """Convert a TaxProfile into PolicyEngine household JSON."""
    tax_year = str(profile.tax_year)
    people = {}
    members = []

    # Primary filer
    people["filer"] = {
        "age": {tax_year: profile.personal_info.age or 30},
        "employment_income": {tax_year: profile.income.total_wages()},
        "self_employment_income": {tax_year: profile.income.total_self_employment()},
        "taxable_interest_income": {tax_year: profile.income.total_interest()},
        "qualified_dividend_income": {tax_year: profile.income.total_qualified_dividends()},
        "non_qualified_dividend_income": {
            tax_year: profile.income.total_dividends() - profile.income.total_qualified_dividends()
        },
        "long_term_capital_gains": {
            tax_year: sum(c.gain_loss for c in profile.income.capital_gains if c.is_long_term and c.gain_loss > 0)
        },
        "short_term_capital_gains": {
            tax_year: sum(c.gain_loss for c in profile.income.capital_gains if not c.is_long_term and c.gain_loss > 0)
        },
        "capital_losses": {
            tax_year: abs(sum(c.gain_loss for c in profile.income.capital_gains if c.gain_loss < 0))
        },
        "rental_income": {tax_year: profile.income.total_rental()},
        "taxable_pension_income": {tax_year: profile.income.total_retirement()},
        "tax_exempt_interest_income": {
            tax_year: sum(i.amount for i in profile.income.interest if i.is_tax_exempt)
        },
    }
    members.append("filer")

    # Dependents
    for i, dep in enumerate(profile.personal_info.dependents):
        dep_id = f"dependent_{i}"
        people[dep_id] = {
            "age": {tax_year: dep.age},
            "is_tax_unit_dependent": {tax_year: True},
        }
        members.append(dep_id)

    # Filing status
    filing_status = FILING_STATUS_MAP.get(
        profile.personal_info.filing_status, "SINGLE"
    )

    # State
    state = profile.personal_info.state_of_residence or "CA"

    household = {
        "people": people,
        "tax_units": {
            "tax_unit": {
                "members": members,
                "filing_status": {tax_year: filing_status},
            }
        },
        "families": {
            "family": {"members": members}
        },
        "households": {
            "household": {
                "members": members,
                "state_code": {tax_year: state},
            }
        },
        "marital_units": {
            "marital_unit": {"members": ["filer"]}
        },
        "spm_units": {
            "spm_unit": {"members": members}
        },
    }

    return household


def calculate_via_api(profile: TaxProfile) -> dict:
    """Run tax calculation via PolicyEngine's free API.

    Returns dict with federal_tax, state_tax, credits, deductions, etc.
    """
    household = build_household(profile)
    tax_year = str(profile.tax_year)

    # Add output variables we want
    household["tax_units"]["tax_unit"].update({
        "income_tax": {tax_year: None},
        "income_tax_before_credits": {tax_year: None},
        "taxable_income": {tax_year: None},
        "adjusted_gross_income": {tax_year: None},
        "standard_deduction": {tax_year: None},
        "tax_unit_itemizes": {tax_year: None},
        "eitc": {tax_year: None},
        "child_tax_credit": {tax_year: None},
        "self_employment_tax": {tax_year: None},
    })

    household["households"]["household"].update({
        "state_income_tax": {tax_year: None},
    })

    try:
        response = httpx.post(
            PE_API_URL,
            json={"household": household},
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        tu = result.get("tax_units", {}).get("tax_unit", {})
        hh = result.get("households", {}).get("household", {})

        return {
            "engine": "policyengine_api",
            "federal_income_tax": _extract_value(tu, "income_tax", tax_year),
            "income_tax_before_credits": _extract_value(tu, "income_tax_before_credits", tax_year),
            "taxable_income": _extract_value(tu, "taxable_income", tax_year),
            "agi": _extract_value(tu, "adjusted_gross_income", tax_year),
            "standard_deduction": _extract_value(tu, "standard_deduction", tax_year),
            "itemizes": _extract_value(tu, "tax_unit_itemizes", tax_year),
            "eitc": _extract_value(tu, "eitc", tax_year),
            "child_tax_credit": _extract_value(tu, "child_tax_credit", tax_year),
            "self_employment_tax": _extract_value(tu, "self_employment_tax", tax_year),
            "state_income_tax": _extract_value(hh, "state_income_tax", tax_year),
            "success": True,
        }

    except Exception as e:
        return {
            "engine": "policyengine_api",
            "success": False,
            "error": str(e),
        }


def calculate_local(profile: TaxProfile) -> dict:
    """Run tax calculation using locally installed policyengine-us."""
    try:
        from policyengine_us import Simulation

        household = build_household(profile)
        tax_year = profile.tax_year

        sim = Simulation(situation=household)

        return {
            "engine": "policyengine_local",
            "federal_income_tax": float(sim.calculate("income_tax", tax_year)[0]),
            "taxable_income": float(sim.calculate("taxable_income", tax_year)[0]),
            "agi": float(sim.calculate("adjusted_gross_income", tax_year)[0]),
            "standard_deduction": float(sim.calculate("standard_deduction", tax_year)[0]),
            "itemizes": bool(sim.calculate("tax_unit_itemizes", tax_year)[0]),
            "eitc": float(sim.calculate("eitc", tax_year)[0]),
            "child_tax_credit": float(sim.calculate("child_tax_credit", tax_year)[0]),
            "self_employment_tax": float(sim.calculate("self_employment_tax", tax_year)[0]),
            "state_income_tax": float(sim.calculate("state_income_tax", tax_year)[0]),
            "success": True,
        }
    except ImportError:
        return {
            "engine": "policyengine_local",
            "success": False,
            "error": "policyengine-us not installed. Install with: pip install policyengine-us",
        }
    except Exception as e:
        return {
            "engine": "policyengine_local",
            "success": False,
            "error": str(e),
        }


def _extract_value(data: dict, key: str, year: str):
    """Extract a value from PolicyEngine's nested response format."""
    val = data.get(key, {})
    if isinstance(val, dict):
        return val.get(year, 0)
    return val or 0
