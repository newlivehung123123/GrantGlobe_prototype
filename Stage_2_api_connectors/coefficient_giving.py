#!/usr/bin/env python3
"""
Coefficient Giving connector.

Coefficient Giving is the philanthropic foundation formerly known as Open
Philanthropy, rebranded in November 2025 (same organisation, same funds,
new name and domain — coefficientgiving.org). It is one of the largest
non-academic-restricted global grantmakers, organised into a set of named
"Funds" (Abundance & Growth, Effective Giving & Careers, Farm Animal
Welfare, Global Catastrophic Risks Opportunities, Navigating Transformative
AI, Science and Global Health R&D, Strep A Vaccine Fund, etc.), each
running zero-to-several individual RFPs/programmes.

This connector is a hand-curated static list (SCHEMES) rather than a live
scraper, because:
  - Coefficient Giving's individual RFP pages are one-off campaigns with
    irregular, non-cyclical timing (unlike HHMI's clean annual/biennial
    competitions), so there is no reliable listing-page structure to
    crawl generically.
  - The canonical "Apply for Funding" hub page
    (coefficientgiving.org/apply-for-funding/) is itself JS-rendered in
    parts and not reliably scrapeable, but was used as the primary human
    research source to compile this list.

Schemes included (6), each individually verified on its own detail page
as of June 2026, and selected because each carries explicit eligibility
language inviting non-academic applicants (companies, NGOs, independent
individuals) rather than being restricted to university-affiliated
researchers:

  1. RFP on Effective Giving (Effective Giving & Careers Fund)
       Any organisation raising funds for effective charities (donation
       platforms, advisory services, pledge organisations, etc).
       Deadline: June 26, 2026.

  2. RFP: Humane Fish Slaughter Research/Prototypes (Farm Animal Welfare)
       Explicitly: "individuals; universities and research institutions;
       small, medium, and large companies; and public sector research
       organizations." Deadline: July 1, 2026.

  3. RFP: Alternative Protein R&D (Farm Animal Welfare)
       Explicitly: "universities and research institutes; small, medium,
       and large companies; and public-sector research organizations...
       Applicants from anywhere in the world are welcome." Deadline:
       August 10, 2026.

  4. Career Development and Transition Funding (Global Catastrophic Risks
     Opportunities Fund)
       Individual-level funding, open to any career stage/background.
       Rolling, open until further notice.

  5. Funding for Programs and Events on Global Catastrophic Risk,
     Effective Altruism, and Other Topics (GCR Opportunities Fund)
       Open to individuals and organisations running qualifying programs
       or events. Rolling, open until further notice.

  6. Funding for work that builds capacity to address risks from
     transformative AI (Navigating Transformative AI Fund)
       Explicitly: "applications from both organizations and individuals,"
       including people from fields outside computer science/ML. Rolling,
       open until further notice.

Excluded candidates (checked but not included):
  - Living Literature Reviews (Abundance & Growth): "Ideal candidates will
    have a Ph.D. or equivalent expertise" — leans academic, ambiguous fit
    against this project's non-academic-inclusion criterion.
  - RFP on AI Governance / RFP on Biosecurity: confirmed CLOSED as of
    June 2026 (Jan 25, 2026 and May 11, 2026 deadlines respectively).
  - Science and Global Health R&D: accepts only unsolicited proposals via
    a general inquiry form, not a defined scheme with its own deadline.
  - Strep A Vaccine Fund: open call is an ongoing EOI without a concrete,
    individually verifiable eligibility/deadline page at time of writing.

Two distinct status models are used in SCHEMES:
  - Dated RFPs ("rolling": False) have a real one-off deadline. Status is
    computed directly from today vs. that date — once passed, the record
    simply reports "Closed" (no auto-advancing to a fabricated next-year
    date, since these RFPs are not on a guaranteed annual cycle).
  - Rolling programmes ("rolling": True) have no deadline; they are
    always reported "Open" with deadline_raw = "Rolling basis".

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/coefficient_giving.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys

import psycopg2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUNDER = "Coefficient Giving"
DOMAIN = "api_coefficient_giving"
PORTAL_URL = "https://coefficientgiving.org/apply-for-funding/"

SCHEMES: list[dict] = [
    {
        "title": "RFP on Effective Giving",
        "url": "https://coefficientgiving.org/funds/effective-giving-and-careers/rfp-on-effective-giving/",
        "rolling": False,
        "deadline": datetime.date(2026, 6, 26),
        "sectors": ["Civic Engagement", "Global Development"],
        "grant_types": ["Project Grant", "General Operating Support"],
        "individual": [],
        "org_types": ["Non-Profit Organisation", "Social Enterprise"],
        "desc": (
            "Coefficient Giving's Effective Giving & Careers Fund is soliciting "
            "proposals from effective giving organizations: initiatives that raise "
            "funds for highly effective charities. Eligible applicants include "
            "donation platforms and associated outreach efforts, organizations "
            "advising (ultra-)high-net-worth donors on charitable giving, "
            "organizations recruiting pledgers, organizations using matching or "
            "multiplier schemes, and groups raising awareness of effective giving "
            "or funneling new donors to other effective giving organizations. "
            "Effective giving comprises roughly 70% of the Fund's portfolio, with "
            "current grantees estimated to deliver an average adjusted return on "
            "donations of 6x. The Fund is particularly interested in new "
            "country-level organizations in promising markets, professionalized "
            "marketing support, donor advisory capacity for high-net-worth donors, "
            "partnerships with mainstream philanthropy and donor-advised fund "
            "platforms, and workplace/payroll giving integrations. Most grants are "
            "unrestricted, one- or two-year, and non-renewable by default. "
            "Applications are due by June 26, 2026, at 11:59 pm PT."
        ),
    },
    {
        "title": "RFP: Humane Fish Slaughter Research/Prototypes",
        "url": "https://coefficientgiving.org/funds/farm-animal-welfare/request-for-proposals-humane-fish-slaughter-research-prototypes/",
        "rolling": False,
        "deadline": datetime.date(2026, 7, 1),
        "sectors": ["Agriculture & Food", "Biotechnology"],
        "grant_types": ["Research Grant", "Project Grant"],
        "individual": ["Independent Scholar", "Entrepreneur"],
        "org_types": ["University", "Research Institution", "Company", "Government Agency"],
        "desc": (
            "Coefficient Giving's Farm Animal Welfare Fund is soliciting proposals "
            "for technologies and prototypes that materially improve the welfare "
            "of fish at capture and slaughter, rendering pre-death insensibility "
            "instantaneous, long-lasting, verifiable, and scalable under the "
            "physical constraints of aquaculture and fisheries operations. Over "
            "100 billion farmed fish and more than a trillion wild-caught fish are "
            "slaughtered each year, with only a small fraction reliably stunned "
            "before slaughter. The Fund expects to spend roughly $7 million USD on "
            "this RFP over the next year and explicitly encourages applications "
            "from across the R&D ecosystem, including individuals; universities "
            "and research institutions; small, medium, and large companies; and "
            "public sector research organizations. Proposals of varying sizes and "
            "scopes are welcome, from exploratory research to advanced prototype "
            "development. Applications remain open until July 1, 2026, beginning "
            "with a 2,500-3,000 word Letter of Intent."
        ),
    },
    {
        "title": "RFP on Alternative Protein R&D",
        "url": "https://coefficientgiving.org/funds/farm-animal-welfare/request-for-proposals-alternative-protein-rd/",
        "rolling": False,
        "deadline": datetime.date(2026, 8, 10),
        "sectors": ["Agriculture & Food", "Biotechnology", "Research & Innovation"],
        "grant_types": ["Research Grant", "Project Grant"],
        "individual": [],
        "org_types": ["University", "Research Institution", "Company", "Government Agency"],
        "desc": (
            "Coefficient Giving's Farm Animal Welfare Fund is soliciting proposals "
            "to close the taste and price gap between alternative proteins and the "
            "animal products they aim to replace, across four priority areas: "
            "off-flavor reduction in plant- and fermentation-derived protein "
            "ingredients; fat alternatives for flavor generation; egg reduction "
            "and replacement; and characterizing fish flavors in welfare-priority "
            "species. The Fund expects to spend up to $10 million USD on this RFP "
            "and explicitly encourages applications from across the R&D "
            "ecosystem, including universities and research institutes; small, "
            "medium, and large companies; and public-sector research "
            "organizations, with awards typically ranging from $100,000 to $1 "
            "million over two to three years. Applicants from anywhere in the "
            "world are welcome to apply, though award eligibility is subject to "
            "legal and financial due diligence. Applications remain open until "
            "August 10, 2026."
        ),
    },
    {
        "title": "Career Development and Transition Funding",
        "url": "https://coefficientgiving.org/funds/global-catastrophic-risks-opportunities/career-development-and-transition-funding/",
        "rolling": True,
        "deadline": None,
        "sectors": ["Existential Risk Reduction", "Civic Engagement"],
        "grant_types": ["Fellowship", "Project Grant"],
        "individual": [
            "Graduate Student", "Early Career Researcher", "Mid-Career Researcher",
            "Entrepreneur", "Independent Scholar",
        ],
        "org_types": [],
        "desc": (
            "Coefficient Giving's Global Catastrophic Risks Opportunities Fund "
            "offers individual-level career development and transition funding "
            "for people seeking to move into work that helps society navigate "
            "global catastrophic risks (including risks from advanced AI, "
            "biosecurity, and other large-scale threats). Funding can support "
            "activities such as skilling up, career transitions, relocation, or "
            "exploratory projects, and is open to applicants at any career stage "
            "and from any professional or academic background, not solely "
            "academic researchers. Applications are accepted on a rolling basis "
            "and assessed continuously, with no fixed deadline."
        ),
    },
    {
        "title": "Funding for Programs and Events on Global Catastrophic Risk, Effective Altruism, and Other Topics",
        "url": "https://coefficientgiving.org/funds/global-catastrophic-risks-opportunities/funding-for-programs-and-events-on-global-catastrophic-risk-effective-altruism-and-other-topics/",
        "rolling": True,
        "deadline": None,
        "sectors": ["Existential Risk Reduction", "Civic Engagement"],
        "grant_types": ["Project Grant", "Seed Grant"],
        "individual": ["Independent Scholar", "Entrepreneur"],
        "org_types": ["Non-Profit Organisation", "Community Group"],
        "desc": (
            "Coefficient Giving's Global Catastrophic Risks Opportunities Fund "
            "supports programs and events aimed at individuals at any career "
            "stage who are interested in global catastrophic risk, effective "
            "altruism, and related topics — for example, training programs, "
            "fellowships, retreats, conferences, and community-building "
            "initiatives. Both individuals and organizations running such "
            "programs or events may apply, and applicants need not have an "
            "academic affiliation. Applications are accepted on a rolling basis "
            "and assessed continuously, with no fixed deadline."
        ),
    },
    {
        "title": "Funding for work that builds capacity to address risks from transformative AI",
        "url": "https://coefficientgiving.org/funds/navigating-transformative-ai/funding-for-work-that-builds-capacity-to-address-risks-from-transformative-ai/",
        "rolling": True,
        "deadline": None,
        "sectors": ["AI Governance", "AI Policy", "Existential Risk Reduction"],
        "grant_types": ["Project Grant", "Fellowship", "Seed Grant"],
        "individual": [
            "Graduate Student", "Early Career Researcher", "Mid-Career Researcher",
            "Independent Scholar", "Entrepreneur",
        ],
        "org_types": ["Non-Profit Organisation", "Company", "Community Group"],
        "desc": (
            "Coefficient Giving's Navigating Transformative AI Fund funds "
            "capacity-building projects aimed at helping society address risks "
            "from transformative AI: training and mentorship programs, events, "
            "groups, and resources/media/communications work. The Fund "
            "explicitly welcomes applications from both organizations and "
            "individuals, including people from academic or professional fields "
            "outside computer science or machine learning, and from full-time or "
            "part-time projects. This program funds capacity-building rather "
            "than direct technical research. Applications are open until "
            "further notice and are assessed on a rolling basis."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "Stage_3_LLM_extraction", ".env"
        )
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        url = line[len("DATABASE_URL="):]
                        break
    if not url:
        sys.exit("ERROR: DATABASE_URL not set.")
    return url


def _connect():
    return psycopg2.connect(_get_db_url(), connect_timeout=30)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, today: datetime.date) -> dict:
    if scheme["rolling"]:
        deadline_iso = None
        deadline_raw = "Rolling basis (open until further notice)"
        status = "Open"
        days_until = None
    else:
        deadline: datetime.date = scheme["deadline"]
        days_until = (deadline - today).days
        status = "Open" if days_until >= 0 else "Closed"
        deadline_iso = deadline.isoformat()
        deadline_raw = f"{deadline.day} {deadline.strftime('%B %Y')}"

    return {
        "grant_title":              scheme["title"],
        "funder_name":              FUNDER,
        "source_url":               scheme["url"],
        "application_portal_url":   PORTAL_URL,
        "description":              scheme["desc"],
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         scheme["sectors"],
        "grant_types":              scheme["grant_types"],
        "applicant_base_regions":   [],
        "geographic_focus_regions": ["Global"],
        "applicant_base_countries": [],
        "geographic_focus_countries": [],
        "organisation_types":       scheme["org_types"],
        "individual_eligibility":   scheme["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(
                                        scheme["url"], scheme["title"],
                                        deadline_iso or "rolling",
                                    ),
        # carry-along for dry-run display only
        "_days_until": days_until,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    """Insert or update by source_url. Returns 'inserted' or 'updated'."""
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}

    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],))
    existing = cur.fetchone()

    if existing:
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                current_status = %s,
                crawl_date = %s, content_hash = %s,
                domain = %s
               WHERE id = %s""",
            (
                db_rec["grant_title"], db_rec["description"],
                db_rec["application_deadline"], db_rec["application_deadline_raw"],
                db_rec["current_status"],
                db_rec["crawl_date"], db_rec["content_hash"],
                db_rec["domain"],
                existing[0],
            ),
        )
        return "updated"

    cols = list(db_rec.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))})",
        [db_rec[c] for c in cols],
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Coefficient Giving connector for GrantGlobe")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*65}")
    print(f"  Coefficient Giving — {len(records)} schemes  (today: {today})")
    print(f"{'─'*65}")
    for rec in records:
        dl = rec["application_deadline"] or "rolling"
        dd = f"({rec['_days_until']}d)" if rec["_days_until"] is not None else ""
        print(f"  [{rec['current_status']:<8}] {rec['grant_title']:<70} → {dl}  {dd}")

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for rec in records:
            display = {k: v for k, v in rec.items() if not k.startswith("_")}
            print(json.dumps(display, indent=2, default=str))
        return

    conn = _connect()
    inserted = updated = err = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            print(f"  {result:9}  {record['grant_title']}")
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            print(f"  ERROR [{record['grant_title'][:50]}]: {e}", file=sys.stderr)
            err += 1
    conn.close()
    print(f"\n  Coefficient Giving: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
