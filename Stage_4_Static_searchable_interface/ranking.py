#!/usr/bin/env python3
"""
ranking.py — Layer 1 of GrantGlobe's recommendation system.

Computes a build-time "default feed" score for every grant and returns the
grants re-ordered so the homepage leads with high-value, timely, well-described
opportunities from reputable funders — instead of the old "soonest-deadline
first" ordering, which buried good calls under whatever happened to expire next.

The score is a transparent weighted blend of six 0..1 sub-scores:

    status        how actionable the call is right now (Open/Rolling > Forthcoming)
    deadline      deadline "sweet spot" — enough runway to apply, not so far it's noise
    funding       award size (log-scaled, currency-normalised to USD)
    prestige      funder reputation tier (curated)
    completeness  how fully the record is described (trust / quality signal)
    recency       how recently the call opened (freshness, like a feed)

Each grant gets a `_rank_score` (0..1) written onto it for the frontend to use
as its global prior, plus `_rank_parts` for debugging/tuning. A light
diversification pass then spreads funders near the top so the first screen shows
variety rather than ten calls from the same agency.

This module is pure-Python and has no third-party dependencies, so it imports
cleanly inside export_grants.py during the GitHub Actions build.
"""

from __future__ import annotations

import datetime
import hashlib
import math

# ---------------------------------------------------------------------------
# Weights — must sum to ~1.0. Tunable; documented above.
# ---------------------------------------------------------------------------
WEIGHTS: dict[str, float] = {
    "status":       0.18,
    "deadline":     0.20,
    "funding":      0.15,
    "prestige":     0.22,
    "completeness": 0.15,
    "recency":      0.10,
}

# Small additive nudge for AI-focused calls (GrantGlobe's core audience lean).
_AI_FOCUS_BONUS = 0.03

# ---------------------------------------------------------------------------
# Rough FX → USD, only for cross-currency funding-size comparison. These do not
# need to be precise; they exist so a €1M call and a $1M call score similarly.
# ---------------------------------------------------------------------------
_FX_USD: dict[str, float] = {
    "USD": 1.00, "EUR": 1.08, "GBP": 1.27, "CHF": 1.10, "CAD": 0.73,
    "AUD": 0.66, "NZD": 0.61, "JPY": 0.0067, "CNY": 0.14, "HKD": 0.128,
    "SGD": 0.74, "KRW": 0.00073, "INR": 0.012, "SEK": 0.095, "NOK": 0.094,
    "DKK": 0.145, "PLN": 0.25, "CZK": 0.043, "ZAR": 0.054, "BRL": 0.18,
    "MXN": 0.058, "ILS": 0.27, "AED": 0.27, "SAR": 0.27, "TWD": 0.031,
}

# ---------------------------------------------------------------------------
# Funder prestige tiers. Matched as case-insensitive substrings of funder_name.
# Tier A → 1.00 (world-leading), Tier B → 0.78 (established public funders),
# everything else → 0.50. Pragmatic and easy to extend.
# ---------------------------------------------------------------------------
_PRESTIGE_A: tuple[str, ...] = (
    "european research council", "horizon europe", "european commission",
    "marie sk", "marie curie", "msca", "national science foundation",
    "national institutes of health", "wellcome", "gates foundation",
    "bill & melinda gates", "howard hughes", "hhmi", "max planck",
    "deutsche forschungsgemeinschaft", "medical research council",
    "engineering and physical sciences", "biotechnology and biological",
    "economic and social research council", "natural environment research",
    "science and technology facilities", "uk research and innovation",
    "simons foundation", "john templeton", "templeton", "royal society",
    "national natural science foundation of china", "japan society for the promotion",
    "swiss national science foundation", "chan zuckerberg", "gordon and betty moore",
    "schmidt sciences", "schmidt futures", "open philanthropy", "kavli",
    "leverhulme", "alfred p. sloan", "sloan foundation", "macarthur",
    "european molecular biology", "human frontier science",
)
_PRESTIGE_B: tuple[str, ...] = (
    "research council", "national research foundation", "academy of finland",
    "agence nationale de la recherche", "fundação para a ciência",
    "research foundation flanders", "national science centre", "fonds national",
    "fapesp", "canadian institutes of health", "natural sciences and engineering",
    "social sciences and humanities research", "australian research council",
    "marsden", "research grants council", "a*star", "national medical research",
    "national research foundation of korea", "czech science foundation",
    "national academies", "alexander von humboldt", "daad", "volkswagen foundation",
    "nordforsk", "research council of norway", "swedish research council",
    "novo nordisk", "carlsberg", "burroughs wellcome", "axa research",
    "department of energy", "nasa", "noaa", "usda", "darpa", "department of defense",
    "national endowment", "ford foundation", "rockefeller", "russell sage",
    "robert wood johnson", "spencer foundation",
)

# api_* domains that are reputable national/federal funders by construction —
# used as a prestige floor when the funder name doesn't match a keyword above.
_PRESTIGE_API_FLOOR = 0.66


def _prestige_score(grant: dict) -> float:
    name = (grant.get("funder_name") or "").lower()
    for kw in _PRESTIGE_A:
        if kw in name:
            return 1.0
    for kw in _PRESTIGE_B:
        if kw in name:
            return 0.78
    domain = grant.get("domain") or ""
    if domain.startswith("api_"):
        return _PRESTIGE_API_FLOOR
    return 0.50


def _status_score(status: str | None) -> float:
    return {
        "Open": 1.00, "Rolling": 0.90,
        "Forthcoming": 0.70, "Upcoming": 0.70,
    }.get(status or "", 0.55)


def _deadline_score(deadline_iso: str | None, today: datetime.date) -> float:
    """Reward a healthy application window; down-weight 'closes tomorrow' and
    'closes in two years'. Rolling/TBC (no date) is treated as comfortably open."""
    if not deadline_iso:
        return 0.70
    try:
        d = datetime.date.fromisoformat(str(deadline_iso)[:10])
    except (ValueError, TypeError):
        return 0.60
    days = (d - today).days
    if days < 0:
        return 0.0          # already closed (export should have filtered these)
    if days < 7:
        return 0.45         # almost no time to apply
    if days < 21:
        return 0.75
    if days <= 120:
        return 1.00         # sweet spot
    if days <= 240:
        return 0.80
    if days <= 365:
        return 0.60
    return 0.45             # very far off — low urgency, low signal


def _funding_score(grant: dict) -> float:
    amt = grant.get("funding_amount_max") or grant.get("funding_amount_min")
    if not amt:
        return 0.50         # unknown amount — neutral, neither rewarded nor buried
    cur = (grant.get("currency") or "USD").upper()
    try:
        usd = float(amt) * _FX_USD.get(cur, 1.0)
    except (ValueError, TypeError):
        return 0.50
    if usd <= 0:
        return 0.50
    # log10: ~$5k → 0.0, ~$5M → 1.0, clamped.
    score = (math.log10(usd) - 3.7) / (6.7 - 3.7)
    return max(0.10, min(1.0, score))


def _completeness_score(grant: dict) -> float:
    pts = 0
    if len(grant.get("description") or "") >= 120:
        pts += 1
    if grant.get("funding_amount_max") or grant.get("funding_amount_min"):
        pts += 1
    if grant.get("application_deadline") or grant.get("application_deadline_raw"):
        pts += 1
    if grant.get("thematic_sectors"):
        pts += 1
    if grant.get("organisation_types") or grant.get("individual_eligibility"):
        pts += 1
    if (grant.get("geographic_focus_regions") or grant.get("geographic_focus_countries")
            or grant.get("applicant_base_regions")):
        pts += 1
    return pts / 6.0


def _recency_score(grant: dict, today: datetime.date) -> float:
    raw = grant.get("grant_opening_date") or grant.get("crawl_date")
    if not raw:
        return 0.60
    try:
        d = datetime.date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return 0.60
    days = (today - d).days
    if days < 0:
        return 0.90         # opens in the future — fresh/upcoming
    if days <= 30:
        return 1.00
    if days <= 90:
        return 0.85
    if days <= 180:
        return 0.70
    if days <= 365:
        return 0.55
    return 0.40


def score_grant(grant: dict, today: datetime.date | None = None) -> tuple[float, dict]:
    """Return (overall_score 0..1, sub_score_dict) for one grant."""
    today = today or datetime.date.today()
    parts = {
        "status":       _status_score(grant.get("current_status")),
        "deadline":     _deadline_score(grant.get("application_deadline"), today),
        "funding":      _funding_score(grant),
        "prestige":     _prestige_score(grant),
        "completeness": _completeness_score(grant),
        "recency":      _recency_score(grant, today),
    }
    base = sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)
    if grant.get("ai_focused"):
        base = min(1.0, base + _AI_FOCUS_BONUS)
    return base, parts


def _tiebreak(grant: dict) -> str:
    """Deterministic, source-agnostic tiebreaker so equal scores don't cluster
    by insertion order (which would re-introduce by-source clumping)."""
    return hashlib.md5(str(grant.get("id", "")).encode()).hexdigest()


def _diversify(ranked: list[dict], window: int = 4) -> list[dict]:
    """Greedy re-order that avoids repeating the same funder within a sliding
    window, while keeping high scores near the top. Picks the highest-scored
    remaining grant whose funder hasn't appeared in the last `window` picks;
    if every candidate would repeat, takes the highest-scored one anyway."""
    pool = sorted(ranked, key=lambda g: (-g.get("_rank_score", 0), _tiebreak(g)))
    out: list[dict] = []
    recent: list[str] = []
    while pool:
        pick_idx = 0
        for i, g in enumerate(pool):
            if (g.get("funder_name") or "") not in recent:
                pick_idx = i
                break
        g = pool.pop(pick_idx)
        out.append(g)
        recent.append(g.get("funder_name") or "")
        if len(recent) > window:
            recent.pop(0)
    return out


def rank_grants(
    grants: list[dict],
    today: datetime.date | None = None,
    diversify: bool = True,
) -> list[dict]:
    """Score, sort (desc), and lightly diversify. Annotates each grant with
    `_rank_score` and `_rank_parts`. Returns a new ordered list."""
    today = today or datetime.date.today()
    for g in grants:
        score, parts = score_grant(g, today)
        g["_rank_score"] = round(score, 4)
        g["_rank_parts"] = {k: round(v, 3) for k, v in parts.items()}
    if diversify:
        return _diversify(grants)
    return sorted(grants, key=lambda g: (-g["_rank_score"], _tiebreak(g)))
