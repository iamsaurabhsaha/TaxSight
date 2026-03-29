"""Tesseract OCR wrapper for tax document text extraction."""

from pathlib import Path
from typing import Optional

from PIL import Image


def extract_text(file_path: str | Path) -> Optional[str]:
    """Extract text from an image or PDF using Tesseract OCR.

    Returns the raw text string, or None if extraction fails.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    try:
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "pytesseract is required for OCR. Install with: pip install pytesseract\n"
            "Also install Tesseract: brew install tesseract"
        )

    try:
        if suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif", ".webp"):
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text.strip() if text else None

        elif suffix == ".pdf":
            # Convert PDF pages to images, then OCR
            try:
                from pdf2image import convert_from_path

                images = convert_from_path(file_path)
                texts = []
                for img in images:
                    page_text = pytesseract.image_to_string(img)
                    if page_text:
                        texts.append(page_text.strip())
                return "\n\n".join(texts) if texts else None
            except ImportError:
                raise RuntimeError(
                    "pdf2image is required for PDF OCR. Install with: pip install pdf2image\n"
                    "Also install poppler: brew install poppler"
                )

        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    except Exception as e:
        if "TesseractNotFoundError" in type(e).__name__ or "tesseract" in str(e).lower():
            raise RuntimeError(
                "Tesseract is not installed. Install with: brew install tesseract"
            )
        raise


def is_tesseract_available() -> bool:
    """Check if Tesseract OCR is installed and available."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
