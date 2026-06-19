"""
LLM Extractor — Gemini 3.5 Flash Batch API client.

MODEL_NAME is a module-level constant. Verify the exact API string against
Google AI documentation at build time — it may be 'gemini-3.5-flash' or a
versioned alias such as 'gemini-3.5-flash-001'.

Public surface
--------------
MODEL_NAME          : str            — model identifier constant
SYSTEM_PROMPT       : str            — verbatim 12-rule extraction prompt
RESPONSE_SCHEMA     : dict           — Gemini response_schema dict
build_page_prompt() : str            — assembles per-page prompt string
BatchTimeoutError   : Exception      — raised after 6-hour polling timeout
submit_batch()      : str            — submits a Gemini Batch API job, returns job_id
poll_batch_until_complete() : job    — blocks until job finishes or times out
parse_batch_results(): tuple         — parses results, marks DB rows
extract_pages()     : list           — top-level orchestrator for one batch cycle
"""

import json
import time
from typing import Any

import structlog

from .batch_processor import mark_completed, mark_failed

# ---------------------------------------------------------------------------
# Model identifier
# ---------------------------------------------------------------------------

# Gemini 3.5 Flash was released at Google I/O on 19 May 2026.  Confirm this
# string against https://ai.google.dev before the first production API call.
# Update only this constant if Google revises the identifier.
MODEL_NAME = "gemini-3.5-flash"

# ---------------------------------------------------------------------------
# System prompt  (§6.2 — verbatim, all 12 rules)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a grant opportunity extraction specialist. Your task is to read the text of a web page or document and extract ALL grant, fellowship, scholarship, or funding opportunities described on that page.

CRITICAL RULES — read carefully before extracting:

1. Return a JSON list. If there are no grant opportunities on the page, return an empty list [].
   If there are multiple opportunities on the same page, return one object per opportunity.

2. Never fabricate values. If a field's value is not clearly stated in the source text,
   return null for that field. Do not guess, infer, or construct plausible values.

3. Return exactly what the source text says for all raw text fields.
   The normalisation system will standardise values — your job is accurate extraction only.

4. Assign a confidence score to every field:
   - "high": value is explicitly and unambiguously stated in the source text
   - "medium": value is implied or partially stated — likely correct but not certain
   - "low": value is uncertain, inferred from indirect or ambiguous language
   - "not_found": field is not present or cannot be identified in the source text

5. For individual_eligibility: if the source text says "early career researcher" without
   specifying whether current PhD students are included, assign "Early Career Researcher"
   with confidence "medium" and include a note in the raw_notes field.
   If PhD students are explicitly included, assign BOTH "Student — Postgraduate / PhD"
   AND "Early Career Researcher (includes PhD candidates)".

6. For ai_focused: assign true only when AI, machine learning, deep learning, large language
   models, generative AI, neural networks, NLP, computer vision, AI governance, AI ethics,
   or AI safety is a substantive focus of the grant — not merely mentioned in passing.

7. For current_status: extract only what the source explicitly states.
   Do NOT compute or infer status from the deadline date — the system handles this separately.

8. For geographic fields: extract country and region names exactly as written.
   Do not convert to codes — the normalisation system handles standardisation.

9. For funding amounts: extract numeric values only. Convert abbreviations:
   "£50k" → 50000, "$2.5 million" → 2500000. If a range is stated, populate both min and max.

10. For description: write a plain-text summary of 2–3 sentences maximum. Capture the core
    purpose of the grant and who it is for. Do not copy the full page text. Return null if
    there is insufficient content to produce a meaningful summary.

11. For grant_opening_date: extract the date when the grant round opens or applications begin
    to be accepted, if explicitly stated. This is distinct from the application deadline.
    Return null if not stated. Return the raw date string exactly as written.

12. For non-English source documents: extract field values in the source language exactly as
    written. Do not translate.
    Controlled-vocabulary matching is English-only in this prototype. If the source is non-English, extract values in the source language — they will be preserved in the raw data and flagged for review.
    For free-text fields (grant_title, funder_name, description), preserve the original
    language text. Set source_language_raw to the language you detect.\
"""

# ---------------------------------------------------------------------------
# Response schema  (§6.3)
# ---------------------------------------------------------------------------

_CONFIDENCE_ENUM = {
    "type": "string",
    "enum": ["high", "medium", "low", "not_found"],
}

RESPONSE_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            # Core text fields
            "grant_title":              {"type": ["string", "null"]},
            "funder_name":              {"type": ["string", "null"]},
            "description":              {"type": ["string", "null"]},
            # Deadline fields
            "application_deadline_raw": {"type": ["string", "null"]},
            "deadline_notes":           {"type": ["string", "null"]},
            "eoi_deadline_raw":         {"type": ["string", "null"]},
            "grant_opening_date_raw":   {"type": ["string", "null"]},
            # Funding amount
            "funding_amount_min":       {"type": ["number", "null"]},
            "funding_amount_max":       {"type": ["number", "null"]},
            "currency_raw":             {"type": ["string", "null"]},
            # Status / portal
            "current_status_raw":       {"type": ["string", "null"]},
            "application_portal_url":   {"type": ["string", "null"]},
            # Language
            "source_language_raw":      {"type": ["string", "null"]},
            # Boolean flags
            "ai_focused":               {"type": ["boolean", "null"]},
            "individuals_not_eligible": {"type": ["boolean", "null"]},
            # Array fields
            "organisation_types_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            "individual_eligibility_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            "applicant_base_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            "geographic_focus_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            "thematic_sectors_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            "grant_types_raw": {
                "type": "array",
                "items": {"type": "string"},
            },
            # Confidence scores (one per scored field)
            "confidence_scores": {
                "type": "object",
                "properties": {
                    "grant_title":           _CONFIDENCE_ENUM,
                    "funder_name":           _CONFIDENCE_ENUM,
                    "application_deadline":  _CONFIDENCE_ENUM,
                    "eoi_deadline":          _CONFIDENCE_ENUM,
                    "grant_opening_date":    _CONFIDENCE_ENUM,
                    "funding_amount":        _CONFIDENCE_ENUM,
                    "current_status":        _CONFIDENCE_ENUM,
                    "geographic_focus":      _CONFIDENCE_ENUM,
                    "thematic_sectors":      _CONFIDENCE_ENUM,
                    "individual_eligibility": _CONFIDENCE_ENUM,
                    "organisation_types":    _CONFIDENCE_ENUM,
                    "applicant_base":        _CONFIDENCE_ENUM,
                    "ai_focused":            _CONFIDENCE_ENUM,
                },
            },
            # Free-text annotation field
            "raw_notes": {"type": ["string", "null"]},
        },
    },
}

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Timing constants (injectable via keyword args in tests)
# ---------------------------------------------------------------------------

_POLL_FAST_INTERVAL_S: int = 5 * 60       # 5 minutes — first 60 minutes
_POLL_SLOW_INTERVAL_S: int = 15 * 60      # 15 minutes — after first 60 minutes
_POLL_FAST_THRESHOLD_S: int = 60 * 60     # switch to slow polling after 60 minutes
_POLL_MAX_WAIT_S: int = 6 * 60 * 60       # hard timeout: 6 hours

_RETRY_BACKOFFS: tuple[int, ...] = (30, 60, 120)   # seconds for up to 3 retries
_RATE_LIMIT_PAUSE_S: int = 60             # pause duration for 429 responses


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class BatchTimeoutError(Exception):
    """Raised when a Gemini Batch API job exceeds the 6-hour polling timeout."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _genai():
    """Lazily import google.generativeai so tests can import this module freely."""
    import google.genai as genai  # noqa: PLC0415
    return genai


def _is_rate_limit(exc: Exception) -> bool:
    """Return True when *exc* looks like an HTTP 429 / quota-exceeded error."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "quota" in msg or "resource_exhausted" in msg


def _with_api_retry(fn, *args, **kwargs) -> Any:
    """Invoke *fn(*args, **kwargs)* with up to 3 retries on transient errors.

    Error handling per §6.4:
    - Rate limit (429): pause 60 s, then retry.
    - Other transient errors: exponential back-off of 30 s, 60 s, 120 s.
    - After all retries exhausted: re-raise the last exception.

    Attempt schedule: 1 initial attempt + up to len(_RETRY_BACKOFFS) retries,
    giving 4 total attempts maximum.  The backoff sleep is skipped after the
    final attempt so the caller receives the exception without an extra wait.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + len(_RETRY_BACKOFFS)):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            # All retries exhausted — break immediately without sleeping.
            if attempt == len(_RETRY_BACKOFFS):
                break
            backoff = _RETRY_BACKOFFS[attempt]
            if _is_rate_limit(exc):
                log.warning(
                    "rate_limit_pause",
                    attempt=attempt + 1,
                    wait_s=_RATE_LIMIT_PAUSE_S,
                    error=str(exc),
                )
                time.sleep(_RATE_LIMIT_PAUSE_S)
            else:
                log.warning(
                    "api_retry",
                    attempt=attempt + 1,
                    wait_s=backoff,
                    error=str(exc),
                )
                time.sleep(backoff)

    raise last_exc  # type: ignore[misc]


def _extract_text_from_candidate(candidate) -> str:
    """Pull the text string out of a Gemini Candidate object."""
    return candidate.content.parts[0].text


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_page_prompt(page_text: str) -> str:
    """Return the complete prompt to submit for a single page.

    Prepends the system prompt so that each individual request in the batch
    carries the full extraction instruction set, matching the Gemini Batch
    API's per-request structure (no separate system-message slot in batch
    mode).
    """
    return SYSTEM_PROMPT + "\n\nPage content:\n" + page_text


# ---------------------------------------------------------------------------
# Batch submission
# ---------------------------------------------------------------------------


def submit_batch(page_prompts: list[dict]) -> str:
    """Submit *page_prompts* as a Gemini Batch API job and return the job ID.

    Args:
        page_prompts: List of ``{"url_hash": str, "prompt": str}`` dicts.
            ``url_hash`` is used as the per-request ``custom_id`` so that
            ``parse_batch_results`` can match results back to extraction_log rows.

    Returns:
        Opaque job ID string (``job.name``).

    Note:
        The exact attribute names (``client.batches.create``, ``job.name``,
        ``custom_id``) must be verified against the installed version of
        google-generativeai.  Adjust here if the SDK surface differs.
    """
    genai = _genai()

    requests_payload = [
        {
            "custom_id": item["url_hash"],
            "request": {
                "contents": [
                    {"role": "user", "parts": [{"text": item["prompt"]}]}
                ],
                "generation_config": {
                    "response_mime_type": "application/json",
                    "response_schema": RESPONSE_SCHEMA,
                },
            },
        }
        for item in page_prompts
    ]

    def _do_submit():
        client = genai.Client()
        job = client.batches.create(
            model=f"models/{MODEL_NAME}",
            requests=requests_payload,
        )
        return job.name

    job_id: str = _with_api_retry(_do_submit)
    log.info("batch_submitted", job_id=job_id, request_count=len(page_prompts))
    return job_id


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

# Terminal states reported by the Gemini Batch API
_TERMINAL_SUCCESS = frozenset({"JOB_STATE_SUCCEEDED", "SUCCEEDED", "DONE"})
_TERMINAL_FAILURE = frozenset({"JOB_STATE_FAILED", "JOB_STATE_CANCELLED",
                                "FAILED", "CANCELLED"})


def poll_batch_until_complete(
    job_id: str,
    *,
    _fast_interval: int = _POLL_FAST_INTERVAL_S,
    _slow_interval: int = _POLL_SLOW_INTERVAL_S,
    _fast_threshold: int = _POLL_FAST_THRESHOLD_S,
    _max_wait: int = _POLL_MAX_WAIT_S,
) -> Any:
    """Block until the batch job reaches a terminal state or the timeout fires.

    Polling schedule (§6.1):
        - First 60 minutes  → poll every 5 minutes.
        - After 60 minutes  → poll every 15 minutes.
        - After 6 hours     → raise ``BatchTimeoutError`` and log at CRITICAL.

    All interval parameters are injectable so tests can pass ``_fast_interval=0``
    and ``_max_wait=1`` without sleeping.

    Returns:
        The completed job object (success or failure — caller inspects state).

    Raises:
        BatchTimeoutError: If the job has not completed within *_max_wait* seconds.
    """
    genai = _genai()
    started_at = time.monotonic()

    while True:
        elapsed = time.monotonic() - started_at

        if elapsed >= _max_wait:
            log.critical(
                "batch_timeout",
                job_id=job_id,
                elapsed_hours=round(elapsed / 3600, 2),
            )
            raise BatchTimeoutError(
                f"Batch job {job_id!r} did not complete within "
                f"{_max_wait // 3600} hours."
            )

        def _get_job():
            client = genai.Client()
            return client.batches.get(name=job_id)

        job = _with_api_retry(_get_job)

        # Normalise state: the SDK may return an enum or a string
        state: str = str(getattr(job, "state", "UNKNOWN"))

        if state in _TERMINAL_SUCCESS:
            log.info("batch_succeeded", job_id=job_id, elapsed_s=round(elapsed))
            return job

        if state in _TERMINAL_FAILURE:
            log.error("batch_terminal_failure", job_id=job_id, state=state)
            return job  # extract_pages decides whether to resubmit

        interval = _fast_interval if elapsed < _fast_threshold else _slow_interval
        log.info(
            "batch_polling",
            job_id=job_id,
            state=state,
            elapsed_min=int(elapsed // 60),
            next_poll_min=interval // 60,
        )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------


def parse_llm_response(raw_json_str: str) -> list[dict]:
    """Parse and validate a raw JSON string returned by the Gemini LLM.

    Steps:
      1. Decode JSON — raises ``ValueError`` on any syntax error.
      2. Assert the decoded value is a ``list`` — raises ``ValueError`` if not.
      3. Iterate items: each must be a ``dict`` containing both
         ``grant_title`` and ``confidence_scores`` keys.  Malformed items are
         logged at WARNING and skipped; they do not cause the call to fail.

    Args:
        raw_json_str: The raw text content returned by the Gemini API.

    Returns:
        List of valid grant dicts.  May be empty if no grants were found or
        all items were malformed.

    Raises:
        ValueError: If *raw_json_str* is not valid JSON, or if the decoded
            value is not a JSON list (e.g. an object ``{}``).
    """
    try:
        data = json.loads(raw_json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(
            f"LLM response must be a JSON list; got {type(data).__name__!r}. "
            "Hint: the model may have returned a JSON object instead of an array."
        )

    valid: list[dict] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            log.warning(
                "malformed_item_not_dict",
                index=idx,
                item_type=type(item).__name__,
            )
            continue
        if "grant_title" not in item:
            log.warning("malformed_item_missing_grant_title", index=idx)
            continue
        if "confidence_scores" not in item:
            log.warning("malformed_item_missing_confidence_scores", index=idx)
            continue
        valid.append(item)

    return valid


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------


def parse_batch_results(
    job_id: str,
    claimed_rows: list[dict],
    conn,
) -> tuple[list[dict], list[str]]:
    """Parse a completed batch job's output and update extraction_log rows.

    Per §6.4 partial-failure handling:
    - Successful requests: JSON is parsed and validated as a list.
    - Failed requests: the extraction_log row is marked 'failed' and the
      url_hash collected for retry.

    Args:
        job_id: The Gemini Batch API job identifier.
        claimed_rows: List of extraction_log row dicts (must contain at minimum
            ``id`` and ``url_hash``).
        conn: Live psycopg2 connection for marking row statuses.

    Returns:
        ``(raw_grant_objects, failed_url_hashes)``
        - ``raw_grant_objects``: flat list of raw grant dicts from all pages.
        - ``failed_url_hashes``: url_hashes of requests that failed or had
          unparseable responses — callers may re-submit these.
    """
    genai = _genai()
    row_by_hash: dict[str, dict] = {r["url_hash"]: r for r in claimed_rows}

    raw_grant_objects: list[dict] = []
    failed_url_hashes: list[str] = []

    def _fetch_results():
        client = genai.Client()
        return list(client.batches.get_results(name=job_id))

    results = _with_api_retry(_fetch_results)

    for result in results:
        url_hash: str = getattr(result, "custom_id", "") or ""
        row = row_by_hash.get(url_hash)

        # ── failed request ─────────────────────────────────────────────────
        if getattr(result, "error", None):
            error_msg = str(result.error)
            log.warning(
                "batch_request_failed",
                url_hash=url_hash,
                error=error_msg,
            )
            if row:
                mark_failed(conn, row["id"], error_msg)
            failed_url_hashes.append(url_hash)
            continue

        # ── successful request — parse JSON ────────────────────────────────
        try:
            raw_text: str = _extract_text_from_candidate(
                result.response.candidates[0]
            )
            # parse_llm_response validates list structure and filters malformed
            # items; raises ValueError for invalid JSON or non-list responses.
            grants: list[dict] = parse_llm_response(raw_text)

            for g in grants:
                g["__url_hash"] = url_hash
            raw_grant_objects.extend(grants)

            if row:
                mark_completed(conn, row["id"], records_extracted=len(grants))

            log.info(
                "page_parsed",
                url_hash=url_hash,
                grants_found=len(grants),
            )

        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            # Invalid JSON or unexpected response structure — §6.4
            log.error(
                "parse_error",
                url_hash=url_hash,
                error=str(exc),
            )
            if row:
                mark_failed(conn, row["id"], f"parse_error: {exc}")
            failed_url_hashes.append(url_hash)

    return raw_grant_objects, failed_url_hashes


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def extract_pages(page_contents: list, conn) -> list:
    """Synchronous per-page extraction replacing the broken batch API."""
    import os, time as _t
    import google.genai as _genai
    from google.genai import types as _types
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    client = _genai.Client(api_key=api_key)
    all_grants = []
    for item in page_contents:
        url_hash = item["url_hash"]
        row = item["row"]
        try:
            resp = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=item["prompt"],
                config=_types.GenerateContentConfig(response_mime_type="application/json"),
            )
            grants = parse_llm_response((resp.text or "[]").strip())
            for g in grants:
                g["__url_hash"] = url_hash
            all_grants.extend(grants)
            mark_completed(conn, row["id"], len(grants))
            conn.commit()
            log.info("page_extracted", url_hash=url_hash, grants=len(grants))
        except Exception as exc:
            log.error("extract_failed", url_hash=url_hash, error=str(exc))
            mark_failed(conn, row["id"], f"extraction_error: {exc}")
            conn.commit()
        _t.sleep(0.3)
    return all_grants
