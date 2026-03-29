"""Tests for interview step definitions and routing."""


from ai_tax_prep.core.interview_steps import (
    STEPS,
    get_all_steps,
    get_next_step,
    get_progress,
    get_step,
)
from ai_tax_prep.core.tax_profile import TaxProfile


class TestStepRegistry:
    def test_steps_registered(self):
        assert len(STEPS) > 20

    def test_welcome_exists(self):
        step = get_step("welcome")
        assert step is not None
        assert step.category == "basics"

    def test_complete_exists(self):
        step = get_step("complete")
        assert step is not None
        assert step.next_step == ""

    def test_nonexistent_step(self):
        assert get_step("nonexistent") is None

    def test_all_steps_have_required_fields(self):
        for step in get_all_steps():
            assert step.id, "Step missing id"
            assert step.category, f"Step {step.id} missing category"
            assert step.title, f"Step {step.id} missing title"
            assert step.description, f"Step {step.id} missing description"

    def test_categories_valid(self):
        valid = {"basics", "income", "adjustments", "deductions", "credits", "payments", "review"}
        for step in get_all_steps():
            assert step.category in valid, f"Step {step.id} has invalid category: {step.category}"


class TestStepRouting:
    def test_welcome_goes_to_filing_status(self):
        profile = TaxProfile()
        next_id = get_next_step("welcome", profile)
        assert next_id == "filing_status"

    def test_filing_status_goes_to_personal_info(self):
        profile = TaxProfile()
        next_id = get_next_step("filing_status", profile)
        assert next_id == "personal_info"

    def test_personal_info_goes_to_dependents(self):
        profile = TaxProfile()
        next_id = get_next_step("personal_info", profile)
        assert next_id == "dependents"

    def test_nonexistent_step_returns_none(self):
        profile = TaxProfile()
        assert get_next_step("nonexistent", profile) is None


class TestProgress:
    def test_welcome_progress(self):
        progress = get_progress("welcome")
        assert progress["progress_pct"] == 0
        assert progress["current_category"] == "basics"

    def test_income_progress(self):
        progress = get_progress("w2_income")
        assert progress["progress_pct"] > 0
        assert progress["current_category"] == "income"

    def test_review_progress(self):
        progress = get_progress("review_summary")
        assert progress["progress_pct"] > 50
        assert progress["current_category"] == "review"

    def test_unknown_step(self):
        progress = get_progress("nonexistent")
        assert progress["progress_pct"] == 0
