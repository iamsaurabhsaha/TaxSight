"""LLM vision extraction — use multimodal models to parse tax documents."""

import base64
import json
from pathlib import Path

from ai_tax_prep.documents.schemas import DOC_TYPE_NAMES, DOC_TYPE_SCHEMAS
from ai_tax_prep.llm.client import LLMClient

VISION_EXTRACTION_PROMPT = """\
You are a tax document data extractor. Analyze this image of a {doc_type_name} \
and extract all relevant fields.

Return a JSON object with these fields:
{schema_fields}

RULES:
- Extract ONLY what is clearly visible in the document.
- Use 0.0 for numeric fields that are blank or unreadable.
- Use "" for text fields that are blank or unreadable.
- Do NOT guess or fabricate any values.
- Return valid JSON only, no explanations.
"""

TEXT_EXTRACTION_PROMPT = """\
You are a tax document data extractor. Analyze this {doc_type_name} text \
and extract all relevant fields.

Return a JSON object with these fields:
{schema_fields}

RULES:
- Extract ONLY what is explicitly stated in the text.
- Use 0.0 for numeric fields not found.
- Use "" for text fields not found.
- Do NOT guess or fabricate any values.
- Return valid JSON only, no explanations.

Document text:
{document_text}
"""

CLASSIFY_PROMPT = """\
Look at this tax document and identify what type of document it is.

Return a JSON object with:
- "doc_type": one of: "w2", "1099_nec", "1099_int", "1099_div", "1099_b", "1099_r", "1098_e", "other"
- "confidence": a number from 0.0 to 1.0 indicating how confident you are

Return valid JSON only.
"""

CONSOLIDATED_EXTRACTION_PROMPT = """\
This is a consolidated tax document containing multiple 1099 forms. \
Extract ALL tax data from ALL sections.

Return a JSON object with these keys (use 0.0 if a section is not present or value is zero):
- "has_1099_b": true/false
- "proceeds": total proceeds from 1099-B
- "cost_basis": total cost basis from 1099-B
- "net_gain_loss": net gain or loss from 1099-B
- "has_1099_div": true/false
- "ordinary_dividends": from 1099-DIV box 1a
- "qualified_dividends": from 1099-DIV box 1b
- "has_1099_int": true/false
- "interest_income": from 1099-INT box 1
- "tax_exempt_interest": from 1099-INT box 8
- "has_1099_misc": true/false
- "other_income": from 1099-MISC box 3
- "federal_withholding": total federal tax withheld across all sections
- "payer_name": name of the brokerage/institution

Return valid JSON only. Extract ONLY what is explicitly in the document.

Document text:
{document_text}
"""

CLASSIFY_TEXT_PROMPT = """\
Analyze this tax document text and identify what type of document it is.

If this is a CONSOLIDATED statement containing multiple 1099 forms (1099-B, 1099-DIV, 1099-INT, etc.), \
return doc_type as "consolidated_1099".

Return a JSON object with:
- "doc_type": one of: "w2", "1099_nec", "1099_int", "1099_div", "1099_b", "1099_r", "1098_e", "consolidated_1099", "other"
- "confidence": a number from 0.0 to 1.0 indicating how confident you are

Return valid JSON only.

Document text:
{document_text}
"""


def classify_document(file_path: str | Path, llm: LLMClient | None = None) -> dict:
    """Use LLM to classify a tax document type."""
    llm = llm or LLMClient()
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _classify_from_pdf(file_path, llm)
    return _classify_from_image(file_path, llm)


def extract_with_vision(
    file_path: str | Path,
    doc_type: str,
    llm: LLMClient | None = None,
) -> dict:
    """Use LLM to extract structured data from a tax document."""
    llm = llm or LLMClient()
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if doc_type == "consolidated_1099":
        return extract_consolidated_1099(file_path, llm)

    if suffix == ".pdf":
        return _extract_from_pdf(file_path, doc_type, llm)
    return _extract_from_image(file_path, doc_type, llm)


# --- PDF handling (text-based) ---

def _read_pdf_text(file_path: Path) -> str:
    """Extract text from a PDF file."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text.strip()
    except ImportError:
        pass

    # Fallback: try pdfplumber
    try:
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text.strip()
    except ImportError:
        pass

    # Fallback: basic binary read won't work for PDFs
    # Try using the LLM with just the filename info
    return ""


def _classify_from_pdf(file_path: Path, llm: LLMClient) -> dict:
    """Classify a PDF document using extracted text."""
    text = _read_pdf_text(file_path)
    if not text:
        # Guess from filename
        return _classify_from_filename(file_path)

    prompt = CLASSIFY_TEXT_PROMPT.format(document_text=text[:3000])
    messages = [{"role": "user", "content": prompt}]

    try:
        result = llm.chat_json(messages)
        return {
            "doc_type": result.get("doc_type", "other"),
            "confidence": float(result.get("confidence", 0.5)),
        }
    except Exception:
        return _classify_from_filename(file_path)


def extract_consolidated_1099(file_path: str | Path, llm: LLMClient | None = None) -> dict:
    """Extract all sections from a consolidated 1099 document."""
    llm = llm or LLMClient()
    file_path = Path(file_path)
    text = _read_pdf_text(file_path)
    if not text:
        return {"extracted_data": {}, "confidence": 0.0}

    prompt = CONSOLIDATED_EXTRACTION_PROMPT.format(document_text=text[:5000])
    messages = [{"role": "user", "content": prompt}]

    try:
        result = llm.chat_json(messages)
        return {"extracted_data": result, "confidence": 0.85}
    except Exception as e:
        return {"extracted_data": {}, "confidence": 0.0, "error": str(e)}


def _extract_from_pdf(file_path: Path, doc_type: str, llm: LLMClient) -> dict:
    """Extract data from a PDF using text extraction + LLM."""
    text = _read_pdf_text(file_path)
    if not text:
        return {"extracted_data": {}, "confidence": 0.0, "error": "Could not read PDF text. Install PyMuPDF: pip install pymupdf"}

    schema_class = DOC_TYPE_SCHEMAS.get(doc_type)
    doc_type_name = DOC_TYPE_NAMES.get(doc_type, doc_type)

    if schema_class:
        schema_fields = json.dumps(
            {k: v.get("description", k) for k, v in schema_class.model_json_schema().get("properties", {}).items()},
            indent=2,
        )
    else:
        schema_fields = "Extract all visible fields as key-value pairs."

    prompt = TEXT_EXTRACTION_PROMPT.format(
        doc_type_name=doc_type_name,
        schema_fields=schema_fields,
        document_text=text[:4000],
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        result = llm.chat_json(messages)

        confidence = 0.80
        if schema_class:
            try:
                validated = schema_class.model_validate(result)
                result = validated.model_dump()
                confidence = 0.90
            except Exception:
                confidence = 0.60

        return {"extracted_data": result, "confidence": confidence}
    except Exception as e:
        return {"extracted_data": {}, "confidence": 0.0, "error": str(e)}


# --- Image handling (vision-based) ---

def _classify_from_image(file_path: Path, llm: LLMClient) -> dict:
    """Classify an image document using LLM vision."""
    image_data = _encode_image(file_path)
    media_type = _get_media_type(file_path.suffix.lower())

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                {"type": "text", "text": CLASSIFY_PROMPT},
            ],
        }
    ]

    try:
        result = llm.chat_json(messages)
        return {
            "doc_type": result.get("doc_type", "other"),
            "confidence": float(result.get("confidence", 0.5)),
        }
    except Exception:
        return _classify_from_filename(file_path)


def _extract_from_image(file_path: Path, doc_type: str, llm: LLMClient) -> dict:
    """Extract data from an image using LLM vision."""
    image_data = _encode_image(file_path)
    media_type = _get_media_type(file_path.suffix.lower())

    schema_class = DOC_TYPE_SCHEMAS.get(doc_type)
    doc_type_name = DOC_TYPE_NAMES.get(doc_type, doc_type)

    if schema_class:
        schema_fields = json.dumps(
            {k: v.get("description", k) for k, v in schema_class.model_json_schema().get("properties", {}).items()},
            indent=2,
        )
    else:
        schema_fields = "Extract all visible fields as key-value pairs."

    prompt = VISION_EXTRACTION_PROMPT.format(
        doc_type_name=doc_type_name,
        schema_fields=schema_fields,
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    try:
        result = llm.chat_json(messages)

        confidence = 0.85
        if schema_class:
            try:
                validated = schema_class.model_validate(result)
                result = validated.model_dump()
                confidence = 0.9
            except Exception:
                confidence = 0.6

        return {"extracted_data": result, "confidence": confidence}
    except Exception as e:
        return {"extracted_data": {}, "confidence": 0.0, "error": str(e)}


# --- Helpers ---

def _classify_from_filename(file_path: Path) -> dict:
    """Best-effort classification from filename."""
    name = file_path.name.lower()
    if "w2" in name or "w-2" in name:
        return {"doc_type": "w2", "confidence": 0.7}
    if "1099-nec" in name or "1099_nec" in name or "1099nec" in name:
        return {"doc_type": "1099_nec", "confidence": 0.7}
    if "1099-int" in name or "1099_int" in name:
        return {"doc_type": "1099_int", "confidence": 0.7}
    if "1099-div" in name or "1099_div" in name:
        return {"doc_type": "1099_div", "confidence": 0.7}
    if "1099-b" in name or "1099_b" in name:
        return {"doc_type": "1099_b", "confidence": 0.7}
    if "1099-r" in name or "1099_r" in name:
        return {"doc_type": "1099_r", "confidence": 0.7}
    if "1099" in name:
        return {"doc_type": "1099_nec", "confidence": 0.4}
    if "1098" in name and ("e" in name.lower().split("1098")[-1][:3]):
        return {"doc_type": "1098_e", "confidence": 0.7}
    if "1098" in name:
        return {"doc_type": "other", "confidence": 0.5}
    return {"doc_type": "other", "confidence": 0.3}


def _encode_image(file_path: str | Path) -> str:
    """Read and base64-encode an image file."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_media_type(suffix: str) -> str:
    """Get MIME type from file extension."""
    types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return types.get(suffix, "image/png")
