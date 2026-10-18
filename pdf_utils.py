"""PDF utilities – extract text from uploaded resume bytes."""
import re

MAX_PDF_BYTES = 2 * 1024 * 1024   # 2 MB
MAX_RESUME_CHARS = 8_000


def extract_text(pdf_bytes: bytes) -> str:
    """Return cleaned text from a PDF byte string.

    Raises ValueError with a user-friendly message on any problem.
    """
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF is larger than 2 MB. Please compress it and try again.")

    try:
        import pymupdf as fitz  # PyMuPDF ≥ 1.24 (replaces deprecated `import fitz`)
    except ImportError:
        try:
            import fitz  # noqa: F401 – older PyMuPDF
        except ImportError:
            raise RuntimeError("PyMuPDF is not installed.")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        raise ValueError("Could not open the PDF. Make sure it's a valid PDF file.")

    if doc.page_count == 0:
        raise ValueError("The PDF has no pages.")

    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()

    text = "\n".join(parts)
    text = _clean(text)

    if not text.strip():
        raise ValueError("Could not extract any text from your PDF. Is it a scanned image? Please use a text-based PDF.")

    if len(text) > MAX_RESUME_CHARS:
        text = text[:MAX_RESUME_CHARS]

    return text


def _clean(text: str) -> str:
    """Remove excessive whitespace while preserving structure."""
    # Collapse 3+ blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing whitespace per line
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()
