"""OCR engine protocol and Tesseract adapter hook for future scanned-PDF support."""

from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.exceptions import OcrNotConfiguredError


@dataclass(slots=True)
class OcrResult:
    """Text and confidence output returned by an OCR pass on a single page image."""

    text: str
    confidence: float | None = None
    engine: str = "tesseract"


@runtime_checkable
class OcrEngine(Protocol):
    """Protocol for pluggable OCR engines (e.g., Tesseract, PaddleOCR)."""

    engine_name: str

    def is_available(self) -> bool:
        """Return True if required runtime libraries and binaries are installed."""
        ...

    def extract_text_from_image_bytes(
        self, image_bytes: bytes, *, language: str = "eng"
    ) -> OcrResult:
        """Run OCR over rasterized page image bytes and return extracted text."""
        ...


class TesseractOcrHook:
    """Tesseract OCR adapter prepared for future scanned PDF/image extraction.

    When ``pytesseract``, ``Pillow``, and the ``tesseract`` CLI binary are
    installed and ``MEMORIA_OCR_ENABLED=true``, this adapter executes OCR on
    low-text-density PDF pages. Otherwise it safely reports unavailability so
    the PDF extractor can emit structured ``pages_requiring_ocr`` signals.
    """

    engine_name: str = "tesseract"

    def __init__(self, tesseract_cmd: str = "tesseract") -> None:
        self._tesseract_cmd = tesseract_cmd

    def is_available(self) -> bool:
        """Check whether pytesseract, PIL, and the tesseract binary exist."""
        has_binary = shutil.which(self._tesseract_cmd) is not None
        if not has_binary:
            return False
        try:
            importlib.import_module("pytesseract")
            importlib.import_module("PIL.Image")
            return True
        except ImportError:
            return False

    def extract_text_from_image_bytes(
        self, image_bytes: bytes, *, language: str = "eng"
    ) -> OcrResult:
        """Run Tesseract OCR over PNG/JPEG bytes when dependencies are installed."""
        if not self.is_available():
            raise OcrNotConfiguredError(
                "Tesseract OCR is not installed or unavailable in this environment.",
                details={"tesseract_cmd": self._tesseract_cmd, "language": language},
            )

        import io

        pytesseract = importlib.import_module("pytesseract")
        pil_image = importlib.import_module("PIL.Image")
        pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        with pil_image.open(io.BytesIO(image_bytes)) as img:
            text = pytesseract.image_to_string(img, lang=language)

        return OcrResult(text=text or "", engine=self.engine_name)
