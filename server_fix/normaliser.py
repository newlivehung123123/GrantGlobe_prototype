"""
Normalisation layer — maps raw LLM output to standards before database insertion.

All lookup files are loaded once at module import time.
"""

import json
import hashlib
import os
import unicodedata
import re
import structlog
from datetime import date, datetime, timezone
from pathlib import Path

from dateutil import parser as dateutil_parser
from rapidfuzz import fuzz

DATA_DIR = Path(__file__).parent.parent / "data"

log = structlog.get_logger(__name__)

# Load all lookup files at import time so disk I/O only happens once per process.
COUNTRY_LOOKUP   = json.loads((DATA_DIR / "country_lookup.json").read_text())
REGION_LOOKUP    = json.loads((DATA_DIR / "region_lookup.json").read_text())
CURRENCY_LOOKUP  = json.loads((DATA_DIR / "currency_lookup.json").read_text())
FUNDER_AUTHORITY = json.loads((DATA_DIR / "funder_authority.json").read_text())
SUPRANATIONAL    = json.loads((DATA_DIR / "supranational_groups.json").read_text())


# ---------------------------------------------------------------------------
# Grant title
# ---------------------------------------------------------------------------

# One or more terminal punctuation characters that should be stripped
# from normalised grant titles (unless the final character is ? or !).
_TERMINAL_PUNCT_RE = re.compile(r"[.,;:\-—…]+$")


def normalise_grant_title(raw: str | None) -> str | None:
    """Strip whitespace, apply title case, and remove trailing punctuation.

    Args:
        raw: The raw grant_title string extracted by the LLM.

    Returns:
        Normalised title string, or ``None`` if *raw* is ``None`` or blank.
    """
    if not raw or not raw.strip():
        return None

    title = raw.strip().title()

    # Preserve intentional question / exclamation marks; strip everything else.
    if title[-1] not in ("?", "!"):
        title = _TERMINAL_PUNCT_RE.sub("", title).rstrip()

    return title or None


# ---------------------------------------------------------------------------
# Funder name
# ---------------------------------------------------------------------------


def normalise_funder_name(raw: str | None) -> dict:
    """Resolve a raw funder name to its canonical form via FUNDER_AUTHORITY.

    Lookup strategy (§7.2):
    1. Exact match on lowercased/stripped key.
    2. Fuzzy match via ``fuzz.ratio()`` at threshold ≥ 90 across all keys.
    3. Unmatched: return raw string with ``unmatched=True`` flag.

    Args:
        raw: Raw funder name as extracted by the LLM.

    Returns:
        Dict with keys ``canonical_name`` and ``ror_id``.
        Unmatched results additionally contain ``unmatched: True``.
    """
    if not raw or not raw.strip():
        return {"canonical_name": raw, "ror_id": None, "unmatched": True}

    key = raw.lower().strip()

    # 1 — exact match
    if key in FUNDER_AUTHORITY:
        entry = FUNDER_AUTHORITY[key]
        return {"canonical_name": entry["canonical_name"], "ror_id": entry["ror_id"]}

    # 2 — fuzzy match
    best_score = 0
    best_key: str | None = None
    for fa_key in FUNDER_AUTHORITY:
        score = fuzz.ratio(key, fa_key)
        if score > best_score:
            best_score = score
            best_key = fa_key

    if best_score >= 90 and best_key is not None:
        entry = FUNDER_AUTHORITY[best_key]
        log.debug(
            "funder_fuzzy_matched",
            raw=raw,
            matched_key=best_key,
            score=best_score,
        )
        return {"canonical_name": entry["canonical_name"], "ror_id": entry["ror_id"]}

    # 3 — unmatched
    log.debug("unmatched_funder", funder=raw)
    return {"canonical_name": raw, "ror_id": None, "unmatched": True}


# ---------------------------------------------------------------------------
# Deadline / grant opening date
# ---------------------------------------------------------------------------

_ROLLING_PHRASES = ("rolling", "open continuously", "no deadline", "ongoing")
_TBC_PHRASES = ("tbc", "to be confirmed", "coming soon", "tba")


def normalise_deadline(raw_str: str | None, confidence: str) -> dict:
    """Parse a raw deadline string and classify its type.

    Returns a dict ``{"date": date | None, "type": str}`` where ``type``
    is one of: ``"rolling"``, ``"tbc"``, ``"not_published"``,
    ``"unextracted"``, ``"confirmed"``.

    Type is determined in strict priority order (§7.2):

    1. ``"rolling"``       — raw string contains a rolling-deadline phrase.
    2. ``"tbc"``           — raw string contains a TBC phrase.
    3. ``"not_published"`` — raw is ``None`` and confidence is ``"not_found"``.
    4. ``"unextracted"``   — raw is ``None`` and confidence is ``"low"``/``"medium"``.
    5. ``"confirmed"``     — dateutil successfully parses the string.
    6. ``"unextracted"``   — parse failed.

    Args:
        raw_str: The raw date string from the LLM (may be ``None``).
        confidence: The confidence label for this field (``"high"``,
            ``"medium"``, ``"low"``, ``"not_found"``).

    Returns:
        ``{"date": datetime.date | None, "type": str}``
    """
    if raw_str is not None:
        raw_lower = raw_str.lower()

        if any(phrase in raw_lower for phrase in _ROLLING_PHRASES):
            return {"date": None, "type": "rolling"}

        if any(phrase in raw_lower for phrase in _TBC_PHRASES):
            return {"date": None, "type": "tbc"}

        try:
            # dayfirst=True handles the European DD/MM/YYYY convention.
            # yearfirst=False is the default; dayfirst takes precedence for
            # ambiguous inputs like "01/02/2026" → 1 Feb 2026, not 2 Jan.
            parsed_dt = dateutil_parser.parse(raw_str, dayfirst=True)
            return {"date": parsed_dt.date(), "type": "confirmed"}
        except (ValueError, OverflowError):
            return {"date": None, "type": "unextracted"}

    # raw_str is None — classify by confidence
    if confidence == "not_found":
        return {"date": None, "type": "not_published"}

    return {"date": None, "type": "unextracted"}


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


def normalise_currency(raw_str: str | None) -> str:
    """Resolve a raw currency symbol, name, or abbreviation to ISO 4217.

    Args:
        raw_str: Raw currency string from the LLM (e.g. ``"£"``, ``"USD"``).

    Returns:
        ISO 4217 three-letter code (e.g. ``"GBP"``), or ``"OTH"`` if
        unrecognised.
    """
    if not raw_str or not raw_str.strip():
        return "OTH"

    key = raw_str.lower().strip()
    if key in CURRENCY_LOOKUP:
        return CURRENCY_LOOKUP[key]

    log.debug("unmatched_currency", currency=raw_str)
    return "OTH"


# ---------------------------------------------------------------------------
# Source language
# ---------------------------------------------------------------------------

LANG_MAP: dict[str, str] = {
    "english": "en",          "en": "en",
    "french": "fr",           "fr": "fr",            "français": "fr",
    "spanish": "es",          "es": "es",            "español": "es",
    "arabic": "ar",           "ar": "ar",
    "portuguese": "pt",       "pt": "pt",
    "chinese": "zh-hans",     "simplified chinese": "zh-hans",
    "zh-hans": "zh-hans",
    "traditional chinese": "zh-hant",
    "zh-hant": "zh-hant",
    "japanese": "ja",         "ja": "ja",
    "korean": "ko",           "ko": "ko",
    "german": "de",           "de": "de",
    "dutch": "nl",            "nl": "nl",
    "russian": "ru",          "ru": "ru",
    "italian": "it",          "it": "it",
    "swedish": "sv",          "sv": "sv",
    "norwegian": "no",        "no": "no",
    "danish": "da",           "da": "da",
}


def normalise_source_language(raw_str: str | None) -> str:
    """Map a raw language name or code to an ISO 639-1 code.

    Args:
        raw_str: Raw language string from the LLM (e.g. ``"English"``,
            ``"en"``, ``"français"``).

    Returns:
        ISO 639-1 code (``"en"``, ``"fr"``, etc.), ``"zh-hans"``,
        ``"zh-hant"``, or ``"ot"`` for unrecognised languages.
    """
    if not raw_str or not raw_str.strip():
        return "ot"

    key = raw_str.lower().strip()
    return LANG_MAP.get(key, "ot")


# ---------------------------------------------------------------------------
# Country normalisation
# ---------------------------------------------------------------------------


def normalise_country(raw_str: str | None) -> str:
    """Resolve a raw country/territory string to an ISO 3166-1 alpha-2 code.

    Lookup strategy (§7.2):
    1. Exact match on lowercased/stripped key in ``COUNTRY_LOOKUP``.
    2. Fuzzy match via ``fuzz.ratio()`` at threshold ≥ 88.
    3. Unmatched → ``"OT"`` plus a ``DEBUG`` log.

    Args:
        raw_str: Raw country string from the LLM.

    Returns:
        ISO 3166-1 alpha-2 code (e.g. ``"GB"``), or ``"OT"`` (Others).
    """
    if not raw_str or not raw_str.strip():
        return "OT"

    key = raw_str.lower().strip()

    # 1 — exact match
    if key in COUNTRY_LOOKUP:
        return COUNTRY_LOOKUP[key]

    # 2 — fuzzy match
    best_score = 0
    best_key: str | None = None
    for ck in COUNTRY_LOOKUP:
        score = fuzz.ratio(key, ck)
        if score > best_score:
            best_score = score
            best_key = ck

    if best_score >= 88 and best_key is not None:
        log.debug(
            "country_fuzzy_matched",
            raw=raw_str,
            matched_key=best_key,
            score=best_score,
        )
        return COUNTRY_LOOKUP[best_key]

    log.debug("unmatched_country", country=raw_str)
    return "OT"


# ---------------------------------------------------------------------------
# Supranational group expansion
# ---------------------------------------------------------------------------

# Build a lowercased key → canonical key index once at import time so
# expand_supranational_group avoids rebuilding it on every call.
_SUPRA_INDEX: dict[str, str] = {k.lower(): k for k in SUPRANATIONAL}


def expand_supranational_group(raw_str: str | None) -> list[str] | None:
    """Return the constituent ISO alpha-2 codes for a supranational group name.

    Args:
        raw_str: Raw geographic string (e.g. ``"EU Member States"``).

    Returns:
        List of ISO alpha-2 codes if *raw_str* matches a supranational group,
        otherwise ``None``.
    """
    if not raw_str or not raw_str.strip():
        return None

    canonical = _SUPRA_INDEX.get(raw_str.lower().strip())
    if canonical is not None:
        return SUPRANATIONAL[canonical]
    return None


# ---------------------------------------------------------------------------
# Region normalisation
# ---------------------------------------------------------------------------


def normalise_region(raw_str: str | None) -> str:
    """Map a raw region string to a UN M.49 canonical label.

    Args:
        raw_str: Raw region string from the LLM.

    Returns:
        Canonical region label (e.g. ``"Sub-Saharan Africa"``), or
        ``"Others"`` if unmatched.
    """
    if not raw_str or not raw_str.strip():
        return "Others"

    key = raw_str.lower().strip()
    return REGION_LOOKUP.get(key, "Others")


# ---------------------------------------------------------------------------
# Geographic list normalisation
# ---------------------------------------------------------------------------


def normalise_geographic_list(raw_list: list[str] | None) -> dict:
    """Normalise a raw geographic_focus list into region labels and country codes.

    For each item in *raw_list* (§7.2):
    1. Try supranational group expansion first. On a match: add the canonical
       group name to *regions* and all constituent ISO codes to *countries*.
    2. Otherwise: run ``normalise_country`` and append the result (valid code
       or ``"OT"``) to *countries*; also run ``normalise_region`` and, if the
       result is not ``"Others"``, append it to *regions*.

    Args:
        raw_list: List of raw geographic strings from the LLM
            (e.g. ``["EU Member States", "Kenya", "South Asia"]``).

    Returns:
        ``{"regions": list[str], "countries": list[str]}``
    """
    regions: list[str] = []
    countries: list[str] = []

    if not raw_list:
        return {"regions": regions, "countries": countries}

    for item in raw_list:
        if not item or not item.strip():
            continue

        # 1 — supranational group
        codes = expand_supranational_group(item)
        if codes is not None:
            canonical_name = _SUPRA_INDEX[item.lower().strip()]
            regions.append(canonical_name)
            countries.extend(codes)
            continue

        # 2 — individual country / region
        country_code = normalise_country(item)
        countries.append(country_code)

        region_label = normalise_region(item)
        if region_label != "Others":
            regions.append(region_label)

    return {"regions": regions, "countries": countries}


# ---------------------------------------------------------------------------
# Controlled vocabulary normalisation
# ---------------------------------------------------------------------------


_VOCAB_FUZZY_THRESHOLD = 85
_VOCAB_TOKEN_SET_THRESHOLD = 90


# ---------------------------------------------------------------------------
# Curated alias tables — raw LLM terms (lowercase) that are semantically clear
# but don't fuzzy-match the controlled vocab closely enough (either because
# the canonical entry uses very different wording, or the term is a narrower
# concept that fits within a broader canonical category). Checked before
# exact/fuzzy/token-set matching.
# ---------------------------------------------------------------------------

THEMATIC_SECTORS_ALIASES: dict[str, str] = {
    "arts and cultural exchange": "Arts, Culture and Heritage",
    "visual arts": "Arts, Culture and Heritage",
    "performing arts": "Arts, Culture and Heritage",
    "arts and culture": "Arts, Culture and Heritage",
    "higher education": "Education and Training",
    "civil security for society": "Peace and Security",
    "artificial intelligence": "Digital Technology and Innovation",
    "research and innovation": "Digital Technology and Innovation",
    "agricultural sciences": "Agriculture and Food Security",
    "social sciences": "Social Sciences and Humanities",
    "humanities": "Social Sciences and Humanities",
    "social sciences and humanities": "Social Sciences and Humanities",
    "japanese studies": "Social Sciences and Humanities",
    "japanese-language education": "Social Sciences and Humanities",
    "science": "Natural and Physical Sciences",
    "physics": "Natural and Physical Sciences",
    "chemical sciences": "Natural and Physical Sciences",
    "mathematical sciences": "Natural and Physical Sciences",
    "biologie": "Natural and Physical Sciences",
    "hoger onderwijs": "Education and Training",          # Dutch: higher education
    "onderwijs": "Education and Training",                # Dutch: education
    "onderwijsinnovatie": "Education and Training",       # Dutch: education innovation
    "日本語教育": "Education and Training",                 # Japanese: Japanese-language education
    "open science": "Digital Technology and Innovation",
    "cybersecurity": "Digital Technology and Innovation",
    "technische wetenschappen": "Digital Technology and Innovation",  # Dutch: technical sciences
    "i+d+i": "Digital Technology and Innovation",          # Spanish: R&D&i
    "01-agricultural sciences": "Agriculture and Food Security",
    "agriculture, forestry and rural areas": "Agriculture and Food Security",
    "food, bioeconomy, natural resources, agriculture and environment": "Agriculture and Food Security",
    "02-structural, cell and molecular biology": "Natural and Physical Sciences",
    "03-biological systems and organisms": "Natural and Physical Sciences",
    "05-chemical sciences": "Natural and Physical Sciences",
    "08-mathematical sciences": "Natural and Physical Sciences",
    "09-physics": "Natural and Physical Sciences",
    "ontwerpwetenschappen": "Natural and Physical Sciences",       # Dutch: design sciences
    "levenswetenschappen": "Natural and Physical Sciences",        # Dutch: life sciences
    "natuurwetenschap en techniek": "Natural and Physical Sciences",  # Dutch: natural science and technology
    "medische wetenschappen": "Health and Medical Research",       # Dutch: medical sciences
    "04-medical and health sciences incl. neurosciences": "Health and Medical Research",
    "geneeskunde": "Health and Medical Research",                  # Dutch: medicine
    "levenswetenschappen en geneeskunde": "Health and Medical Research",  # Dutch: life sciences and medicine
    "salud": "Health and Medical Research",                        # Spanish: health
    "milieuwetenschap": "Climate Change and Environment",          # Dutch: environmental science
    "sociologie": "Social Sciences and Humanities",                # Dutch: sociology
    "bedrijfskunde": "Economic Development and Livelihoods",       # Dutch: business administration
    "economie": "Economic Development and Livelihoods",            # Dutch: economics
    "global partnerships": "Economic Development and Livelihoods",
    "public policy": "Democracy, Governance and Accountability",
    "international relations": "Peace and Security",
    "cultural exchange": "Arts, Culture and Heritage",
    # Missing high-frequency terms from DB analysis (2026-06-16)
    "science, technology, engineering and mathematics (stem)": "Natural and Physical Sciences",
    "stem": "Natural and Physical Sciences",
    "education": "Education and Training",
    "agriculture": "Agriculture and Food Security",
    "technology": "Digital Technology and Innovation",
    "health": "Health and Medical Research",
    "engineering": "Natural and Physical Sciences",
    "mathematics": "Natural and Physical Sciences",
    "climate change": "Climate Change and Environment",
    "chemistry": "Natural and Physical Sciences",
    "biology": "Natural and Physical Sciences",
    "biodiversity and conservation": "Climate Change and Environment",
    "biodiversity": "Climate Change and Environment",
    "economics": "Economic Development and Livelihoods",
    "innovation": "Digital Technology and Innovation",
    "energy": "Climate Change and Environment",
    "circular economy": "Climate Change and Environment",
    "bioeconomy": "Agriculture and Food Security",
    "natural resources": "Climate Change and Environment",
    "environment": "Climate Change and Environment",
    "production economics": "Economic Development and Livelihoods",
    "economics and business economics": "Economic Development and Livelihoods",
    "social science": "Social Sciences and Humanities",
}

ORG_TYPES_ALIASES: dict[str, str] = {
    # English variants
    "university": "University / Higher Education Institution",
    "universities": "University / Higher Education Institution",
    "higher education institutions": "University / Higher Education Institution",
    "higher education institution": "University / Higher Education Institution",
    "higher education establishments": "University / Higher Education Institution",
    "higher or secondary education establishments": "University / Higher Education Institution",
    "universities of applied sciences": "University / Higher Education Institution",
    "university of applied sciences": "University / Higher Education Institution",
    "higher vocational education (hbo)": "University / Higher Education Institution",
    "scientific education (wo)": "University / Higher Education Institution",
    "knowledge institutions": "University / Higher Education Institution",
    "educational institution": "University / Higher Education Institution",
    "educational institutions": "University / Higher Education Institution",
    "research organisations": "Research Institution / Think Tank",
    "research organization": "Research Institution / Think Tank",
    "research organizations": "Research Institution / Think Tank",
    "research organisation": "Research Institution / Think Tank",
    "research institute": "Research Institution / Think Tank",
    "research institutes": "Research Institution / Think Tank",
    "government": "Government / Public Authority",
    "governments": "Government / Public Authority",
    "public authority": "Government / Public Authority",
    "public authorities": "Government / Public Authority",
    "business": "Private Sector / For-Profit Company",
    "businesses": "Private Sector / For-Profit Company",
    "company": "Private Sector / For-Profit Company",
    "companies": "Private Sector / For-Profit Company",
    "sme": "Private Sector / For-Profit Company",
    "smes": "Private Sector / For-Profit Company",
    # Dutch
    "hogescholen": "University / Higher Education Institution",       # universities of applied sciences
    "universiteiten": "University / Higher Education Institution",    # universities
    "kennisinstellingen": "University / Higher Education Institution",# knowledge institutions
    "onderzoeksinstellingen": "Research Institution / Think Tank",    # research institutions
    "overheden": "Government / Public Authority",                     # governments
    "bedrijven": "Private Sector / For-Profit Company",              # companies
    # French
    "universités": "University / Higher Education Institution",
    "établissements d'enseignement supérieur": "University / Higher Education Institution",
    "organismes de recherche": "Research Institution / Think Tank",
    # Spanish
    "universidades": "University / Higher Education Institution",
    "organizaciones de investigación": "Research Institution / Think Tank",
    "empresas": "Private Sector / For-Profit Company",
}

INDIV_ELIGIBILITY_ALIASES: dict[str, str] = {
    "researchers": "Researcher (any career stage)",
    "onderzoekers": "Researcher (any career stage)",
    "phd candidates": "Early Career Researcher (includes PhD candidates)",
    "postdocs": "Early Career Researcher (includes PhD candidates)",
    "postdoctoral researchers": "Early Career Researcher (includes PhD candidates)",
    "artists": "Artist / Creative",
    "curators": "Artist / Creative",
    "translators": "Artist / Creative",
    "researchers at the stage of consolidation and further development of their leadership/research group": "Senior / Established Researcher or Professional",
    "experienced researchers": "Senior / Established Researcher or Professional",
    "advanced researchers": "Senior / Established Researcher or Professional",
    "chercheurs seniors": "Senior / Established Researcher or Professional",          # French: senior researchers
    "international anerkannte wissenschaftler*innen": "Senior / Established Researcher or Professional",  # German: internationally recognised scientists
    "full, associate and assistant professors": "Senior / Established Researcher or Professional",
    "professors": "Senior / Established Researcher or Professional",
    "fellows": "Researcher (any career stage)",
    "research and innovation staff": "Researcher (any career stage)",
    "naukowców na każdym etapie kariery": "Researcher (any career stage)",            # Polish: researchers at every career stage
    "jeunes chercheurs": "Early Career Researcher (includes PhD candidates)",         # French: young researchers
    "postdoctoral fellows": "Early Career Researcher (includes PhD candidates)",
    "teachers": "Professional / Practitioner",
    "leraren": "Professional / Practitioner",                                          # Dutch: teachers
    "lectoren": "Professional / Practitioner",                                         # Dutch: lecturers
    "hbo-professionals": "Professional / Practitioner",                                # Dutch: applied-sciences professionals
    "educational professionals": "Professional / Practitioner",
    "professionals in higher education": "Professional / Practitioner",
    "faculty": "Professional / Practitioner",
    "scholars": "Independent Scholar",
    "leaders": "Activist / Community Leader",
    "youth": "Any Individual (no career stage or profession restriction)",
    "hoofdaanvrager": "Any Individual (no career stage or profession restriction)",    # Dutch: main applicant
    "medeaanvrager(s)": "Any Individual (no career stage or profession restriction)",  # Dutch: co-applicant(s)
}


def _translate_to_english(text: str) -> str | None:
    """Best-effort translation of *text* to English.

    Returns ``None`` (rather than raising) on any failure — translation is a
    fallback step only, and a network/library error must not break
    extraction. Requires the optional ``deep-translator`` package; if it is
    not installed, returns ``None`` immediately.
    """
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        return None

    try:
        translated = GoogleTranslator(source="auto", target="en").translate(text)
        if translated and translated.strip().lower() != text.strip().lower():
            return translated
    except Exception as exc:  # noqa: BLE001 - translation is best-effort
        log.debug("translation_failed", text=text, error=str(exc))
    return None


def _match_vocab_term(
    key: str,
    vocab_lower: dict[str, str],
    aliases: dict[str, str] | None,
) -> tuple[str | None, str | None, float]:
    """Attempt to match *key* (already lowercased/stripped) against the vocab.

    Returns ``(canonical, method, score)`` — ``canonical`` is ``None`` if
    nothing matched at any tier.
    """
    # 0 — curated alias
    if aliases and key in aliases:
        return aliases[key], "alias", 100.0

    # 1 — exact match
    if key in vocab_lower:
        return vocab_lower[key], "exact", 100.0

    # 2 — fuzzy match (full-string)
    best_score = 0.0
    best_canonical: str | None = None
    for v_lower, v_canonical in vocab_lower.items():
        score = fuzz.ratio(key, v_lower)
        if score > best_score:
            best_score = score
            best_canonical = v_canonical

    if best_score >= _VOCAB_FUZZY_THRESHOLD and best_canonical is not None:
        return best_canonical, "fuzzy", best_score

    # 3 — token-set fuzzy match
    best_ts_score = 0.0
    best_ts_canonical: str | None = None
    for v_lower, v_canonical in vocab_lower.items():
        score = fuzz.token_set_ratio(key, v_lower)
        if score > best_ts_score:
            best_ts_score = score
            best_ts_canonical = v_canonical

    if best_ts_score >= _VOCAB_TOKEN_SET_THRESHOLD and best_ts_canonical is not None:
        return best_ts_canonical, "token_set", best_ts_score

    return None, None, 0.0


def normalise_controlled_vocab(
    raw_list: list[str] | None,
    vocab_list: list[str],
    aliases: dict[str, str] | None = None,
) -> list[str]:
    """Map each raw string to an entry in *vocab_list*.

    Lookup strategy (mirrors ``normalise_funder_name`` / ``normalise_country``):
    1. Exact match, case-insensitive.
    2. Fuzzy match via ``fuzz.ratio()`` at threshold >= 85 against all vocab
       entries (catches synonyms/abbreviations and punctuation/dash variants
       such as "Student - Postgraduate / PhD" vs "Student — Postgraduate / PhD").
    3. Token-set fuzzy match via ``fuzz.token_set_ratio()`` at threshold >= 90
       (catches short/generic terms that are a subset of a longer canonical
       entry, e.g. "Science" -> "Science and Technology", "Researchers" ->
       "Senior / Established Researcher or Professional", "Health" ->
       "Health Research"; ``fuzz.ratio()`` scores these too low because of
       the length difference, but token_set_ratio scores a clean subset
       relationship at or near 100).
    4. Unmatched: replaced with ``"Others"`` and logged at ``DEBUG``.

    Raw strings are preserved in ``raw_extraction`` by the caller.

    Args:
        raw_list: Raw strings from the LLM (e.g. organisation_types_raw).
        vocab_list: Canonical controlled vocabulary entries.

    Returns:
        List of canonical strings (may include ``"Others"``).
    """
    if not raw_list:
        return []

    # Build lowercase → canonical lookup once per call (vocab_list is small).
    vocab_lower: dict[str, str] = {v.lower(): v for v in vocab_list}

    result: list[str] = []
    for item in raw_list:
        if not item or not item.strip():
            continue
        key = item.lower().strip()

        canonical, method, score = _match_vocab_term(key, vocab_lower, aliases)

        # 5 — translation fallback: if nothing matched and the term contains
        # non-ASCII characters (heuristic for "not English"), translate to
        # English and retry the same alias/exact/fuzzy/token-set sequence.
        if canonical is None and not key.isascii():
            translated = _translate_to_english(item.strip())
            if translated:
                t_key = translated.lower().strip()
                canonical, method, score = _match_vocab_term(t_key, vocab_lower, aliases)
                if canonical is not None:
                    log.debug(
                        "vocab_translated_then_matched",
                        item=item,
                        translated=translated,
                        matched=canonical,
                        method=method,
                        score=score,
                    )

        if canonical is not None:
            if method != "exact":
                log.debug(
                    f"vocab_{method}_matched",
                    item=item,
                    matched=canonical,
                    score=score,
                )
            result.append(canonical)
            continue

        # unmatched
        log.debug("unmatched_vocab_item", item=item)
        result.append("Others")

    return result


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


def compute_content_hash(funder_name: str, grant_title: str) -> str:
    """SHA-256 of NFKC-normalised, lowercased funder_name + '||' + grant_title.

    Deadline is excluded: deadline extensions must update the record, not
    duplicate it.

    Known limitation: two grants from the same funder with identical titles
    (e.g. 'Innovation Fund' as both a Research Grant and a Fellowship) will
    collide. This is surfaced as records_duplicate_lower_confidence in the QA
    report.
    """
    def _norm(s: str) -> str:
        return unicodedata.normalize("NFKC", s).lower().strip()

    combined = _norm(funder_name) + "||" + _norm(grant_title)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Aggregate confidence score
# ---------------------------------------------------------------------------

_CONF_INT: dict[str, int] = {"high": 3, "medium": 2, "low": 1, "not_found": 0}


def aggregate_confidence_score(confidence_scores: dict) -> int:
    """Sum integer confidence values across all scored fields.

    ``high`` = 3, ``medium`` = 2, ``low`` = 1, ``not_found`` = 0.
    Unrecognised labels contribute 0.
    """
    return sum(_CONF_INT.get(v, 0) for v in confidence_scores.values())


# ---------------------------------------------------------------------------
# Review flag determination
# ---------------------------------------------------------------------------

# Array fields checked under R5 (§5.2): thematic_sectors, geographic_focus,
# individual_eligibility.  geographic_focus_regions is the normalised field
# name for geographic_focus in the record dict.
# NOTE: organisation_types is NOT in the spec's R5 list and must not be added here.
_R5_ARRAY_FIELDS = (
    "thematic_sectors",
    "geographic_focus_regions",
    "individual_eligibility",
)


def determine_review_flag(record: dict, threshold: str = "low") -> bool:
    """Apply §5.2 review flag rules and return True if the record needs review.

    Args:
        record: Normalised grant record dict.  Expected keys:
            ``confidence_scores`` (dict), ``application_deadline_type`` (str),
            ``current_status`` (str), ``thematic_sectors`` (list),
            ``geographic_focus_regions`` (list), ``individual_eligibility``
            (list), ``organisation_types`` (list),
            ``individuals_not_eligible`` (bool | None).
        threshold: ``"low"`` (default) or ``"medium"``.  Overridden by the
            ``STAGE3_REVIEW_CONFIDENCE_THRESHOLD`` environment variable when
            set — the env var takes precedence over the argument default,
            allowing callers to explicitly pass a value while still supporting
            env-based configuration for production runs.

    Returns:
        ``True`` if any rule fires, ``False`` otherwise.
    """
    threshold = os.environ.get("STAGE3_REVIEW_CONFIDENCE_THRESHOLD", threshold)

    if threshold == "medium":
        trigger_set: frozenset[str] = frozenset({"medium", "low", "not_found"})
    else:
        trigger_set = frozenset({"low", "not_found"})

    cs: dict = record.get("confidence_scores", {})

    # R1 — grant title confidence
    if cs.get("grant_title") in trigger_set:
        return True

    # R2 — funder name confidence
    if cs.get("funder_name") in trigger_set:
        return True

    # R3 — deadline confidence AND type is not an excused category
    _deadline_excused = frozenset({"rolling", "tbc", "not_published"})
    if (
        cs.get("application_deadline") in trigger_set
        and record.get("application_deadline_type") not in _deadline_excused
    ):
        return True

    # R4 — current_status is Others
    if record.get("current_status") == "Others":
        return True

    # R5 — a non-empty array field is ENTIRELY "Others" (i.e. nothing in
    # that field matched the controlled vocabulary at all). A field that
    # mixes "Others" with at least one recognised term is not flagged,
    # since the record still carries usable categorisation.
    for field in _R5_ARRAY_FIELDS:
        arr = record.get(field) or []
        if arr and all(x == "Others" for x in arr):
            return True

    # R6 — ai_focused confidence (fixed threshold — medium does NOT trigger R6)
    if cs.get("ai_focused") in {"low", "not_found"}:
        return True

    # R7 — individuals_not_eligible could not be determined
    if record.get("individuals_not_eligible") is None:
        return True

    return False


# ---------------------------------------------------------------------------
# Status auto-computation
# ---------------------------------------------------------------------------

_STATUS_VOCAB: list[str] = [
    "Open", "Closed", "Upcoming", "Rolling", "Suspended", "Others"
]
_STATUS_VOCAB_LOWER: dict[str, str] = {v.lower(): v for v in _STATUS_VOCAB}

# Curated aliases for current_status_raw values that are valid synonyms or
# non-English equivalents of a _STATUS_VOCAB entry but score below
# _VOCAB_FUZZY_THRESHOLD on fuzz.ratio (e.g. "Gesloten" vs "Closed" = 50).
# Many of these are Latin-script non-English terms (Dutch, French, Polish)
# that the non-ASCII translation-trigger heuristic used elsewhere would not
# catch, so they are handled directly here. Keys are lowercase/stripped.
_STATUS_ALIASES: dict[str, str] = {
    # Closed
    "gesloten": "Closed",                # Dutch: closed
    "clos": "Closed",                    # French: closed
    "project closed": "Closed",
    "the call is closed": "Closed",
    "inactive/archive": "Closed",
    "inactive": "Closed",
    "archive": "Closed",
    "brak aktualnie otwartego konkursu": "Closed",  # Polish: no call currently open
    "expired": "Closed",
    "ended": "Closed",
    "finished": "Closed",
    "terminated": "Closed",
    "selected": "Closed",
    "終了": "Closed",                    # Japanese: ended/closed
    # Open
    "open for applications": "Open",
    "open calls": "Open",
    "open voor aanvragen": "Open",       # Dutch: open for applications
    "ouvert": "Open",                    # French: open
    "open for letter of intent": "Open",
    "otwarte": "Open",                   # Polish: open
    "active": "Open",
    "current initiative": "Open",
    # Rolling
    "continuous": "Rolling",
    "doorlopend": "Rolling",             # Dutch: ongoing/continuous
    "ongoing": "Rolling",
    # Upcoming
    "in preparation": "Upcoming",
    "in voorbereiding": "Upcoming",      # Dutch: in preparation
    # Suspended
    "no call will open in 2026": "Suspended",
    "no no call will open in 2026": "Suspended",
    "the programme has been discountinued": "Suspended",   # typo as extracted
    "the programme has been discontinued": "Suspended",
    # Open (additional)
    "appel en cours": "Open",                              # French: call in progress
    "open call": "Open",
    "open voor intentieverklaring": "Open",                # Dutch: open for letter of intent
    "applications for fy2026 are now open": "Open",
    "open calls for students": "Open",
    "open for pre-proposals": "Open",
    "call for applications": "Open",
    "published": "Open",
    # Closed (additional)
    "grants awarded": "Closed",
    "approved": "Closed",
    "applications are closed": "Closed",
    "expired calls": "Closed",
    "wyniki konkursu": "Closed",                           # Polish: competition results
    "appels clos": "Closed",                               # French: calls closed
    "closed grants": "Closed",
    "allocated": "Closed",
    "this call closed on 18 september 2025": "Closed",
    "this call closed on 12 november 2025": "Closed",
    "this call closed on 14 april 2026": "Closed",
    "these proposals are now under evaluation by independent experts.": "Closed",
    # Rolling (additional)
    "recurring": "Rolling",
    "open calls continuous": "Rolling",
    "permanently open": "Rolling",
}


def compute_status(record: dict) -> dict:
    """Apply the §7.2 five-rule status auto-computation in strict priority order.

    All date comparisons use UTC (``datetime.now(timezone.utc).date()``).

    Args:
        record: Partially-normalised grant dict.  Expected keys:
            ``current_status_raw`` (str | None),
            ``confidence_scores`` (dict),
            ``application_deadline_type`` (str | None),
            ``application_deadline`` (datetime.date | None),
            ``grant_opening_date`` (datetime.date | None).

    Returns:
        ``{"current_status": str | None, "status_source": str}``
        where ``current_status`` is ``None`` only for the sentinel fallback.
    """
    today: date = datetime.now(timezone.utc).date()

    cs: dict = record.get("confidence_scores", {})
    status_raw: str | None = record.get("current_status_raw")
    app_deadline_type: str | None = record.get("application_deadline_type")
    app_deadline: date | None = record.get("application_deadline")
    opening_date: date | None = record.get("grant_opening_date")

    # Rule 1 — explicitly stated status with high confidence
    if status_raw is not None and cs.get("current_status") == "high":
        key = status_raw.lower().strip()
        canonical = _STATUS_VOCAB_LOWER.get(key)
        if canonical is None:
            # Curated alias (synonyms / non-English equivalents that don't
            # score highly enough under fuzzy matching, e.g. "Gesloten").
            canonical = _STATUS_ALIASES.get(key)
        if canonical is None:
            # Fuzzy match (mirrors normalise_controlled_vocab) to absorb
            # punctuation/wording variants such as "open" vs "Open now".
            best_score = 0
            for v_lower, v_canonical in _STATUS_VOCAB_LOWER.items():
                score = fuzz.ratio(key, v_lower)
                if score > best_score:
                    best_score = score
                    canonical = v_canonical
            if best_score < _VOCAB_FUZZY_THRESHOLD:
                canonical = "Others"
        return {"current_status": canonical, "status_source": "extracted"}

    # Rule 2 — rolling deadline implies Rolling status
    if app_deadline_type == "rolling" and status_raw is None:
        return {"current_status": "Rolling", "status_source": "computed"}

    # Rule 3 — grant has not yet opened → Upcoming
    # MUST precede rule 4: a grant not yet opened cannot be Open or Closed.
    if (
        opening_date is not None
        and cs.get("grant_opening_date") == "high"
        and opening_date > today
        and status_raw is None
    ):
        return {"current_status": "Upcoming", "status_source": "computed"}

    # Rule 4 — confirmed deadline with high confidence → Open or Closed
    if (
        app_deadline_type == "confirmed"
        and cs.get("application_deadline") == "high"
        and status_raw is None
    ):
        if app_deadline is not None and app_deadline < today:
            return {"current_status": "Closed", "status_source": "computed"}
        if app_deadline is not None and app_deadline >= today:
            return {"current_status": "Open", "status_source": "computed"}

    # Rule 5 — sentinel fallback
    return {"current_status": None, "status_source": "sentinel"}


# ---------------------------------------------------------------------------
# Controlled vocabulary lists (§10)
# ---------------------------------------------------------------------------

ORG_TYPES_VOCAB: list[str] = [
    "University / Higher Education Institution",
    "Research Institution / Think Tank",
    "Non-Governmental Organisation (NGO)",
    "Civil Society Organisation (CSO)",
    "Community Organisation / Grassroots Group",
    "Government / Public Authority",
    "Intergovernmental Organisation",
    "Private Sector / For-Profit Company",
    "Social Enterprise",
    "Foundation / Philanthropic Organisation",
    "Hospital / Healthcare Institution",
    "Media Organisation",
    "Faith-Based Organisation",
    "Consortium / Partnership",
    "Others",
]

INDIV_ELIGIBILITY_VOCAB: list[str] = [
    "Student — Undergraduate",
    "Student — Postgraduate / PhD",
    "Early Career Researcher",
    "Early Career Researcher (includes PhD candidates)",
    "Mid-Career Professional / Researcher",
    "Senior / Established Researcher or Professional",
    "Professional / Practitioner",
    "Entrepreneur",
    "Developer / Programmer",
    "Independent Scholar",
    "Artist / Creative",
    "Journalist",
    "Activist / Community Leader",
    "Any Individual (no career stage or profession restriction)",
    "Researcher (any career stage)",
    "Others",
]

THEMATIC_SECTORS_VOCAB: list[str] = [
    "Agriculture and Food Security",
    "Arts, Culture and Heritage",
    "Biodiversity and Conservation",
    "Climate Change and Environment",
    "Democracy, Governance and Accountability",
    "Digital Technology and Innovation",
    "Disaster Risk Reduction and Humanitarian Response",
    "Economic Development and Livelihoods",
    "Education and Training",
    "Energy and Clean Technology",
    "Gender Equality and Women's Empowerment",
    "Health and Medical Research",
    "Human Rights and Social Justice",
    "Infrastructure and Urban Development",
    "Media and Journalism",
    "Mental Health and Wellbeing",
    "Migration, Displacement and Refugees",
    "Peace and Security",
    "Poverty Reduction and Social Protection",
    "Science, Technology, Engineering and Mathematics (STEM)",
    "Water, Sanitation and Hygiene (WASH)",
    "Youth and Children",
    "Social Sciences and Humanities",
    "Natural and Physical Sciences",
    "Others",
]

GRANT_TYPES_VOCAB: list[str] = [
    "Research Grant",
    "Fellowship",
    "Scholarship",
    "Project Grant",
    "Capacity Building Grant",
    "Travel Grant",
    "Emergency Fund",
    "Award / Prize",
    "Loan",
    "In-Kind Support",
    "Others",
]


# ---------------------------------------------------------------------------
# Full-record normalisation (converts raw LLM output to a DB-ready dict)
# ---------------------------------------------------------------------------


def normalise_raw_grant(raw_grant: dict, source: dict) -> dict:
    """Convert a raw LLM grant dict to a fully normalised DB-ready record.

    Args:
        raw_grant: Raw grant dict as produced by ``parse_llm_response``.
            Private keys prefixed with ``__`` (e.g. ``__url_hash``) are
            silently ignored and must be stripped by the caller first.
        source: Provenance dict with keys:
            ``source_url`` — original page URL (may be empty string).
            ``domain``     — crawl domain (e.g. ``"example.com"``).
            ``crawl_date`` — ISO-8601 date string (e.g. ``"2026-05-23"``).

    Returns:
        Dict whose keys match the ``grants`` table columns, ready for
        ``upsert_grant``.
    """
    cs: dict = raw_grant.get("confidence_scores") or {}

    # Parse crawl_date to a date object
    crawl_date_str: str = source.get("crawl_date") or ""
    try:
        crawl_date_obj: date = (
            dateutil_parser.parse(crawl_date_str).date()
            if crawl_date_str
            else datetime.now(timezone.utc).date()
        )
    except (ValueError, OverflowError):
        crawl_date_obj = datetime.now(timezone.utc).date()

    # Basic text fields
    grant_title_raw: str = raw_grant.get("grant_title") or ""
    grant_title: str = normalise_grant_title(grant_title_raw) or grant_title_raw

    funder_raw: str = raw_grant.get("funder_name") or ""
    funder_result: dict = normalise_funder_name(funder_raw)
    funder_name: str = funder_result.get("canonical_name") or funder_raw

    # Deadlines
    app_deadline = normalise_deadline(
        raw_grant.get("application_deadline_raw"),
        cs.get("application_deadline", "not_found"),
    )
    eoi_deadline = normalise_deadline(
        raw_grant.get("eoi_deadline_raw"),
        cs.get("eoi_deadline", "not_found"),
    )
    opening_date = normalise_deadline(
        raw_grant.get("grant_opening_date_raw"),
        cs.get("grant_opening_date", "not_found"),
    )

    # Currency + language
    currency: str = normalise_currency(raw_grant.get("currency_raw"))
    source_language: str = normalise_source_language(raw_grant.get("source_language_raw"))

    # Geographic lists
    geo_focus = normalise_geographic_list(raw_grant.get("geographic_focus_raw") or [])
    applicant_base = normalise_geographic_list(raw_grant.get("applicant_base_raw") or [])

    # Controlled vocabularies
    org_types: list[str] = normalise_controlled_vocab(
        raw_grant.get("organisation_types_raw") or [], ORG_TYPES_VOCAB,
        aliases=ORG_TYPES_ALIASES,
    )
    indiv_elig: list[str] = normalise_controlled_vocab(
        raw_grant.get("individual_eligibility_raw") or [], INDIV_ELIGIBILITY_VOCAB,
        aliases=INDIV_ELIGIBILITY_ALIASES,
    )

    # individuals_not_eligible inference (R7 mitigation): the extraction
    # schema allows individuals_not_eligible to be null when the model
    # could not determine it directly. However, if the model separately
    # extracted one or more individual_eligibility_raw entries, that is
    # direct evidence individuals CAN apply (individuals_not_eligible is
    # false) — no re-extraction needed. Only applied when the field is
    # null; an explicit true/false from the model is never overridden.
    individuals_not_eligible = raw_grant.get("individuals_not_eligible")
    if individuals_not_eligible is None and (raw_grant.get("individual_eligibility_raw") or []):
        log.debug("individuals_not_eligible_inferred_false", reason="individual_eligibility_raw_non_empty")
        individuals_not_eligible = False

    # Mirror-image inference: if the model identified eligible organisation
    # types but found NO individual-eligibility entries at all — including
    # professional/career-stage titles such as "Researcher" or "Artist /
    # Creative", which is exactly what individual_eligibility_raw captures —
    # that is direct evidence the grant is restricted to organisations and
    # individuals_not_eligible is true. Only applied when the field is null
    # and individual_eligibility_raw is empty; an explicit true/false from
    # the model, or any non-empty individual_eligibility_raw, takes priority
    # (handled above).
    if individuals_not_eligible is None and (raw_grant.get("organisation_types_raw") or []):
        log.debug("individuals_not_eligible_inferred_true", reason="organisation_types_raw_non_empty_only")
        individuals_not_eligible = True
    thematic: list[str] = normalise_controlled_vocab(
        raw_grant.get("thematic_sectors_raw") or [], THEMATIC_SECTORS_VOCAB,
        aliases=THEMATIC_SECTORS_ALIASES,
    )
    grant_types: list[str] = normalise_controlled_vocab(
        raw_grant.get("grant_types_raw") or [], GRANT_TYPES_VOCAB
    )

    # Intermediate record for status + review computation
    intermediate: dict = {
        "confidence_scores": cs,
        "application_deadline_type": app_deadline["type"],
        "application_deadline": app_deadline["date"],
        "grant_opening_date": opening_date["date"],
        "current_status_raw": raw_grant.get("current_status_raw"),
        "thematic_sectors": thematic,
        "geographic_focus_regions": geo_focus["regions"],
        "individual_eligibility": indiv_elig,
        "organisation_types": org_types,
        "individuals_not_eligible": individuals_not_eligible,
    }

    status_result: dict = compute_status(intermediate)
    agg_score: int = aggregate_confidence_score(cs)
    review_flag: bool = determine_review_flag({**intermediate, **status_result})
    review_status: str = "pending" if review_flag else "approved"

    content_hash: str = compute_content_hash(funder_name, grant_title)

    return {
        "content_hash": content_hash,
        "grant_title": grant_title,
        "funder_name": funder_name,
        "funder_ror_id": funder_result.get("ror_id"),
        "source_url": source.get("source_url") or "",
        "application_portal_url": raw_grant.get("application_portal_url"),
        "description": raw_grant.get("description"),
        "application_deadline": app_deadline["date"],
        "application_deadline_raw": raw_grant.get("application_deadline_raw"),
        "application_deadline_type": app_deadline["type"],
        "deadline_notes": raw_grant.get("deadline_notes"),
        "eoi_deadline": eoi_deadline["date"],
        "eoi_deadline_raw": raw_grant.get("eoi_deadline_raw"),
        "eoi_deadline_type": eoi_deadline["type"],
        "grant_opening_date": opening_date["date"],
        "grant_opening_date_raw": raw_grant.get("grant_opening_date_raw"),
        "funding_amount_min": raw_grant.get("funding_amount_min"),
        "funding_amount_max": raw_grant.get("funding_amount_max"),
        "currency": currency,
        "funding_amount_type": None,
        "current_status": status_result["current_status"],
        "status_source": status_result["status_source"],
        "source_language": source_language,
        "ai_focused": raw_grant.get("ai_focused"),
        "individuals_not_eligible": individuals_not_eligible if individuals_not_eligible is not None else False,
        "organisation_types": org_types,
        "individual_eligibility": indiv_elig,
        "applicant_base_regions": applicant_base["regions"],
        "applicant_base_countries": applicant_base["countries"],
        "geographic_focus_regions": geo_focus["regions"],
        "geographic_focus_countries": geo_focus["countries"],
        "thematic_sectors": thematic,
        "grant_types": grant_types,
        "confidence_scores": cs,
        "aggregate_confidence_score": agg_score,
        "raw_extraction": {
            k: v for k, v in raw_grant.items() if not k.startswith("__")
        },
        "requires_review": review_flag,
        "review_status": review_status,
        "domain": source.get("domain") or "unknown",
        "crawl_date": crawl_date_obj,
    }
