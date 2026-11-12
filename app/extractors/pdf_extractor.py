"""Independent PDF extractor powered by PyMuPDF (fitz) with OCR readiness."""

from __future__ import annotations

import time
from pathlib import Path
from statistics import median
from typing import Any

import fitz

from app.core.exceptions import (
    CorruptedDocumentError,
    EmptyDocumentError,
    ExtractionError,
    PasswordProtectedDocumentError,
)
from app.extractors.base import (
    BaseExtractor,
    ExtractedContent,
    ExtractionContext,
    RawBlock,
    RawOcrSignal,
    RawPageReference,
    RawStatistics,
)
from app.extractors.ocr_engine import OcrEngine
from app.schemas.common import BlockType, DocumentFormat, OcrStatus
from app.utils.file_utils import sanitize_error_reason
from app.utils.text_utils import count_lines, count_words


class PdfExtractor(BaseExtractor):
    """Extracts page-ordered blocks, page references, metadata, and OCR signals from PDFs."""

    name = "pymupdf_pdf_extractor"
    supported_format = DocumentFormat.PDF
    supported_extensions = (".pdf",)
    supported_mime_types = ("application/pdf",)
    supports_tables = False
    ocr_fallback_ready = True

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        self._ocr_engine = ocr_engine

    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Extract text page by page, preserve page numbers, detect scans/encryption, and record warnings."""
        started = time.perf_counter()
        self.validate_file(file_path, context)

        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            raise CorruptedDocumentError(
                f"Failed to open PDF document '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc

        try:
            # Handle password-protected / encrypted PDFs explicitly
            if doc.is_encrypted or doc.needs_pass:
                authenticated = False
                try:
                    authenticated = bool(doc.authenticate(""))
                except Exception:
                    authenticated = False
                if not authenticated or doc.needs_pass:
                    raise PasswordProtectedDocumentError(
                        f"PDF document '{file_path.name}' is password-protected and cannot be read without decryption.",
                        details={"filename": file_path.name, "is_encrypted": True},
                    )

            if doc.page_count == 0:
                raise EmptyDocumentError(
                    f"PDF document '{file_path.name}' contains zero pages."
                )

            raw_metadata = doc.metadata or {}
            blocks: list[RawBlock] = []
            pages: list[RawPageReference] = []
            empty_pages: list[int] = []
            pages_requiring_ocr: list[int] = []
            ocr_notes: list[str] = []
            ocr_applied = False
            warnings: list[str] = []
            failed_pages = 0

            cached_page_dicts: dict[int, dict[str, Any]] = {}
            baseline_font_size = self._estimate_body_font_size(doc, cached_page_dicts)

            for page_idx in range(doc.page_count):
                page_number = page_idx + 1
                try:
                    page = doc.load_page(page_idx)
                    page_blocks = self._extract_page_blocks(
                        page=page,
                        page_number=page_number,
                        baseline_font_size=baseline_font_size,
                        cached_page_dict=cached_page_dicts.pop(page_idx, None),
                    )
                    has_images = len(page.get_images(full=False)) > 0
                except Exception as page_exc:
                    failed_pages += 1
                    warnings.append(
                        f"Failed to extract page {page_number}: {sanitize_error_reason(page_exc, replacement_name=file_path.name)}"
                    )
                    pages.append(
                        RawPageReference(
                            page_number=page_number,
                            is_empty=True,
                            potentially_scanned=False,
                            has_images=False,
                        )
                    )
                    empty_pages.append(page_number)
                    continue

                extracted_chars = sum(len(b.text.strip()) for b in page_blocks)
                is_empty = extracted_chars == 0
                if is_empty:
                    empty_pages.append(page_number)
                    warnings.append(f"Page {page_number} contains no selectable text.")

                potentially_scanned = (
                    extracted_chars < context.pdf_min_text_chars_per_page
                    or (has_images and extracted_chars < context.pdf_min_text_chars_per_page * 2)
                )

                page_ocr_applied = False
                if potentially_scanned:
                    pages_requiring_ocr.append(page_number)
                    if not is_empty:
                        warnings.append(
                            f"Page {page_number} has low selectable text density ({extracted_chars} chars) and may be scanned."
                        )
                    ocr_blocks = self._try_ocr_page(
                        page=page,
                        page_number=page_number,
                        context=context,
                        notes=ocr_notes,
                    )
                    if ocr_blocks:
                        ocr_applied = True
                        page_ocr_applied = True
                        page_blocks.extend(ocr_blocks)

                page_text = "\n".join(b.text for b in page_blocks if b.text.strip())
                pages.append(
                    RawPageReference(
                        page_number=page_number,
                        char_count=len(page_text),
                        word_count=count_words(page_text),
                        block_count=len(page_blocks),
                        is_empty=len(page_text.strip()) == 0,
                        potentially_scanned=potentially_scanned,
                        has_images=has_images,
                        ocr_applied=page_ocr_applied,
                    )
                )
                blocks.extend(page_blocks)

            if failed_pages == doc.page_count:
                raise ExtractionError(
                    f"All pages in PDF '{file_path.name}' failed extraction.",
                    details={"page_count": doc.page_count, "warnings": warnings},
                )

            ocr_status = self._resolve_ocr_status(
                pages_requiring_ocr=pages_requiring_ocr,
                ocr_enabled=context.ocr_enabled,
                ocr_applied=ocr_applied,
            )

            non_empty_blocks = [b for b in blocks if b.text.strip()]
            if not non_empty_blocks:
                if pages_requiring_ocr and not context.ocr_enabled:
                    warnings.append(
                        "PDF contains no selectable text; OCR is required to extract scanned pages."
                    )
                    blocks.append(
                        RawBlock(
                            type=BlockType.PARAGRAPH,
                            text="",
                            page_number=1,
                            metadata={"ocr_pending": True},
                        )
                    )
                else:
                    raise EmptyDocumentError(
                        f"PDF document '{file_path.name}' yielded no extractable text."
                    )

            custom_props: dict[str, Any] = {}
            for key in ("subject", "keywords", "creator", "producer", "format", "encryption"):
                value = raw_metadata.get(key)
                if value:
                    custom_props[key] = value
            if empty_pages:
                custom_props["empty_pages"] = empty_pages

            raw_text = "\n\n".join(b.text for b in blocks if b.text.strip())
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

            return ExtractedContent(
                extractor_name=self.name,
                format=self.supported_format,
                raw_text=raw_text,
                blocks=blocks,
                pages=pages,
                title=raw_metadata.get("title") or None,
                author=raw_metadata.get("author") or None,
                created_at=raw_metadata.get("creationDate") or None,
                modified_at=raw_metadata.get("modDate") or None,
                page_count=doc.page_count,
                encoding="utf-8",
                custom_properties=custom_props,
                ocr_signal=RawOcrSignal(
                    status=ocr_status,
                    ocr_enabled=context.ocr_enabled,
                    ocr_applied=ocr_applied,
                    ocr_engine=(
                        self._ocr_engine.engine_name
                        if self._ocr_engine
                        else context.ocr_engine_name
                    ),
                    pages_requiring_ocr=pages_requiring_ocr,
                    empty_pages=empty_pages,
                    notes=ocr_notes,
                ),
                statistics=RawStatistics(
                    extraction_time_ms=elapsed_ms,
                    char_count=len(raw_text),
                    word_count=count_words(raw_text),
                    line_count=count_lines(raw_text),
                    block_count=len(blocks),
                    table_count=0,
                    page_count=doc.page_count,
                    empty_page_count=len(empty_pages),
                    scanned_page_count=len(pages_requiring_ocr),
                ),
                warnings=warnings,
            )
        except (
            PasswordProtectedDocumentError,
            EmptyDocumentError,
            CorruptedDocumentError,
            ExtractionError,
        ):
            raise
        except Exception as exc:
            raise ExtractionError(
                f"Unexpected error while extracting PDF '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc
        finally:
            doc.close()

    def _estimate_body_font_size(
        self,
        doc: fitz.Document,
        cached_page_dicts: dict[int, dict[str, Any]],
    ) -> float:
        """Estimate median body font size across up to the first 5 pages and cache dicts."""
        sizes: list[float] = []
        sample_pages = min(doc.page_count, 5)
        for idx in range(sample_pages):
            try:
                page_dict = doc.load_page(idx).get_text("dict")
                cached_page_dicts[idx] = page_dict
            except Exception:
                continue
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = str(span.get("text", "")).strip()
                        size = float(span.get("size", 0.0))
                        if text and size > 0:
                            sizes.append(size)
        return median(sizes) if sizes else 11.0

    def _extract_page_blocks(
        self,
        *,
        page: fitz.Page,
        page_number: int,
        baseline_font_size: float,
        cached_page_dict: dict[str, Any] | None = None,
    ) -> list[RawBlock]:
        """Extract ordered text blocks from a PDF page with font-based heading heuristics."""
        page_dict = cached_page_dict if cached_page_dict is not None else page.get_text("dict")
        extracted: list[RawBlock] = []

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            line_texts: list[str] = []
            span_sizes: list[float] = []
            is_bold = False

            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_buf = "".join(str(span.get("text", "")) for span in spans).strip()
                if line_buf:
                    line_texts.append(line_buf)
                for span in spans:
                    if str(span.get("text", "")).strip():
                        span_sizes.append(float(span.get("size", baseline_font_size)))
                        flags = int(span.get("flags", 0))
                        if flags & 16:
                            is_bold = True

            combined = "\n".join(line_texts).strip()
            if not combined:
                continue

            avg_size = sum(span_sizes) / len(span_sizes) if span_sizes else baseline_font_size
            block_type = BlockType.PARAGRAPH
            level: int | None = None

            if (
                len(combined) <= 140
                and "\n" not in combined
                and (
                    avg_size >= baseline_font_size * 1.25
                    or (is_bold and avg_size >= baseline_font_size * 1.1)
                )
            ):
                block_type = BlockType.HEADING
                if avg_size >= baseline_font_size * 1.7:
                    level = 1
                elif avg_size >= baseline_font_size * 1.4:
                    level = 2
                else:
                    level = 3

            extracted.append(
                RawBlock(
                    type=block_type,
                    text=combined,
                    level=level,
                    page_number=page_number,
                    metadata={
                        "avg_font_size": round(avg_size, 2),
                        "bbox": block.get("bbox"),
                    },
                )
            )

        return extracted

    def _try_ocr_page(
        self,
        *,
        page: fitz.Page,
        page_number: int,
        context: ExtractionContext,
        notes: list[str],
    ) -> list[RawBlock]:
        """Invoke pluggable OCR engine on a low-text page if enabled and available."""
        if not context.ocr_enabled:
            return []
        if self._ocr_engine is None or not self._ocr_engine.is_available():
            notes.append(
                f"Page {page_number} flagged for OCR, but OCR engine '{context.ocr_engine_name}' is unavailable."
            )
            return []

        try:
            pixmap = page.get_pixmap(dpi=200)
            ocr_result = self._ocr_engine.extract_text_from_image_bytes(
                pixmap.tobytes("png"),
                language=context.tesseract_lang,
            )
        except Exception as exc:
            notes.append(f"OCR failed on page {page_number}: {exc}")
            return []

        text = ocr_result.text.strip()
        if not text:
            notes.append(f"OCR returned empty text for page {page_number}.")
            return []

        return [
            RawBlock(
                type=BlockType.PARAGRAPH,
                text=text,
                page_number=page_number,
                metadata={"source": "ocr", "ocr_engine": ocr_result.engine},
            )
        ]

    @staticmethod
    def _resolve_ocr_status(
        *,
        pages_requiring_ocr: list[int],
        ocr_enabled: bool,
        ocr_applied: bool,
    ) -> OcrStatus:
        if not pages_requiring_ocr:
            return OcrStatus.NOT_NEEDED
        if ocr_applied:
            return OcrStatus.APPLIED
        if not ocr_enabled:
            return OcrStatus.DEFERRED_DISABLED
        return OcrStatus.UNAVAILABLE
