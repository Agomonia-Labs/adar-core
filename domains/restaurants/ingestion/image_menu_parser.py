"""Image menu OCR extraction."""

from __future__ import annotations

from pathlib import Path

from domains.restaurants.ingestion.menu_parser import parse_menu_text


def extract_image_text(path: Path) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Image menu OCR requires pillow and pytesseract. Run: "
            "pip install pillow pytesseract. The system also needs tesseract installed."
        ) from exc

    return pytesseract.image_to_string(Image.open(path))


def parse_image_menu(path: Path, source_url: str | None = None) -> list[dict]:
    source = source_url or str(path)
    text = extract_image_text(path)
    return parse_menu_text(text, source_url=source, source_type="image_ocr")
