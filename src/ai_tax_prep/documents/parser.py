"""Document parser orchestrator — combines OCR + LLM vision, cross-references, scores confidence."""

import json
from pathlib import Path

from ai_tax_prep.core.tax_profile import (
    CapitalGain,
    DividendIncome,
    InterestIncome,
    RetirementIncome,
    SelfEmploymentIncome,
    TaxProfile,
    W2Income,
)
from ai_tax_prep.db.database import get_session_factory, init_db
from ai_tax_prep.db.models import Document
from ai_tax_prep.documents.ocr import extract_text, is_tesseract_available
from ai_tax_prep.documents.vision import classify_document, extract_with_vision
from ai_tax_prep.llm.client import LLMClient


def _safe_float(value) -> float:
    """Safely convert a value to float, returning 0.0 for empty/invalid values."""
    if value is None or value == "" or value == "N/A" or value == "n/a":
        return 0.0
    try:
        # Handle strings like "$1,234.56"
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
            if not value:
                return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class DocumentParser:
    """Orchestrates document parsing: OCR + vision → validate → store → apply to profile."""

    def __init__(self, session_id: str, llm: LLMClient | None = None):
        self.session_id = session_id
        self.llm = llm or LLMClient()
        init_db()
        self._db_factory = get_session_factory()

    def _get_db(self):
        return self._db_factory()

    def parse_document(
        self,
        file_path: str | Path,
        doc_type: str | None = None,
    ) -> dict:
        """Parse a tax document using OCR and/or LLM vision.

        Args:
            file_path: Path to the document image/PDF
            doc_type: Document type (w2, 1099_nec, etc.) or None to auto-detect

        Returns:
            dict with: doc_type, extracted_data, confidence, needs_review, ocr_text
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = {
            "doc_type": doc_type,
            "extracted_data": {},
            "confidence": 0.0,
            "needs_review": True,
            "ocr_text": None,
        }

        # Step 1: OCR (if available)
        if is_tesseract_available():
            try:
                result["ocr_text"] = extract_text(file_path)
            except Exception:
                pass

        # Step 2: Auto-classify if doc_type not provided
        if not doc_type:
            classification = classify_document(file_path, self.llm)
            result["doc_type"] = classification["doc_type"]
            doc_type = classification["doc_type"]

        # Step 3: LLM vision extraction
        vision_result = extract_with_vision(file_path, doc_type, self.llm)
        result["extracted_data"] = vision_result["extracted_data"]
        result["confidence"] = vision_result["confidence"]

        # Step 4: Cross-reference OCR with vision if both available
        if result["ocr_text"] and result["extracted_data"]:
            result["confidence"] = self._cross_reference(
                result["ocr_text"], result["extracted_data"], result["confidence"]
            )

        # Step 5: Set review flag
        result["needs_review"] = result["confidence"] < 0.85

        # Step 6: Save to database
        self._save_document(file_path, result)

        return result

    def _cross_reference(self, ocr_text: str, extracted_data: dict, base_confidence: float) -> float:
        """Cross-reference OCR text with vision extraction to adjust confidence."""
        matches = 0
        checks = 0

        for key, value in extracted_data.items():
            if isinstance(value, (int, float)) and value > 0:
                # Check if the number appears in OCR text
                formatted = f"{value:,.2f}"
                formatted_no_comma = f"{value:.2f}"
                formatted_int = str(int(value))

                checks += 1
                if (formatted in ocr_text or
                    formatted_no_comma in ocr_text or
                    formatted_int in ocr_text):
                    matches += 1
            elif isinstance(value, str) and len(value) > 2:
                checks += 1
                if value.lower() in ocr_text.lower():
                    matches += 1

        if checks == 0:
            return base_confidence

        match_ratio = matches / checks
        # Boost confidence if OCR confirms vision, reduce if not
        if match_ratio > 0.7:
            return min(0.95, base_confidence + 0.05)
        elif match_ratio < 0.3:
            return max(0.3, base_confidence - 0.15)
        return base_confidence

    def _save_document(self, file_path: Path, result: dict):
        """Save parsed document to database."""
        db = self._get_db()
        try:
            doc = Document(
                session_id=self.session_id,
                doc_type=result["doc_type"],
                file_path=str(file_path),
                ocr_text=result.get("ocr_text"),
                extracted_data=json.dumps(result["extracted_data"]),
                confidence_score=result["confidence"],
                needs_review=result["needs_review"],
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            result["document_id"] = doc.id
        finally:
            db.close()

    def apply_to_profile(self, extracted_data: dict, doc_type: str, profile: TaxProfile) -> TaxProfile:
        """Apply extracted document data to a tax profile."""
        if doc_type == "w2":
            wages = _safe_float(extracted_data.get("wages", 0))
            # Skip supplemental W-2s with $0 or near-zero Box 1 wages
            # (e.g., NJ payroll tax W-2s that only have state/local info)
            if wages < 1.0:
                return profile
            w2 = W2Income(
                employer_name=extracted_data.get("employer_name", ""),
                employer_ein=extracted_data.get("employer_ein", ""),
                wages=wages,
                federal_withholding=_safe_float(extracted_data.get("federal_withholding", 0)),
                ss_wages=_safe_float(extracted_data.get("ss_wages", 0)),
                ss_tax=_safe_float(extracted_data.get("ss_tax", 0)),
                medicare_wages=_safe_float(extracted_data.get("medicare_wages", 0)),
                medicare_tax=_safe_float(extracted_data.get("medicare_tax", 0)),
                state=extracted_data.get("state", ""),
                state_wages=_safe_float(extracted_data.get("state_wages", 0)),
                state_withholding=_safe_float(extracted_data.get("state_tax", extracted_data.get("state_withholding", 0))),
            )
            profile.income.w2s.append(w2)
            profile.payments.federal_withholding = profile.income.total_federal_withholding()
            profile.payments.state_withholding = profile.income.total_state_withholding()

        elif doc_type == "1099_nec":
            se = SelfEmploymentIncome(
                business_name=extracted_data.get("payer_name", ""),
                gross_income=_safe_float(extracted_data.get("nonemployee_compensation", 0)),
            )
            profile.income.self_employment.append(se)

        elif doc_type == "1099_int":
            interest = InterestIncome(
                payer_name=extracted_data.get("payer_name", ""),
                amount=_safe_float(extracted_data.get("interest_income", 0)),
                is_tax_exempt=_safe_float(extracted_data.get("tax_exempt_interest", 0)) > 0,
            )
            profile.income.interest.append(interest)

        elif doc_type == "1099_div":
            div = DividendIncome(
                payer_name=extracted_data.get("payer_name", ""),
                ordinary_dividends=_safe_float(extracted_data.get("ordinary_dividends", 0)),
                qualified_dividends=_safe_float(extracted_data.get("qualified_dividends", 0)),
            )
            profile.income.dividends.append(div)

        elif doc_type == "1099_b":
            cg = CapitalGain(
                description=extracted_data.get("description", ""),
                date_acquired=extracted_data.get("date_acquired", ""),
                date_sold=extracted_data.get("date_sold", ""),
                proceeds=_safe_float(extracted_data.get("proceeds", 0)),
                cost_basis=_safe_float(extracted_data.get("cost_basis", 0)),
                is_long_term=bool(extracted_data.get("is_long_term", False)),
            )
            profile.income.capital_gains.append(cg)

        elif doc_type == "1099_r":
            dist_code = str(extracted_data.get("distribution_code", "")).upper().strip()

            # Code P = prior year distribution, skip for current tax year
            if "P" in dist_code:
                return profile

            # Code J = Roth IRA early distribution
            # Generally a return of contributions = $0 taxable
            # Only taxable if earnings are distributed (needs Form 8606)
            if "J" in dist_code:
                taxable = _safe_float(extracted_data.get("taxable_amount", 0))
                # If taxable_amount is 0 or same as gross, likely return of contributions
                gross = _safe_float(extracted_data.get("gross_distribution", 0))
                if taxable == 0 or taxable == gross:
                    taxable = 0  # Assume return of contributions unless user specifies otherwise
                ret = RetirementIncome(
                    source=extracted_data.get("payer_name", ""),
                    gross_distribution=gross,
                    taxable_amount=taxable,
                )
                profile.income.retirement.append(ret)
                return profile

            ret = RetirementIncome(
                source=extracted_data.get("payer_name", ""),
                gross_distribution=_safe_float(extracted_data.get("gross_distribution", 0)),
                taxable_amount=_safe_float(extracted_data.get("taxable_amount", 0)),
            )
            profile.income.retirement.append(ret)

        elif doc_type == "1098_e":
            interest_amount = _safe_float(
                extracted_data.get("student_loan_interest", extracted_data.get("student_loan_interest_received", 0))
            )
            if interest_amount > 0:
                profile.adjustments.student_loan_interest = interest_amount

        return profile

    def get_documents(self) -> list[dict]:
        """Get all documents for this session."""
        db = self._get_db()
        try:
            docs = db.query(Document).filter(Document.session_id == self.session_id).all()
            return [
                {
                    "id": doc.id,
                    "doc_type": doc.doc_type,
                    "file_path": doc.file_path,
                    "confidence": doc.confidence_score,
                    "needs_review": doc.needs_review,
                    "extracted_data": json.loads(doc.extracted_data) if doc.extracted_data else {},
                }
                for doc in docs
            ]
        finally:
            db.close()

    def cross_reference_documents(self, profile: TaxProfile) -> list[str]:
        """Cross-reference all documents and flag inconsistencies."""
        warnings = []
        docs = self.get_documents()

        # Check for common missing documents
        has_w2 = any(d["doc_type"] == "w2" for d in docs)
        has_income = profile.income.total_wages() > 0

        if has_income and not has_w2:
            warnings.append(
                "You reported wage income but haven't uploaded a W-2. "
                "Consider uploading it for more accurate withholding data."
            )

        # Check W-2 consistency
        w2_docs = [d for d in docs if d["doc_type"] == "w2"]
        if len(w2_docs) != len(profile.income.w2s) and len(w2_docs) > 0:
            warnings.append(
                f"You have {len(w2_docs)} W-2 document(s) uploaded but "
                f"{len(profile.income.w2s)} W-2 entries in your profile. "
                "Please verify all W-2s are accounted for."
            )

        # Check for documents needing review
        needs_review = [d for d in docs if d["needs_review"]]
        if needs_review:
            warnings.append(
                f"{len(needs_review)} document(s) have low extraction confidence "
                "and need manual review. Run `tax-prep docs review` to verify."
            )

        # Check withholding consistency across docs
        total_doc_withholding = sum(
            d["extracted_data"].get("federal_withholding", 0)
            for d in docs
            if d["extracted_data"]
        )
        profile_withholding = profile.payments.federal_withholding
        if total_doc_withholding > 0 and profile_withholding > 0:
            diff = abs(total_doc_withholding - profile_withholding)
            if diff > 100:
                warnings.append(
                    f"Federal withholding from documents (${total_doc_withholding:,.2f}) "
                    f"doesn't match profile (${profile_withholding:,.2f}). "
                    "Please verify your withholding amounts."
                )

        return warnings
