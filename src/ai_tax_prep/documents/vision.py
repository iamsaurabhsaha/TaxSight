"""LLM vision extraction — use multimodal models to parse tax documents."""

import base64
import json
from pathlib import Path
from typing import Optional

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

CLASSIFY_PROMPT = """\
Look at this tax document image and identify what type of document it is.

Return a JSON object with:
- "doc_type": one of: "w2", "1099_nec", "1099_int", "1099_div", "1099_b", "1099_r", "other"
- "confidence": a number from 0.0 to 1.0 indicating how confident you are

Return valid JSON only.
"""


def classify_document(file_path: str | Path, llm: Optional[LLMClient] = None) -> dict:
    """Use LLM vision to classify a tax document type.

    Returns: {"doc_type": str, "confidence": float}
    """
    llm = llm or LLMClient()
    image_data = _encode_image(file_path)
    file_ext = Path(file_path).suffix.lower()
    media_type = _get_media_type(file_ext)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{image_data}",
                    },
                },
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
        return {"doc_type": "other", "confidence": 0.0}


def extract_with_vision(
    file_path: str | Path,
    doc_type: str,
    llm: Optional[LLMClient] = None,
) -> dict:
    """Use LLM vision to extract structured data from a tax document.

    Returns: {"extracted_data": dict, "confidence": float}
    """
    llm = llm or LLMClient()
    image_data = _encode_image(file_path)
    file_ext = Path(file_path).suffix.lower()
    media_type = _get_media_type(file_ext)

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
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{image_data}",
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

    try:
        result = llm.chat_json(messages)

        # Validate against schema if available
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
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
        ".pdf": "application/pdf",
    }
    return types.get(suffix, "image/png")
