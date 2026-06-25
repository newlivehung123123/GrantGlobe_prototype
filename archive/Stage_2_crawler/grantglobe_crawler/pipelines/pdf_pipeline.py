"""
PDFExtractionPipeline — text extraction from downloaded PDF binaries.

Priority: 400 (runs BEFORE ContentStoragePipeline at 500).

Only processes items where ``item['is_pdf'] is True``.  All other items
pass through immediately.

Extraction sequence (spec §2.4):

  Step 1  PyMuPDF (fitz)   — primary text extraction, page by page.
  Step 2  pdfplumber       — secondary pass for table-structured content.
  Step 3  OCR threshold    — if ≥ PDF_OCR_THRESHOLD of pages yield
                             < PDF_OCR_MIN_CHARS_PER_PAGE characters,
                             route those failing pages to OCR.
  Step 4  pdf2image        — convert only failed pages to PNG images,
                             in batches of PDF_OCR_PAGE_BATCH_SIZE.
  Step 5  pytesseract      — OCR on each failed-page PNG.
  Step 6  lingua-py        — language detection on assembled text.
  Step 7  Header/footer stripping — lines appearing on ≥
                             PDF_FOOTER_REPEAT_THRESHOLD fraction of pages.
  Step 8  Write .txt file  — raw_cache/{domain}/{date}/pdfs/{sha256}.txt
                             Sets item['char_count'], item['language'],
                             item['content_sha256'].

All library imports (fitz, pdfplumber, pdf2image, pytesseract, lingua)
are wrapped in try/except ImportError.  If a library is absent its step
is skipped with a logged warning; the pipeline never raises.

Password-protected PDFs are caught explicitly and recorded as
``extraction_method: encrypted`` per spec §2.4 Known Limitations.

Spec ref: §2.4 PDF Extraction Pipeline.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scrapy import signals

from grantglobe_crawler.items import GrantItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional library imports
# ---------------------------------------------------------------------------

try:
    import fitz as _fitz  # PyMuPDF

    _FITZ_AVAILABLE = True
except ImportError:
    _fitz = None  # type: ignore[assignment]
    _FITZ_AVAILABLE = False
    logger.warning("PyMuPDF (fitz) not installed — PDF text extraction disabled.")

try:
    import pdfplumber as _pdfplumber

    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _pdfplumber = None  # type: ignore[assignment]
    _PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not installed — table extraction disabled.")

try:
    from pdf2image import convert_from_bytes as _convert_from_bytes

    _PDF2IMAGE_AVAILABLE = True
except ImportError:
    _convert_from_bytes = None  # type: ignore[assignment]
    _PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed — OCR conversion disabled.")

try:
    import pytesseract as _pytesseract

    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _pytesseract = None  # type: ignore[assignment]
    _PYTESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed — OCR disabled.")

try:
    from lingua import Language as _Language
    from lingua import LanguageDetectorBuilder as _LanguageDetectorBuilder

    _LINGUA_AVAILABLE = True
except ImportError:
    _Language = None  # type: ignore[assignment]
    _LanguageDetectorBuilder = None  # type: ignore[assignment]
    _LINGUA_AVAILABLE = False
    logger.warning("lingua-language-detector not installed — language detection disabled.")


class PDFExtractionPipeline:
    """
    Scrapy item pipeline for PDF text extraction.

    Sets the following item fields for PDF items before passing them on:
      ``item['content_sha256']``  — SHA-256 of raw PDF bytes
      ``item['char_count']``      — character count of extracted text
      ``item['language']``        — ISO 639-1 code or None
    Writes ``{content_sha256}.txt`` to the dated pdfs/ directory.
    """

    def __init__(
        self,
        raw_cache_dir: Path,
        ocr_threshold: float,
        ocr_min_chars: int,
        ocr_dpi: int,
        ocr_page_batch_size: int,
        ocr_languages: list[str],
        footer_repeat_threshold: float,
        lingua_languages: list[str],
    ) -> None:
        self._raw_cache_dir = raw_cache_dir
        self._ocr_threshold = ocr_threshold
        self._ocr_min_chars = ocr_min_chars
        self._ocr_dpi = ocr_dpi
        self._ocr_page_batch_size = ocr_page_batch_size
        self._ocr_languages = ocr_languages
        self._footer_repeat_threshold = footer_repeat_threshold
        self._lingua_languages = lingua_languages
        self._language_detector = None  # built lazily on first use

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        instance = cls(
            raw_cache_dir=Path(s.get("RAW_CACHE_DIR", "raw_cache")),
            ocr_threshold=s.getfloat("PDF_OCR_THRESHOLD", 0.40),
            ocr_min_chars=s.getint("PDF_OCR_MIN_CHARS_PER_PAGE", 100),
            ocr_dpi=s.getint("PDF_OCR_DPI", 300),
            ocr_page_batch_size=s.getint("PDF_OCR_PAGE_BATCH_SIZE", 10),
            ocr_languages=s.getlist("PDF_OCR_LANGUAGES", ["eng", "fra", "spa", "ara"]),
            footer_repeat_threshold=s.getfloat("PDF_FOOTER_REPEAT_THRESHOLD", 0.70),
            lingua_languages=s.getlist(
                "LINGUA_LANGUAGES",
                ["ENGLISH", "FRENCH", "SPANISH", "ARABIC", "PORTUGUESE"],
            ),
        )
        crawler.signals.connect(instance.spider_opened, signal=signals.spider_opened)
        return instance

    def spider_opened(self, spider) -> None:
        self._raw_cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Scrapy pipeline interface
    # ------------------------------------------------------------------

    def process_item(self, item, spider):
        """
        Extract text from PDF items.  Pass all non-PDF items through.
        """
        if not isinstance(item, GrantItem) or not item.get("is_pdf"):
            return item

        domain: str = item.get("domain") or ""
        pdf_bytes: bytes = item.get("html_content") or b""

        if not pdf_bytes:
            logger.warning("PDF item from %s has empty html_content", domain)
            return item

        # Compute content SHA-256 (used as filename stem throughout cache).
        # Guard: if ChangeDetectionPipeline (priority 100) already set
        # content_sha256, reuse it rather than overwriting.  spec §2.6.
        if not item.get("content_sha256"):
            item["content_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
        content_sha256: str = item["content_sha256"]

        date_str = _date_from_timestamp(item.get("crawl_timestamp"))
        pdfs_dir = self._raw_cache_dir / domain / date_str / "pdfs"

        extraction_failed: bool = False
        try:
            full_text, extraction_meta = self._extract_text(pdf_bytes)
        except Exception as exc:
            logger.error(
                "Unexpected error extracting PDF %s (%s): %s",
                item.get("url"),
                domain,
                exc,
            )
            full_text = ""
            extraction_meta = {"extraction_method": "error", "error": str(exc)}
            extraction_failed = True

        # Step 6 — language detection.
        if full_text.strip():
            lang_code = self._detect_language(full_text)
            if lang_code:
                item["language"] = lang_code

        # Step 7 — header/footer stripping is applied inside _extract_text.
        # Step 8 — set char_count and write .txt sidecar.
        item["char_count"] = len(full_text)

        # Consider extraction failed when no text was recovered at all.
        if item["char_count"] == 0:
            extraction_failed = True

        if full_text:
            txt_path = pdfs_dir / f"{content_sha256}.txt"
            _write_bytes_atomic(txt_path, full_text.encode("utf-8"))
            logger.debug(
                "Wrote PDF text %s (%d chars)", txt_path.name, len(full_text)
            )

        # item['content_sha256'], item['char_count'], and item['language'] are now
        # set.  ContentStoragePipeline (priority 500) reads these and writes the
        # meta.json sidecar.  extraction_meta is logged at DEBUG level for
        # diagnostics but not stored on the item (GrantItem only allows declared
        # fields).
        logger.debug(
            "PDF extraction complete for %s: %s", item.get("url"), extraction_meta
        )

        # Report stats back to the spider so _build_domain_stats() can include
        # accurate PDF counts in the QA report (wired in Phase C).
        if domain:
            pdfs_found = getattr(spider, "_domain_pdfs_found", None)
            if pdfs_found is not None:
                pdfs_found[domain] += 1
            if extraction_failed:
                pdf_failures = getattr(spider, "_domain_pdf_failures", None)
                if pdf_failures is not None:
                    pdf_failures[domain] += 1

        return item

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def _extract_text(self, pdf_bytes: bytes) -> tuple[str, dict]:
        """
        Run the full extraction sequence (Steps 1–7) and return the
        cleaned text and an extraction metadata dict.

        Spec ref: §2.4 Steps 1–7.
        """
        meta: dict = {}

        # ── Step 1: PyMuPDF primary extraction ────────────────────────────
        page_texts: list[str] = []
        page_char_counts: list[int] = []
        total_pages = 0

        if not _FITZ_AVAILABLE:
            logger.warning("PyMuPDF not available — skipping PDF text extraction")
            return "", {"extraction_method": "unavailable"}

        try:
            doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            # Password-protected or corrupted PDFs.
            err_str = str(exc).lower()
            if "password" in err_str or "encrypted" in err_str:
                logger.warning("Password-protected PDF — skipping: %s", exc)
                return "", {"extraction_method": "encrypted"}
            logger.error("fitz.open failed: %s", exc)
            return "", {"extraction_method": "error", "error": str(exc)}

        try:
            total_pages = doc.page_count
            for page in doc:
                text = page.get_text("text") or ""
                page_texts.append(text)
                page_char_counts.append(len(text))
        finally:
            doc.close()

        meta["total_pages"] = total_pages
        meta["extraction_method"] = "pymupdf"

        # ── Step 2: pdfplumber — merge table content ──────────────────────
        if _PDFPLUMBER_AVAILABLE and total_pages > 0:
            try:
                with _pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    for page_idx, page in enumerate(pdf.pages):
                        if page_idx >= len(page_texts):
                            break
                        tables = page.extract_tables() or []
                        for table in tables:
                            rows_text = "\n".join(
                                " | ".join(str(cell or "").strip() for cell in row)
                                for row in table
                                if row
                            )
                            if rows_text.strip():
                                page_texts[page_idx] = (
                                    page_texts[page_idx] + "\n" + rows_text
                                )
            except Exception as exc:
                logger.debug("pdfplumber secondary pass failed: %s", exc)

        # ── Step 3: OCR threshold decision ───────────────────────────────
        if total_pages > 0:
            failed_page_indices = [
                i
                for i, count in enumerate(page_char_counts)
                if count < self._ocr_min_chars
            ]
            fail_ratio = len(failed_page_indices) / total_pages
        else:
            failed_page_indices = []
            fail_ratio = 0.0

        meta["ocr_threshold_ratio"] = round(fail_ratio, 3)

        if (
            fail_ratio >= self._ocr_threshold
            and _PDF2IMAGE_AVAILABLE
            and _PYTESSERACT_AVAILABLE
            and failed_page_indices
        ):
            # ── Steps 4–5: selective OCR on failed pages only ─────────────
            ocr_lang_str = "+".join(self._ocr_languages)
            ocr_page_count = 0
            batch_size = self._ocr_page_batch_size

            for batch_start in range(0, len(failed_page_indices), batch_size):
                batch = failed_page_indices[batch_start: batch_start + batch_size]
                for page_idx in batch:
                    one_based = page_idx + 1  # pdf2image uses 1-based page numbers
                    try:
                        images = _convert_from_bytes(
                            pdf_bytes,
                            dpi=self._ocr_dpi,
                            first_page=one_based,
                            last_page=one_based,
                        )
                        if images:
                            ocr_text = _pytesseract.image_to_string(
                                images[0], lang=ocr_lang_str
                            )
                            page_texts[page_idx] = ocr_text
                            page_char_counts[page_idx] = len(ocr_text)
                            ocr_page_count += 1
                            del images  # free PNG memory immediately
                    except Exception as exc:
                        logger.debug(
                            "OCR failed for page %d: %s", one_based, exc
                        )

            meta["ocr_pages"] = ocr_page_count
            if ocr_page_count:
                meta["extraction_method"] = "pymupdf+ocr"
                meta["ocr_language"] = ocr_lang_str

        # ── Step 6 placeholder (language detection called from caller) ─────

        # ── Step 7: strip repeated headers/footers ────────────────────────
        cleaned_pages = _strip_header_footer(page_texts, self._footer_repeat_threshold)

        full_text = "\n\n".join(p for p in cleaned_pages if p.strip())
        return full_text, meta

    # ------------------------------------------------------------------
    # Language detection
    # ------------------------------------------------------------------

    def _detect_language(self, text: str) -> str | None:
        """
        Run lingua-language-detector on *text* and return the ISO 639-1
        code (e.g. 'en', 'fr', 'ar') or None if detection fails or
        lingua is not installed.

        Spec ref: §2.4 Step 6 — Language detection.
        """
        if not _LINGUA_AVAILABLE:
            return None

        try:
            if self._language_detector is None:
                self._language_detector = self._build_detector()
            if self._language_detector is None:
                return None

            sample = text[:5_000]  # lingua works well on shorter samples
            result = self._language_detector.detect_language_of(sample)
            if result is None:
                return None
            # IsoCode639_1 enum: result.iso_code_639_1 → e.g. IsoCode639_1.EN
            return result.iso_code_639_1.name.lower()
        except Exception as exc:
            logger.debug("Language detection failed: %s", exc)
            return None

    def _build_detector(self):
        """
        Build the lingua LanguageDetector from configured LINGUA_LANGUAGES.
        Returns None if no valid Language enum values are found.
        """
        if not _LINGUA_AVAILABLE:
            return None
        try:
            languages = [
                _Language[lang_name]
                for lang_name in self._lingua_languages
                if hasattr(_Language, lang_name)
            ]
            if not languages:
                return None
            return _LanguageDetectorBuilder.from_languages(*languages).build()
        except Exception as exc:
            logger.warning("Could not build lingua detector: %s", exc)
            return None


# ===========================================================================
# Module-level helpers
# ===========================================================================


def _strip_header_footer(
    page_texts: list[str],
    threshold: float,
) -> list[str]:
    """
    Remove lines that appear as headers or footers on ≥ *threshold*
    fraction of all pages.

    Strategy: collect the first and last non-empty line of each page,
    count occurrences across pages, strip any line that appears in ≥
    ``threshold`` fraction of pages from all page texts.

    Spec ref: §2.4 Step 7 — "repeated headers/footers (detected by
    identical strings appearing at the top or bottom of ≥ 70% of pages)".
    """
    if not page_texts:
        return page_texts

    total = len(page_texts)
    if total == 0:
        return page_texts

    boundary_lines: list[str] = []
    for text in page_texts:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            boundary_lines.append(lines[0])  # first line (potential header)
        if len(lines) > 1:
            boundary_lines.append(lines[-1])  # last line (potential footer)

    counts = Counter(boundary_lines)
    repeated: set[str] = {
        line
        for line, count in counts.items()
        if line and count / total >= threshold
    }

    if not repeated:
        return page_texts

    cleaned: list[str] = []
    for text in page_texts:
        lines = text.splitlines()
        filtered = [ln for ln in lines if ln.strip() not in repeated]
        cleaned.append("\n".join(filtered))

    return cleaned


def _date_from_timestamp(crawl_timestamp: str | None) -> str:
    """Extract YYYY-MM-DD from ISO 8601 string; fall back to today's UTC date."""
    if crawl_timestamp and len(crawl_timestamp) >= 10:
        candidate = crawl_timestamp[:10]
        if candidate.count("-") == 2:
            return candidate
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write *data* bytes to *path* atomically (temp-file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
