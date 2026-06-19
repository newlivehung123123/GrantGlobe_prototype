# GrantGlobe Stage 3 Fix — Diagnosis and Deployment

12 June 2026

## Why every page returned zero grants

Stage 2 stores each crawled page as `raw_cache/{domain}/{date}/pages/{url_hash}.html`,
but the bytes inside are **gzip-compressed** (`content_storage.py`, line 128:
`gzip.compress(body)`). The file name carries no `.gz` extension. The emergency
patch applied to the server on 3 June read these files with
`read_text(encoding="utf-8", errors="replace")`, which decodes compressed binary
into meaningless replacement characters. BeautifulSoup stripped that noise, the
character-count floor passed it, and Gemini — shown gibberish — correctly
returned `[]` for all 537 completed pages. The manual one-page test that night
made the same mistake (`test_file.read_text()[:8000]`), so its `[]` looked like
confirmation of a yield problem that never existed. The model, the prompt, and
the crawl were all sound.

Three further defects sat behind it and would have struck next:

1. The synchronous patch dropped the response schema, while the strict parser
   silently deletes any grant lacking a `confidence_scores` key — so grants the
   model did find would have been recorded as zero.
2. About ten "Extra data" JSON failures came from prose trailing the array;
   strict `json.loads` rejects the whole response.
3. The PDF path cannot work: Stage 2 never writes the `pdf_text` meta field
   that Stage 3 reads. (Unfixed for now; HTML pages are the volume.)

## What the fixed files change

`batch_processor.py`
- `prepare_html_page` locates `{url_hash}.html` beside the meta sidecar,
  detects the gzip magic number, decompresses, and falls back to a plain
  decode — both storage formats are handled. **This is the decisive fix.**
- `_meta_crawl_date` accepts `crawl_timestamp` (what Stage 2 actually writes)
  as well as `crawl_date`, in both the scanner and the meta index.
- `_count_tokens` uses a local chars/4 estimate instead of one API round-trip
  per page through a deprecated SDK.

`extractor.py`
- `extract_pages` is now a synchronous per-page loop over
  `google-genai` `generate_content` with `gemini-3.5-flash`, temperature 0,
  JSON response type, per-page commit, retry with back-off on 429/503. The
  old Batch API code is preserved as `extract_pages_batch` (the installed SDK
  rejects inline batch payloads, which is why every batch submission failed).
- `OUTPUT_FORMAT_INSTRUCTIONS` is appended to every prompt: it names every
  required key, including `confidence_scores`, replacing the schema
  enforcement the synchronous path lacks.
- `parse_llm_response_tolerant` strips code fences, ignores trailing prose
  (`raw_decode`), and retains grants that lack `confidence_scores` by
  substituting an empty dict — such records route to the review queue rather
  than vanishing.

`scheduler.py`
- The extraction job now runs daily at 03:00 UTC (Stage 2 crawls at 02:00,
  GitHub Actions exports at 07:00) instead of Sundays at 04:00.
- `apply_fix.sh` installs a systemd drop-in setting `STAGE3_FORCE=1`, because
  Stage 2 never writes the `crawl_complete_*.json` sentinel the cycle
  otherwise waits four hours for.

## Deployment — three steps

From your Mac (one command; enter the server password when asked):

    scp -r "/Users/newlivehung/Desktop/14. GrantGlobe/GrantGlobe_prototype/server_fix" root@46.225.65.50:/tmp/

SSH in and install (backs up the old code, installs, syntax-checks, then runs
an eight-page smoke test that prints exactly what Gemini sees and returns):

    ssh -o ServerAliveInterval=30 root@46.225.65.50
    bash /tmp/server_fix/apply_fix.sh

If — and only if — the smoke test prints `VERDICT: PASS`, start the backfill:

    bash /tmp/server_fix/start_full_run.sh

The backfill resets every previously processed row (all were fed corrupted
input) and works through every crawl date in raw_cache. Progress survives SSH
disconnects (`nohup`); check any time with:

    bash /tmp/server_fix/check_status.sh

When the log shows `FULL EXTRACTION RUN COMPLETE`, restart the scheduler so the
pipeline runs daily without intervention:

    systemctl start grantglobe-stage3

## What to expect, stated plainly

- Roughly 4,000+ pages at one synchronous call each: several hours, longer if
  the API rate-limits (the code pauses and retries automatically).
- Most pages are navigation, news, or about pages; a realistic yield is grants
  on perhaps 5–15% of pages. Zero across hundreds of pages would again indicate
  a defect; the smoke test is designed to catch that before the full run.
- **Not every extracted grant appears on the site immediately.** The export
  includes only auto-approved records; anything with a low-confidence or
  unmatched field is held in the review queue
  (`stage3_output/review_queue_{date}.csv`) by design. `check_status.sh`
  reports both counts. If the queue is large, review and approve in batches —
  that is a quality decision, not a defect.

## Honest list of what this does not fix

- PDF extraction stays disabled until Stage 2 stores `pdf_text` (or Stage 3
  reads the stored `.pdf` files directly).
- Stage 2 still never writes the sentinel; `STAGE3_FORCE=1` makes this moot,
  but writing the sentinel at crawl end remains the cleaner design.
- The server previously received ad-hoc `sed` patches; this bundle overwrites
  those files wholesale. Commit `Stage_3_LLM_extraction/stage3/` from this
  repository (already updated identically) so the repo and server match.
- Unit tests written against the old Batch API `extract_pages` will need
  updating; the batch implementation survives as `extract_pages_batch`.
