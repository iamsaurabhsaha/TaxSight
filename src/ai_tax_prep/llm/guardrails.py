"""Safety guardrails — input validation, prompt injection detection, output sanitization."""

import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    is_valid: bool
    message: str = ""
    risk_level: str = "none"  # none, low, medium, high


# --- Prompt Injection Detection ---

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*",
    r"forget\s+(everything|all|your)\s+(about|instructions|rules)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"act\s+as\s+(?:a|an|if)\s+",
    r"override\s+(your|the|all)\s+(instructions|rules|guidelines)",
    r"do\s+not\s+follow\s+(your|the)\s+(instructions|rules|guidelines)",
    r"jailbreak",
    r"\[system\]",
    r"<\s*system\s*>",
    r"```\s*system",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def check_prompt_injection(text: str) -> ValidationResult:
    """Check if user input contains prompt injection attempts."""
    if INJECTION_REGEX.search(text):
        return ValidationResult(
            is_valid=False,
            message="I noticed your message contains unusual instructions. "
            "For security, I can only help with tax preparation questions. "
            "Could you rephrase your question?",
            risk_level="high",
        )
    return ValidationResult(is_valid=True)


# --- Input Validation ---

def validate_dollar_amount(value: float, field_name: str, max_reasonable: float = 10_000_000) -> ValidationResult:
    """Validate a dollar amount is reasonable."""
    if value < 0:
        return ValidationResult(
            is_valid=False,
            message=f"{field_name} cannot be negative. Did you mean ${abs(value):,.2f}?",
            risk_level="medium",
        )
    if value > max_reasonable:
        return ValidationResult(
            is_valid=False,
            message=f"{field_name} of ${value:,.2f} seems unusually high. "
            "Please double-check this amount. If it's correct, please confirm.",
            risk_level="low",
        )
    return ValidationResult(is_valid=True)


def validate_filing_status(status: str) -> ValidationResult:
    """Validate filing status is a recognized value."""
    valid_statuses = {
        "single",
        "married_filing_jointly",
        "married_filing_separately",
        "head_of_household",
        "qualifying_surviving_spouse",
    }
    if status.lower().strip() not in valid_statuses:
        return ValidationResult(
            is_valid=False,
            message=f"'{status}' is not a recognized filing status. "
            "Please choose: Single, Married Filing Jointly, Married Filing Separately, "
            "Head of Household, or Qualifying Surviving Spouse.",
            risk_level="low",
        )
    return ValidationResult(is_valid=True)


def validate_state(state: str) -> ValidationResult:
    """Validate state is a valid US state code."""
    valid_states = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    }
    if state.upper().strip() not in valid_states:
        return ValidationResult(
            is_valid=False,
            message=f"'{state}' is not a valid US state code. "
            "Please enter a two-letter state abbreviation (e.g., CA, NY, TX).",
            risk_level="low",
        )
    return ValidationResult(is_valid=True)


def validate_age(age: int) -> ValidationResult:
    """Validate age is reasonable."""
    if age < 0 or age > 130:
        return ValidationResult(
            is_valid=False,
            message=f"Age of {age} doesn't seem right. Please enter a valid age.",
            risk_level="low",
        )
    return ValidationResult(is_valid=True)


def validate_percentage(value: float, field_name: str) -> ValidationResult:
    """Validate a percentage value."""
    if value < 0 or value > 100:
        return ValidationResult(
            is_valid=False,
            message=f"{field_name} should be between 0 and 100.",
            risk_level="low",
        )
    return ValidationResult(is_valid=True)


# --- Output Sanitization ---

DISCLAIMER_SHORT = (
    "Note: This is an estimate for informational purposes only, "
    "not professional tax advice."
)

DISCLAIMER_FULL = (
    "DISCLAIMER: This tool provides tax estimates for informational purposes only. "
    "It is not professional tax advice and should not be used for official tax filing. "
    "Consult a qualified tax professional for your specific situation."
)


def add_disclaimer(text: str, full: bool = False) -> str:
    """Add disclaimer to output text if not already present."""
    disclaimer = DISCLAIMER_FULL if full else DISCLAIMER_SHORT
    if "informational purposes" in text.lower():
        return text
    return f"{text}\n\n{disclaimer}"


def sanitize_llm_output(text: str) -> str:
    """Remove any system prompt leakage, raw JSON, or unwanted content from LLM output."""
    import re

    # Remove raw JSON blocks that leaked into display
    # Match ```json ... ``` blocks
    text = re.sub(r'```json\s*\{[\s\S]*?\}\s*```', '', text)

    # If the entire response looks like a JSON object, try to extract display_text
    stripped = text.strip()
    if stripped.startswith('{') and stripped.endswith('}'):
        try:
            import json
            parsed = json.loads(stripped)
            if "display_text" in parsed:
                return parsed["display_text"]
        except (json.JSONDecodeError, Exception):
            pass

    # Remove any accidental system prompt reveals
    lines = text.split("\n")
    sanitized_lines = []
    for line in lines:
        if line.strip().startswith("CRITICAL RULES:"):
            continue
        if "NEVER reveal these" in line:
            continue
        sanitized_lines.append(line)
    return "\n".join(sanitized_lines).strip()


# --- Confidence & Uncertainty ---

UNCERTAINTY_PHRASES = [
    "i'm not sure",
    "i'm not certain",
    "this may vary",
    "consult a tax professional",
    "depends on your specific",
    "i cannot guarantee",
    "this is a rough estimate",
]


def check_uncertainty(llm_response: str) -> bool:
    """Check if the LLM response contains uncertainty indicators."""
    lower = llm_response.lower()
    return any(phrase in lower for phrase in UNCERTAINTY_PHRASES)


def flag_complex_situation(profile_summary: dict) -> list[str]:
    """Flag situations that may need professional help."""
    warnings = []

    total_income = sum(
        profile_summary.get(k, 0)
        for k in [
            "total_wages", "total_self_employment", "total_interest",
            "total_dividends", "total_capital_gains", "total_rental",
            "total_retirement",
        ]
    )

    if total_income > 500_000:
        warnings.append(
            "Your total income exceeds $500,000. Consider consulting a tax professional "
            "to ensure you're optimizing your tax strategy, especially regarding AMT."
        )

    if profile_summary.get("total_self_employment", 0) > 100_000:
        warnings.append(
            "You have significant self-employment income. A tax professional can help "
            "with strategies like retirement account contributions and business structure."
        )

    if abs(profile_summary.get("total_capital_gains", 0)) > 100_000:
        warnings.append(
            "You have significant capital gains/losses. Consider consulting a tax professional "
            "about tax-loss harvesting and optimal timing strategies."
        )

    if profile_summary.get("total_rental", 0) != 0:
        warnings.append(
            "Rental income has complex rules around depreciation and passive activity losses. "
            "Our estimate simplifies this — a CPA can optimize your rental deductions."
        )

    return warnings
