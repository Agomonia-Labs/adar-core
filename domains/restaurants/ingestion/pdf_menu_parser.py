"""PDF menu extraction."""

from __future__ import annotations

from pathlib import Path

from domains.restaurants.ingestion.menu_parser import parse_menu_text


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF menu ingestion requires pypdf. Run: pip install pypdf") from exc

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def parse_pdf_menu(path: Path, source_url: str | None = None) -> list[dict]:
    source = source_url or str(path)
    text = extract_pdf_text(path)
    return parse_menu_text(text, source_url=source, source_type="pdf")
