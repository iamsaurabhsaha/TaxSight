"""Interview engine — state machine orchestrator that drives the conversational flow."""

import json

from ai_tax_prep.core.interview_steps import (
    InterviewStep,
    get_next_step,
    get_progress,
    get_step,
)
from ai_tax_prep.core.tax_profile import (
    CapitalGain,
    Dependent,
    DividendIncome,
    InterestIncome,
    RentalIncome,
    RetirementIncome,
    SelfEmploymentIncome,
    TaxProfile,
    W2Income,
)
from ai_tax_prep.db.database import get_session_factory, init_db
from ai_tax_prep.db.repository import ChatRepository, SessionRepository, TaxProfileRepository
from ai_tax_prep.llm.client import LLMClient
from ai_tax_prep.llm.guardrails import (
    check_prompt_injection,
    flag_complex_situation,
    sanitize_llm_output,
)
from ai_tax_prep.llm.prompts import (
    EXTRACTION_PROMPT,
    build_messages,
    get_step_prompt,
)


class InterviewEngine:
    """Drives the tax interview — manages state, LLM calls, and profile updates."""

    def __init__(self, session_id: str, llm_client: LLMClient | None = None):
        self.session_id = session_id
        self.llm = llm_client or LLMClient()

        init_db()
        self._db_factory = get_session_factory()

        # Load session state
        db = self._get_db()
        try:
            self._session_repo = SessionRepository(db)
            self._profile_repo = TaxProfileRepository(db)
            self._chat_repo = ChatRepository(db)

            session = self._session_repo.get(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")

            self.tax_year = session.tax_year
            self.current_step_id = session.current_step or "welcome"

            # Load tax profile
            db_profile = self._profile_repo.get_by_session(session_id)
            if db_profile and db_profile.profile_data and db_profile.profile_data != "{}":
                try:
                    self.profile = TaxProfile.from_json(db_profile.profile_data)
                except Exception:
                    self.profile = TaxProfile(tax_year=self.tax_year)
            else:
                self.profile = TaxProfile(tax_year=self.tax_year)

            # Track income types the user says they have (for routing)
            self._pending_income_types: set[str] = set()
        finally:
            db.close()

    def _get_db(self):
        return self._db_factory()

    def get_current_step(self) -> InterviewStep | None:
        return get_step(self.current_step_id)

    def get_progress(self) -> dict:
        return get_progress(self.current_step_id)

    def _get_chat_history(self) -> list[dict]:
        """Load recent chat history from DB."""
        db = self._get_db()
        try:
            repo = ChatRepository(db)
            messages = repo.get_messages(self.session_id)
            return [{"role": m.role, "content": m.content} for m in messages[-20:]]
        finally:
            db.close()

    def _save_message(self, role: str, content: str, step_id: str | None = None):
        """Persist a chat message."""
        db = self._get_db()
        try:
            repo = ChatRepository(db)
            token_count = self.llm.count_tokens(content)
            repo.add_message(
                session_id=self.session_id,
                role=role,
                content=content,
                step_id=step_id or self.current_step_id,
                token_count=token_count,
            )
        finally:
            db.close()

    def _save_profile(self):
        """Persist the current tax profile."""
        db = self._get_db()
        try:
            repo = TaxProfileRepository(db)
            db_profile = repo.get_by_session(self.session_id)
            if db_profile:
                db_profile.profile_data = self.profile.to_json()
                db_profile.filing_status = self.profile.personal_info.filing_status
                db_profile.state_of_residence = self.profile.personal_info.state_of_residence
                db_profile.num_dependents = len(self.profile.personal_info.dependents)
                db.commit()
        finally:
            db.close()

    def _update_session_step(self, step_id: str):
        """Update the current step in the session."""
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            repo.update_step(self.session_id, step_id)
        finally:
            db.close()

    def _build_prompt_kwargs(self) -> dict:
        """Build template variables for step prompts."""
        summary = self.profile.summary()
        return {
            "tax_year": self.tax_year,
            "filing_status": self.profile.personal_info.filing_status or "not yet determined",
            "profile_summary": json.dumps(summary, indent=2),
            "w2_count": len(self.profile.income.w2s) + 1,
            "total_federal_withholding": f"{self.profile.income.total_federal_withholding():,.2f}",
            "total_state_withholding": f"{self.profile.income.total_state_withholding():,.2f}",
        }

    def generate_step_message(self) -> str:
        """Generate the LLM's opening message for the current step."""
        step = self.get_current_step()
        if not step:
            return "Something went wrong — I couldn't find the current step."

        kwargs = self._build_prompt_kwargs()
        step_prompt = get_step_prompt(step.id, **kwargs)
        chat_history = self._get_chat_history()

        messages = build_messages(
            step_id=step.id,
            chat_history=chat_history,
            step_prompt=step_prompt,
        )

        response = self.llm.chat(messages)
        response = sanitize_llm_output(response)

        # Save assistant message
        self._save_message("assistant", response)

        return response

    def stream_step_message(self):
        """Stream the LLM's opening message for the current step."""
        step = self.get_current_step()
        if not step:
            yield "Something went wrong — I couldn't find the current step."
            return

        kwargs = self._build_prompt_kwargs()
        step_prompt = get_step_prompt(step.id, **kwargs)
        chat_history = self._get_chat_history()

        messages = build_messages(
            step_id=step.id,
            chat_history=chat_history,
            step_prompt=step_prompt,
        )

        full_response = ""
        for chunk in self.llm.chat_stream(messages):
            full_response += chunk
            yield chunk

        full_response = sanitize_llm_output(full_response)
        self._save_message("assistant", full_response)

    def process_user_input(self, user_input: str) -> dict:
        """Process user input, extract data, update profile, and determine next action.

        Returns:
            dict with keys:
                - "response": str — the display text for the user
                - "action": str — "continue" (stay on step), "next" (advance), "complete"
                - "next_step": str | None — the next step ID if action is "next"
                - "warnings": list[str] — any warnings to display
        """
        # Check for prompt injection
        injection_check = check_prompt_injection(user_input)
        if not injection_check.is_valid:
            return {
                "response": injection_check.message,
                "action": "continue",
                "next_step": None,
                "warnings": [],
            }

        # Save user message
        self._save_message("user", user_input)

        step = self.get_current_step()
        if not step:
            return {
                "response": "Session error. Please try again.",
                "action": "continue",
                "next_step": None,
                "warnings": [],
            }

        # Build extraction prompt
        kwargs = self._build_prompt_kwargs()
        step_prompt = get_step_prompt(step.id, **kwargs)
        chat_history = self._get_chat_history()

        extraction_context = EXTRACTION_PROMPT.format(
            step_id=step.id,
            step_title=step.title,
            required_fields=", ".join(step.required_fields) if step.required_fields else "none — just acknowledge",
        )

        messages = build_messages(
            step_id=step.id,
            chat_history=chat_history,
            step_prompt=step_prompt + "\n\n" + extraction_context,
        )

        # Get LLM response with extraction
        try:
            result = self.llm.chat_json(messages)
        except (ValueError, Exception):
            # Fallback: get a regular response
            response = self.llm.chat(messages)
            response = sanitize_llm_output(response)
            self._save_message("assistant", response)
            return {
                "response": response,
                "action": "continue",
                "next_step": None,
                "warnings": [],
            }

        display_text = sanitize_llm_output(result.get("display_text", ""))
        extracted_data = result.get("extracted_data", {})
        needs_clarification = result.get("needs_clarification", False)

        # Save assistant response
        self._save_message("assistant", display_text)

        # If clarification needed, stay on this step
        if needs_clarification:
            return {
                "response": display_text,
                "action": "continue",
                "next_step": None,
                "warnings": [],
            }

        # Apply extracted data to profile
        if extracted_data:
            self._apply_extracted_data(step.id, extracted_data)
            self._save_profile()

        # Determine next step
        next_step_id = get_next_step(step.id, self.profile)

        # Handle special routing for income sources
        if step.id == "income_sources" and extracted_data:
            self._process_income_types(extracted_data)
            next_step_id = self._route_first_income_type()

        # Handle W-2 "more" routing
        if step.id == "w2_more" and extracted_data:
            has_more = extracted_data.get("has_more_w2", False)
            if has_more:
                next_step_id = "w2_income"
            else:
                next_step_id = self._route_next_income_after("w2")

        if next_step_id == "complete":
            self._update_session_step("complete")
            db = self._get_db()
            try:
                repo = SessionRepository(db)
                repo.update_status(self.session_id, "completed")
            finally:
                db.close()

            warnings = flag_complex_situation(self.profile.summary())
            return {
                "response": display_text,
                "action": "complete",
                "next_step": None,
                "warnings": warnings,
            }

        if next_step_id and next_step_id != self.current_step_id:
            self.current_step_id = next_step_id
            self._update_session_step(next_step_id)
            return {
                "response": display_text,
                "action": "next",
                "next_step": next_step_id,
                "warnings": [],
            }

        return {
            "response": display_text,
            "action": "continue",
            "next_step": None,
            "warnings": [],
        }

    def _apply_extracted_data(self, step_id: str, data: dict):
        """Apply extracted data to the tax profile based on the current step."""
        if not data:
            return

        if step_id == "filing_status":
            status = data.get("filing_status", "")
            if status:
                self.profile.personal_info.filing_status = status.lower().strip()

        elif step_id == "personal_info":
            if data.get("first_name"):
                self.profile.personal_info.first_name = data["first_name"]
            if data.get("last_name"):
                self.profile.personal_info.last_name = data["last_name"]
            if data.get("age"):
                self.profile.personal_info.age = int(data["age"])
            if data.get("state_of_residence"):
                self.profile.personal_info.state_of_residence = data["state_of_residence"].upper().strip()

        elif step_id == "dependents":
            dependents = data.get("dependents", [])
            if isinstance(dependents, list):
                for dep in dependents:
                    if isinstance(dep, dict):
                        self.profile.personal_info.dependents.append(
                            Dependent(
                                name=dep.get("name", ""),
                                relationship=dep.get("relationship", ""),
                                age=int(dep.get("age", 0)),
                            )
                        )

        elif step_id == "w2_income":
            w2 = W2Income(
                employer_name=data.get("employer_name", ""),
                wages=float(data.get("wages", 0)),
                federal_withholding=float(data.get("federal_withholding", 0)),
                state=data.get("state", ""),
                state_wages=float(data.get("state_wages", 0)),
                state_withholding=float(data.get("state_withholding", 0)),
            )
            self.profile.income.w2s.append(w2)
            # Update payments
            self.profile.payments.federal_withholding = self.profile.income.total_federal_withholding()
            self.profile.payments.state_withholding = self.profile.income.total_state_withholding()

        elif step_id == "self_employment_income":
            se = SelfEmploymentIncome(
                business_name=data.get("business_name", ""),
                gross_income=float(data.get("gross_income", 0)),
                expenses=float(data.get("expenses", 0)),
            )
            self.profile.income.self_employment.append(se)

        elif step_id == "interest_income":
            interest = InterestIncome(
                payer_name=data.get("payer_name", ""),
                amount=float(data.get("amount", 0)),
                is_tax_exempt=bool(data.get("is_tax_exempt", False)),
            )
            self.profile.income.interest.append(interest)

        elif step_id == "dividend_income":
            div = DividendIncome(
                payer_name=data.get("payer_name", ""),
                ordinary_dividends=float(data.get("ordinary_dividends", 0)),
                qualified_dividends=float(data.get("qualified_dividends", 0)),
            )
            self.profile.income.dividends.append(div)

        elif step_id == "capital_gains_income":
            cg = CapitalGain(
                description=data.get("description", ""),
                proceeds=float(data.get("proceeds", 0)),
                cost_basis=float(data.get("cost_basis", 0)),
                is_long_term=bool(data.get("is_long_term", False)),
            )
            self.profile.income.capital_gains.append(cg)

        elif step_id == "retirement_income":
            ret = RetirementIncome(
                source=data.get("source", ""),
                gross_distribution=float(data.get("gross_distribution", 0)),
                taxable_amount=float(data.get("taxable_amount", 0)),
            )
            self.profile.income.retirement.append(ret)

        elif step_id == "rental_income":
            rental = RentalIncome(
                property_description=data.get("property_description", ""),
                gross_rent=float(data.get("gross_rent", 0)),
                expenses=float(data.get("expenses", 0)),
            )
            self.profile.income.rental.append(rental)

        elif step_id == "other_income":
            amount = data.get("amount", 0)
            desc = data.get("description", "")
            if amount:
                self.profile.income.other_income = float(amount)
                self.profile.income.other_income_description = desc

        elif step_id == "adjustments":
            adj = self.profile.adjustments
            if data.get("hsa_contributions"):
                adj.hsa_contributions = float(data["hsa_contributions"])
            if data.get("ira_contributions"):
                adj.ira_contributions = float(data["ira_contributions"])
            if data.get("student_loan_interest"):
                adj.student_loan_interest = float(data["student_loan_interest"])
            if data.get("educator_expenses"):
                adj.educator_expenses = float(data["educator_expenses"])
            if data.get("self_employment_health_insurance"):
                adj.self_employment_health_insurance = float(data["self_employment_health_insurance"])
            if data.get("alimony_paid"):
                adj.alimony_paid = float(data["alimony_paid"])

        elif step_id == "deductions_choice":
            pref = data.get("deduction_preference", "auto")
            if pref == "standard":
                self.profile.use_itemized = False
            elif pref == "itemized":
                self.profile.use_itemized = True
            else:
                self.profile.use_itemized = None  # Auto-optimize

        elif step_id == "itemized_deductions":
            item = self.profile.itemized_deductions
            if data.get("medical_expenses"):
                item.medical_expenses = float(data["medical_expenses"])
            if data.get("state_local_taxes"):
                item.state_local_taxes = float(data["state_local_taxes"])
            if data.get("mortgage_interest"):
                item.mortgage_interest = float(data["mortgage_interest"])
            if data.get("charitable_cash"):
                item.charitable_cash = float(data["charitable_cash"])
            if data.get("charitable_noncash"):
                item.charitable_noncash = float(data["charitable_noncash"])
            if data.get("other_deductions"):
                item.other_deductions = float(data["other_deductions"])

        elif step_id == "payments_withholding":
            if data.get("estimated_federal_payments"):
                self.profile.payments.estimated_federal_payments = float(data["estimated_federal_payments"])
            if data.get("estimated_state_payments"):
                self.profile.payments.estimated_state_payments = float(data["estimated_state_payments"])

    def _process_income_types(self, data: dict):
        """Parse income types from the income_sources step."""
        income_types = data.get("income_types", [])
        if isinstance(income_types, str):
            income_types = [t.strip().lower() for t in income_types.split(",")]
        elif isinstance(income_types, list):
            income_types = [str(t).strip().lower() for t in income_types]

        type_mapping = {
            "w2": "w2", "w-2": "w2", "wages": "w2", "salary": "w2", "employment": "w2",
            "1099-nec": "self_employment", "self-employment": "self_employment",
            "freelance": "self_employment", "self employment": "self_employment",
            "1099-int": "interest", "interest": "interest",
            "1099-div": "dividends", "dividends": "dividends", "dividend": "dividends",
            "1099-b": "capital_gains", "capital gains": "capital_gains",
            "stocks": "capital_gains", "crypto": "capital_gains", "investments": "capital_gains",
            "1099-r": "retirement", "retirement": "retirement", "pension": "retirement",
            "401k": "retirement", "ira": "retirement",
            "rental": "rental", "rent": "rental",
        }

        self._pending_income_types = set()
        for it in income_types:
            for key, mapped in type_mapping.items():
                if key in it:
                    self._pending_income_types.add(mapped)

    def _route_first_income_type(self) -> str:
        """Route to the first pending income type."""
        order = ["w2", "self_employment", "interest", "dividends", "capital_gains", "retirement", "rental"]
        for income_type in order:
            if income_type in self._pending_income_types:
                return self._income_type_to_step(income_type)
        return "other_income"

    def _route_next_income_after(self, current_type: str) -> str:
        """Route to the next income type after the current one is done."""
        order = ["w2", "self_employment", "interest", "dividends", "capital_gains", "retirement", "rental"]
        try:
            idx = order.index(current_type)
        except ValueError:
            return "other_income"

        for income_type in order[idx + 1:]:
            if income_type in self._pending_income_types:
                return self._income_type_to_step(income_type)
        return "other_income"

    def _income_type_to_step(self, income_type: str) -> str:
        mapping = {
            "w2": "w2_income",
            "self_employment": "self_employment_income",
            "interest": "interest_income",
            "dividends": "dividend_income",
            "capital_gains": "capital_gains_income",
            "retirement": "retirement_income",
            "rental": "rental_income",
        }
        return mapping.get(income_type, "other_income")

    def go_back(self) -> str | None:
        """Go back to the previous step. Returns the previous step ID or None."""
        # Simple approach: look at chat history to find the last step transition
        step_order = [
            "welcome", "filing_status", "personal_info", "dependents",
            "income_sources", "w2_income", "w2_more",
            "self_employment_income", "interest_income", "dividend_income",
            "capital_gains_income", "retirement_income", "rental_income",
            "other_income", "adjustments", "deductions_choice", "itemized_deductions",
            "credits", "payments_withholding", "review_summary",
        ]

        try:
            current_idx = step_order.index(self.current_step_id)
            if current_idx > 0:
                prev_step = step_order[current_idx - 1]
                self.current_step_id = prev_step
                self._update_session_step(prev_step)
                return prev_step
        except ValueError:
            pass

        return None

    def get_status_display(self) -> str:
        """Get a formatted status string for display."""
        progress = self.get_progress()
        profile_summary = self.profile.summary()

        lines = [
            f"Progress: {progress['progress_pct']}% — Currently on: {progress['current_step']}",
            f"Category: {progress['current_category']}",
            "",
            "Collected so far:",
            f"  Filing status: {profile_summary['filing_status'] or 'not set'}",
            f"  State: {profile_summary['state'] or 'not set'}",
            f"  Dependents: {profile_summary['dependents']}",
        ]

        if profile_summary["total_wages"]:
            lines.append(f"  Wages: ${profile_summary['total_wages']:,.2f}")
        if profile_summary["total_self_employment"]:
            lines.append(f"  Self-employment: ${profile_summary['total_self_employment']:,.2f}")
        if profile_summary["total_interest"]:
            lines.append(f"  Interest: ${profile_summary['total_interest']:,.2f}")
        if profile_summary["total_dividends"]:
            lines.append(f"  Dividends: ${profile_summary['total_dividends']:,.2f}")
        if profile_summary["total_capital_gains"]:
            lines.append(f"  Capital gains: ${profile_summary['total_capital_gains']:,.2f}")

        return "\n".join(lines)
