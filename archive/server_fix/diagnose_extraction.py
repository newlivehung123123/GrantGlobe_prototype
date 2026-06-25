"""
Smoke test for the fixed Stage 3 extraction path. No database writes.

Selects up to eight crawled pages whose URLs suggest grant content, runs
them through the FIXED prepare_html_page (gzip-aware) and the real prompt,
calls gemini-3.5-flash synchronously, and prints what comes back.

Exit codes:
  0 — pipeline works: pages decoded to real text and Gemini responded.
  1 — hard failure: text still garbled, or every API call failed.

A run that exits 0 but finds few grants is NOT a failure: only some of the
sampled pages will be funding announcements. The purpose here is to prove
the plumbing, not to measure yield.
"""

import os
import re
import sys
import json
from pathlib import Path

sys.path.insert(0, "/opt/grantglobe/Stage_3_LLM_extraction")

from stage3.batch_processor import prepare_html_page  # noqa: E402
from stage3.extractor import (  # noqa: E402
    MODEL_NAME,
    build_page_prompt,
    parse_llm_response_tolerant,
)

RAW_CACHE = Path(os.environ.get(
    "RAW_CACHE_DIR", "/opt/grantglobe/Stage_2_crawler/raw_cache"
))
GRANTISH = re.compile(
    r"grant|fund|fellow|scholarship|call|apply|award|opportunit|bourse|beca",
    re.IGNORECASE,
)
MAX_PAGES = 8


def pick_candidate_pages() -> list[Path]:
    """Return up to MAX_PAGES meta files with grant-suggestive URLs,
    at most one per domain so the sample spans funders."""
    chosen: dict[str, Path] = {}
    fallback: dict[str, Path] = {}
    for meta_path in RAW_CACHE.rglob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        domain = meta.get("domain") or "unknown"
        url = meta.get("url") or ""
        html_file = meta_path.with_name(meta_path.name.replace(".meta.json", ".html"))
        if not html_file.exists():
            continue
        if GRANTISH.search(url):
            chosen.setdefault(domain, meta_path)
        else:
            fallback.setdefault(domain, meta_path)
        if len(chosen) >= MAX_PAGES:
            break
    picks = list(chosen.values())[:MAX_PAGES]
    if len(picks) < MAX_PAGES:
        for domain, p in fallback.items():
            if len(picks) >= MAX_PAGES:
                break
            if domain not in chosen:
                picks.append(p)
    return picks


def mojibake_ratio(text: str) -> float:
    if not text:
        return 1.0
    return text.count("�") / len(text)


def main() -> int:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("FATAL: no GOOGLE_API_KEY / GEMINI_API_KEY in environment")
        return 1

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.0
    )

    pages = pick_candidate_pages()
    if not pages:
        print("FATAL: no candidate pages found in raw_cache")
        return 1

    api_ok = 0
    decode_ok = 0
    total_grants = 0

    for meta_path in pages:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        url = meta.get("url") or "?"
        print("=" * 78)
        print("URL:", url)

        text, reason = prepare_html_page(meta_path, RAW_CACHE, MODEL_NAME)
        if text is None:
            print("  prepare skipped/failed:", reason)
            continue

        ratio = mojibake_ratio(text)
        snippet = text[:220].replace("\n", " ")
        print(f"  text: {len(text)} chars, mojibake ratio {ratio:.3f}")
        print(f"  snippet: {snippet!r}")
        if ratio > 0.05:
            print("  >> TEXT STILL GARBLED — gzip fix did not take effect")
            continue
        decode_ok += 1

        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=build_page_prompt(text),
                config=config,
            )
            raw = (resp.text or "").strip()
            api_ok += 1
            print(f"  gemini raw (first 300): {raw[:300]!r}")
            grants = parse_llm_response_tolerant(raw) if raw else []
            total_grants += len(grants)
            print(f"  grants parsed: {len(grants)}")
            for g in grants[:3]:
                print(f"    - {g.get('grant_title')!r} / {g.get('funder_name')!r}")
        except Exception as exc:  # noqa: BLE001
            print("  GEMINI CALL FAILED:", exc)

    print("=" * 78)
    print(
        f"SUMMARY: {len(pages)} sampled | {decode_ok} decoded cleanly | "
        f"{api_ok} API calls succeeded | {total_grants} grants parsed"
    )

    if decode_ok == 0:
        print("VERDICT: FAIL — pages are still not decoding to readable text.")
        return 1
    if api_ok == 0:
        print("VERDICT: FAIL — no Gemini call succeeded.")
        return 1
    print("VERDICT: PASS — plumbing works. Yield judgement requires the full run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
