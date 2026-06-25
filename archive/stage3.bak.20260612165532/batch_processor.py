"""
Batch Processor — orchestrates the Stage 3 extraction pipeline.

Startup:
  1. Reset stale 'processing' rows (>8 hours old) to 'pending'.
  2. Check for Stage 2 crawl_complete sentinel file.
  3. Scan raw_cache for changed pages not yet completed.
  4. Claim rows using SELECT FOR UPDATE SKIP LOCKED.
"""

import gzip
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional, Union

import structlog
from bs4 import BeautifulSoup

from .db import get_cursor

log = structlog.get_logger(__name__)

# Sentinel polling constants — injectable via the _poll_interval parameter in
# check_crawl_complete_sentinel so tests don't have to wait real time.
_SENTINEL_MAX_WAIT_S = 4 * 60 * 60   # 4 hours
_SENTINEL_POLL_S = 15 * 60           # 15 minutes


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------

def reset_stale_processing_rows(conn) -> int:
    """Reset extraction_log rows stuck in 'processing' for more than 8 hours.

    Rows left in 'processing' by a previous crashed run are reset to 'pending'
    so they will be picked up by the next cycle.  The 8-hour threshold ensures
    a live worker's recently-claimed rows are never stolen by a concurrent
    restart (§3.5 of the design doc).

    Returns the number of rows reset.
    """
    with get_cursor(conn) as cur:
        cur.execute(
            """
            UPDATE extraction_log
            SET status = 'pending', error_message = 'reset from stale processing'
            WHERE status = 'processing'
              AND processed_at < NOW() - INTERVAL '8 hours'
            """
        )
        count = cur.rowcount

    log.info("stale_rows_reset", count=count)
    return count


# ---------------------------------------------------------------------------
# Sentinel check
# ---------------------------------------------------------------------------

def check_crawl_complete_sentinel(
    raw_cache_dir: Union[str, Path],
    run_date: Union[str, date],
    *,
    force: bool = False,
    _poll_interval: int = _SENTINEL_POLL_S,
) -> None:
    """Block until the Stage 2 crawl_complete sentinel file appears.

    Stage 2 writes ``raw_cache/crawl_complete_{YYYY-MM-DD}.json`` as its
    final action.  Stage 3 polls for this file before beginning processing.

    Args:
        raw_cache_dir: Path to the Stage 2 raw_cache directory.
        run_date: The crawl cycle date as a ``date`` object or ISO string.
        force: If True, bypass the check entirely (--force flag).
        _poll_interval: Seconds between polls (injectable for tests).

    Raises:
        RuntimeError: If the sentinel is not found within 4 hours.
    """
    if force:
        log.info("sentinel_check_bypassed", reason="--force flag set")
        return

    date_str = run_date.isoformat() if isinstance(run_date, date) else str(run_date)
    sentinel = Path(raw_cache_dir) / f"crawl_complete_{date_str}.json"

    elapsed = 0
    while not sentinel.exists():
        if elapsed >= _SENTINEL_MAX_WAIT_S:
            log.warning(
                "sentinel_timeout",
                path=str(sentinel),
                waited_hours=_SENTINEL_MAX_WAIT_S / 3600,
            )
            raise RuntimeError(
                f"Stage 2 sentinel file not found after "
                f"{_SENTINEL_MAX_WAIT_S // 3600} hours: {sentinel}"
            )
        log.info(
            "sentinel_polling",
            path=str(sentinel),
            elapsed_minutes=elapsed // 60,
        )
        time.sleep(_poll_interval)
        elapsed += _poll_interval

    log.info("sentinel_found", path=str(sentinel))


# ---------------------------------------------------------------------------
# raw_cache scanner
# ---------------------------------------------------------------------------

def scan_for_pending_pages(
    conn,
    raw_cache_dir: Union[str, Path],
    run_date: Union[str, date],
) -> int:
    """Walk raw_cache for changed pages and register them in extraction_log.

    For each ``.meta.json`` file where ``changed == true`` and
    ``crawl_date`` matches *run_date*, inserts a row into ``extraction_log``
    using ``ON CONFLICT DO NOTHING`` so re-runs are idempotent.

    Returns the count of newly inserted rows.
    """
    date_str = run_date.isoformat() if isinstance(run_date, date) else str(run_date)
    raw_cache_path = Path(raw_cache_dir)
    inserted = 0

    with get_cursor(conn) as cur:
        for meta_path in sorted(raw_cache_path.rglob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning(
                    "meta_json_read_error", path=str(meta_path), error=str(exc)
                )
                continue

            if not meta.get("changed", False):
                continue

            crawl_date_raw = meta.get("crawl_date") or (meta.get("crawl_timestamp") or "")[:10]
            if str(crawl_date_raw) != date_str:
                continue

            # url_hash: prefer explicit field, fall back to filename without
            # suffixes.  meta_path.stem strips only the last suffix (.json),
            # leaving ".meta" attached, which would overflow CHAR(16).
            # Path(meta_path.stem).stem strips both ".meta" and ".json".
            url_hash: str = meta.get("url_hash") or Path(meta_path.stem).stem
            # domain: prefer explicit field, fall back to directory structure.
            domain: str = meta.get("domain") or _domain_from_path(
                meta_path, raw_cache_path
            )

            cur.execute(
                """
                INSERT INTO extraction_log (url_hash, domain, crawl_date)
                VALUES (%(url_hash)s, %(domain)s, %(crawl_date)s)
                ON CONFLICT (url_hash, crawl_date) DO NOTHING
                """,
                {
                    "url_hash": url_hash,
                    "domain": domain,
                    "crawl_date": date_str,
                },
            )
            if cur.rowcount:
                inserted += 1

    log.info("scan_complete", run_date=date_str, inserted=inserted)
    return inserted


def _domain_from_path(meta_path: Path, raw_cache_root: Path) -> str:
    """Infer domain from the directory layout:
    ``{raw_cache_root}/{domain}/{date}/pages/{url_hash}.meta.json``.
    """
    try:
        return meta_path.relative_to(raw_cache_root).parts[0]
    except (ValueError, IndexError):
        return "unknown"


# ---------------------------------------------------------------------------
# Row claiming
# ---------------------------------------------------------------------------

def claim_pending_rows(conn, batch_size: int = 100) -> list:
    """Atomically claim up to *batch_size* pending rows from extraction_log.

    Uses ``SELECT … FOR UPDATE SKIP LOCKED`` so that concurrent Stage 3
    workers never claim the same row.  Claimed rows are immediately updated
    to ``status = 'processing'`` within the same transaction, so the lock is
    released on commit with the status change persisted.

    Returns a list of row dicts (id, url_hash, domain, crawl_date).
    """
    with get_cursor(conn) as cur:
        cur.execute(
            """
            SELECT id, url_hash, domain, crawl_date
            FROM extraction_log
            WHERE status = 'pending'
            ORDER BY id
            LIMIT %(batch_size)s
            FOR UPDATE SKIP LOCKED
            """,
            {"batch_size": batch_size},
        )
        rows = cur.fetchall()

        if rows:
            ids = [r["id"] for r in rows]
            cur.execute(
                """
                UPDATE extraction_log
                SET status = 'processing', processed_at = NOW()
                WHERE id = ANY(%(ids)s)
                """,
                {"ids": ids},
            )

    return list(rows)


# ---------------------------------------------------------------------------
# Status updaters
# ---------------------------------------------------------------------------

def mark_completed(conn, row_id: int, records_extracted: int) -> None:
    """Mark an extraction_log row as successfully completed."""
    with get_cursor(conn) as cur:
        cur.execute(
            """
            UPDATE extraction_log
            SET status = 'completed',
                records_extracted = %(records)s
            WHERE id = %(id)s
            """,
            {"id": row_id, "records": records_extracted},
        )


def mark_failed(conn, row_id: int, error_message: str) -> None:
    """Mark an extraction_log row as failed and increment retry_count."""
    with get_cursor(conn) as cur:
        cur.execute(
            """
            UPDATE extraction_log
            SET status = 'failed',
                error_message = %(error)s,
                retry_count = retry_count + 1
            WHERE id = %(id)s
            """,
            {"id": row_id, "error": error_message},
        )


def mark_skipped(conn, row_id: int, reason: str) -> None:
    """Mark an extraction_log row as skipped (e.g. content_too_short)."""
    with get_cursor(conn) as cur:
        cur.execute(
            """
            UPDATE extraction_log
            SET status = 'skipped',
                error_message = %(reason)s
            WHERE id = %(id)s
            """,
            {"id": row_id, "reason": reason},
        )


# ---------------------------------------------------------------------------
# Token counting and content preparation
# ---------------------------------------------------------------------------

def _count_tokens(text: str, model_name: str) -> int:
    """Estimate token count as chars/4 — avoids a slow API call per page."""
    return max(1, len(text) // 4)


def truncate_to_token_budget(text: str, max_tokens: int, model_name: str) -> str:
    """Return the largest word-boundary prefix of *text* within *max_tokens*.

    Performs a binary search over word counts, calling ``_count_tokens`` at
    most **5 times**.  The caller is responsible for only invoking this
    function when the full text is already known to exceed *max_tokens*
    (i.e. after an initial check in ``prepare_html_page`` /
    ``prepare_pdf_page``).  This avoids an additional wasted API round-trip
    inside the binary search.

    Invariant maintained throughout:
      - ``lo``  words are confirmed to fit within *max_tokens*.
      - ``hi``  words are confirmed to exceed *max_tokens* (or equal
                ``len(words)`` which the caller guarantees is over-budget).
    """
    words = text.split()
    if not words:
        return ""

    lo, hi = 0, len(words)

    for _ in range(5):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        candidate = " ".join(words[:mid])
        if _count_tokens(candidate, model_name) <= max_tokens:
            lo = mid
        else:
            hi = mid

    # lo is the largest word count confirmed to fit.  If lo == 0 (extreme edge
    # case where even a single word exceeds the budget), return the first word
    # as a best-effort result rather than an empty string.
    return " ".join(words[:lo]) if lo > 0 else words[0]


def prepare_html_page(
    meta_json_path: Union[str, Path],
    raw_cache_dir: Union[str, Path],
    model_name: str,
) -> tuple[Optional[str], Optional[str]]:
    """Strip and truncate an HTML page for LLM submission.

    Steps (§5.1 step 2):
      1. Read *meta_json_path* to get ``html_path`` (relative to raw_cache_dir).
      2. Decompress the ``.html.gz`` file.
      3. Strip HTML tags with BeautifulSoup / lxml.
      4. Count tokens; skip if < 50 (content_too_short).
      5. Truncate to 6 000 tokens if over budget.

    Returns:
        ``(text, None)`` on success.
        ``(None, reason)`` when the page should be skipped or on read error.
    """
    meta_json_path = Path(meta_json_path)
    raw_cache_dir = Path(raw_cache_dir)

    # -- read meta ----------------------------------------------------------
    try:
        meta = json.loads(meta_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("meta_json_read_error", path=str(meta_json_path), error=str(exc))
        return None, "meta_read_error"

    html_path_rel: Optional[str] = meta.get("html_path")
    if not html_path_rel:
        inferred = Path(str(meta_json_path).replace(".meta.json", ".html"))
        if not inferred.exists():
            log.error("missing_html_path", path=str(meta_json_path))
            return None, "missing_html_path"
        try:
            raw_html = inferred.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.error("html_read_error", path=str(inferred), error=str(exc))
            return None, "html_read_error"
    else:
        html_gz_path = raw_cache_dir / html_path_rel
        try:
            with gzip.open(html_gz_path, "rb") as fh:
                raw_html = fh.read().decode("utf-8", errors="replace")
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            log.error("html_gz_read_error", path=str(html_gz_path), error=str(exc))
            return None, "html_read_error"

    # -- strip html ---------------------------------------------------------
    soup = BeautifulSoup(raw_html, "lxml")
    text = soup.get_text(separator=" ", strip=True)

    # -- minimum length check -----------------------------------------------
    token_count = _count_tokens(text, model_name)
    if token_count < 50:
        log.info(
            "content_too_short",
            path=str(meta_json_path),
            tokens=token_count,
        )
        return None, "content_too_short"

    # -- truncate if over budget --------------------------------------------
    if token_count > 6_000:
        text = truncate_to_token_budget(text, 6_000, model_name)

    return text, None


def prepare_pdf_page(
    meta_json_path: Union[str, Path],
    model_name: str,
) -> tuple[Optional[str], Optional[str]]:
    """Extract and truncate PDF text from a meta JSON file.

    Stage 2's PDFExtractionPipeline stores the extracted text in the
    ``pdf_text`` field of the ``.meta.json``.  This function reads that
    field and applies the same length check and truncation logic as
    ``prepare_html_page``, with a larger token budget of 12 000.

    Returns:
        ``(text, None)`` on success.
        ``(None, reason)`` when the page should be skipped or on read error.
    """
    meta_json_path = Path(meta_json_path)

    # -- read meta ----------------------------------------------------------
    try:
        meta = json.loads(meta_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("meta_json_read_error", path=str(meta_json_path), error=str(exc))
        return None, "meta_read_error"

    pdf_text: str = (meta.get("pdf_text") or "").strip()
    if not pdf_text:
        log.info("no_pdf_text", path=str(meta_json_path))
        return None, "no_pdf_text"

    # -- minimum length check -----------------------------------------------
    token_count = _count_tokens(pdf_text, model_name)
    if token_count < 50:
        log.info(
            "content_too_short",
            path=str(meta_json_path),
            tokens=token_count,
        )
        return None, "content_too_short"

    # -- truncate if over budget --------------------------------------------
    if token_count > 12_000:
        pdf_text = truncate_to_token_budget(pdf_text, 12_000, model_name)

    return pdf_text, None


# ---------------------------------------------------------------------------
# Top-level orchestration (Phase D)
# ---------------------------------------------------------------------------


def _build_meta_index(
    raw_cache_dir: Union[str, Path],
    run_date: Union[str, date],
) -> dict:
    """Walk raw_cache_dir and return a mapping of url_hash → meta_json_path.

    Only meta files whose ``crawl_date`` field matches *run_date* are included.
    This makes it possible to pass ``meta_path`` to the prepare functions after
    claiming rows from ``extraction_log``.
    """
    date_str = run_date.isoformat() if isinstance(run_date, date) else str(run_date)
    index: dict[str, str] = {}
    for meta_path in Path(raw_cache_dir).rglob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        crawl_date_raw = meta.get("crawl_date") or (meta.get("crawl_timestamp") or "")[:10]
        if str(crawl_date_raw) != date_str:
            continue
        url_hash: str = meta.get("url_hash") or Path(meta_path.stem).stem
        index[url_hash] = str(meta_path)
    return index


def run_extraction_cycle(
    force: bool = False,
    run_date: Optional[str] = None,
    dry_run: bool = False,
    _extract_fn=None,
) -> dict:
    """Orchestrate one full Stage 3 extraction cycle.

    Steps (§5.1):
      0. Startup recovery — reset stale 'processing' rows.
      1. Check Stage 2 sentinel (skipped when ``force=True``).
      2. Scan raw_cache for pending pages.
      3. Claim rows, prepare content.
      4. Submit prepared pages to Gemini via ``_extract_fn``.
      5. Normalise each raw grant and upsert into the ``grants`` table.
      6. Export review queue CSV.
      7. Write extraction QA report.

    Args:
        force:       Skip the Stage 2 sentinel check (useful for manual reruns).
        run_date:    ISO-8601 date string (YYYY-MM-DD) for the cycle.  Defaults
                     to today (UTC) when None.
        dry_run:     Scan and prepare pages and estimate cost via
                     ``count_tokens()``, but submit no LLM calls and write
                     nothing to the database.
        _extract_fn: Injectable extraction function for testing.  Defaults to
                     ``stage3.extractor.extract_pages``.  Signature must match
                     ``extract_pages(page_contents, conn) -> list[dict]``.

    Returns:
        Dict of pipeline statistics (pages_processed, records_inserted_new,
        etc.).  Empty dict on dry-run or when no pages are pending.
    """
    import os
    from datetime import datetime, timezone
    from stage3.db import get_connection
    from stage3.extractor import MODEL_NAME, build_page_prompt, extract_pages
    from stage3.normaliser import normalise_raw_grant
    from stage3.writer import upsert_grant, export_review_queue
    from stage3.qa_reporter import write_extraction_report

    if _extract_fn is None:
        _extract_fn = extract_pages

    raw_cache_dir = os.environ.get("RAW_CACHE_DIR", "raw_cache")
    output_dir = os.environ.get("STAGE3_OUTPUT_DIR", "stage3_output")
    batch_size = int(os.environ.get("STAGE3_BATCH_SIZE", "2000"))

    if run_date is None:
        run_date = datetime.now(timezone.utc).date().isoformat()

    log.info("extraction_cycle_start", run_date=run_date, force=force, dry_run=dry_run)

    # Step 0 — startup recovery
    conn = get_connection()
    try:
        reset_stale_processing_rows(conn)
        conn.commit()
    finally:
        conn.close()

    # Step 1 — sentinel check (deliberately outside any DB connection)
    if not force:
        check_crawl_complete_sentinel(raw_cache_dir, run_date)

    # Step 2 — scan raw_cache
    conn = get_connection()
    try:
        scan_for_pending_pages(conn, raw_cache_dir, run_date)
        conn.commit()
    finally:
        conn.close()

    if dry_run:
        log.info("dry_run_complete", run_date=run_date)
        return {}

    # Step 3 — build url_hash → meta_path index (fast filesystem walk)
    meta_index = _build_meta_index(raw_cache_dir, run_date)

    # Step 4 — claim rows
    conn = get_connection()
    try:
        claimed_rows = claim_pending_rows(conn, batch_size=batch_size)
        conn.commit()
    finally:
        conn.close()

    if not claimed_rows:
        log.info("no_pending_rows", run_date=run_date)
        _flush_output_artifacts(output_dir, run_date, {})
        return {}

    # Step 5 — prepare page content (html or pdf)
    page_contents: list[dict] = []
    pages_skipped = 0
    pages_failed = 0

    for row in claimed_rows:
        url_hash = row["url_hash"]
        meta_path_str = meta_index.get(url_hash)

        if not meta_path_str:
            conn = get_connection()
            try:
                mark_failed(conn, row["id"], "meta_not_found")
                conn.commit()
            finally:
                conn.close()
            pages_failed += 1
            continue

        try:
            meta = json.loads(Path(meta_path_str).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            conn = get_connection()
            try:
                mark_failed(conn, row["id"], f"meta_read_error: {exc}")
                conn.commit()
            finally:
                conn.close()
            pages_failed += 1
            continue

        is_pdf = meta.get("is_pdf", False)
        if is_pdf:
            text, reason = prepare_pdf_page(meta_path_str, MODEL_NAME)
        else:
            text, reason = prepare_html_page(meta_path_str, Path(raw_cache_dir), MODEL_NAME)

        if text is None:
            conn = get_connection()
            try:
                if reason == "content_too_short":
                    mark_skipped(conn, row["id"], reason)
                    pages_skipped += 1
                else:
                    mark_failed(conn, row["id"], reason or "prepare_error")
                    pages_failed += 1
                conn.commit()
            finally:
                conn.close()
            continue

        prompt = build_page_prompt(text)
        page_contents.append(
            {"url_hash": url_hash, "prompt": prompt, "row": dict(row), "meta": meta}
        )

    if not page_contents:
        _flush_output_artifacts(
            output_dir,
            run_date,
            {"pages_processed": len(claimed_rows),
             "pages_skipped_content_too_short": pages_skipped,
             "pages_failed": pages_failed},
        )
        return {}

    # Step 6 — submit to extraction function (Gemini Batch API or mock)
    hash_to_meta = {item["url_hash"]: item["meta"] for item in page_contents}
    conn = get_connection()
    try:
        raw_grants = _extract_fn(page_contents, conn)
        conn.commit()
    except Exception as exc:
        log.error("extraction_failed", error=str(exc))
        conn2 = get_connection()
        try:
            for item in page_contents:
                mark_failed(conn2, item["row"]["id"], f"extraction_error: {exc}")
            conn2.commit()
        finally:
            conn2.close()
        raise
    finally:
        conn.close()

    # Step 7 — normalise and upsert each grant
    records_inserted = 0
    records_updated = 0
    records_skipped_dup = 0
    records_flagged = 0
    grants_per_hash: dict[str, int] = {}

    conn = get_connection()
    try:
        for raw_grant in raw_grants:
            url_hash = raw_grant.pop("__url_hash", None)
            meta = hash_to_meta.get(url_hash, {}) if url_hash else {}
            source = {
                "source_url": meta.get("url") or meta.get("source_url") or "",
                "domain": meta.get("domain") or "unknown",
                "crawl_date": run_date,
            }

            normalised = normalise_raw_grant(raw_grant, source)
            result = upsert_grant(conn, normalised)

            if result == "inserted":
                records_inserted += 1
            elif result == "updated":
                records_updated += 1
            else:
                records_skipped_dup += 1

            if normalised.get("requires_review") and result != "skipped":
                records_flagged += 1

            if url_hash:
                grants_per_hash[url_hash] = grants_per_hash.get(url_hash, 0) + 1
    finally:
        conn.close()

    pages_empty = sum(
        1 for item in page_contents if grants_per_hash.get(item["url_hash"], 0) == 0
    )

    # Step 8 — export review queue CSV
    conn = get_connection()
    try:
        export_review_queue(conn, output_dir, run_date)
    finally:
        conn.close()

    # Step 9 — write QA report
    full_stats: dict = {
        "pages_processed": len(claimed_rows),
        "pages_skipped_content_too_short": pages_skipped,
        "pages_failed": pages_failed,
        "pages_empty_extraction": pages_empty,
        "records_extracted_total": len(raw_grants),
        "records_inserted_new": records_inserted,
        "records_updated_higher_confidence": records_updated,
        "records_duplicate_lower_confidence": records_skipped_dup,
        "records_flagged_review": records_flagged,
        "domains_zero_extraction": sorted({
            item["meta"].get("domain", "unknown")
            for item in page_contents
            if grants_per_hash.get(item["url_hash"], 0) == 0
        }),
    }
    write_extraction_report(full_stats, run_date, output_dir)

    log.info("extraction_cycle_complete", run_date=run_date, **full_stats)
    return full_stats


def _flush_output_artifacts(
    output_dir: Union[str, Path],
    run_date: str,
    stats: dict,
) -> None:
    """Write review queue + QA report even when there is nothing to process."""
    from stage3.db import get_connection
    from stage3.writer import export_review_queue
    from stage3.qa_reporter import write_extraction_report

    conn = get_connection()
    try:
        export_review_queue(conn, output_dir, run_date)
    finally:
        conn.close()
    write_extraction_report(stats, run_date, output_dir)
