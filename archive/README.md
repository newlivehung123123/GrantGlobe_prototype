# GrantGlobe Source List — Layer 1

**Version:** 0.3 Combined (Stage 1 complete — skeleton + Global South extension)
**Date:** 2026-05-21
**Status:** Awaiting Jason's Stage 2 supplementation → then Stage 3 verification

---

## What This Is

The curated list of target domains that the GrantGlobe crawler will visit. This is the project's intellectual moat — the primary differentiator versus general-purpose search engines and existing grant databases.

---

## Files

| File | Description |
|---|---|
| `source_list_v0.1_skeleton.csv` | Original 210-entry skeleton (Western + institutional baseline) |
| `source_list_v0.2_globalsouth_extension.csv` | 110-entry Global South extension (Africa, Asia, LatAm regional bodies, South-South cooperation, AI/Global South-specific) |
| `source_list_v0.3_combined.csv` | **Active working file** — merged 320-entry list |
| `GAP_FLAGS.md` | Explicit gaps in current coverage; roadmap for Jason's Stage 2 additions |
| `README.md` | This file |

---

## CSV Column Schema

| Column | Description |
|---|---|
| `id` | Sequential integer ID |
| `org_name` | Full organization name |
| `domain` | Root domain (no https://) |
| `grants_url` | Best-guess direct URL to grants/funding/fellowships page |
| `category` | Institution type (UN Agency, Regional Dev Bank, Bilateral Aid, National Research Council, Global Philanthropic, EA-Adjacent, AI Safety, Academic Fellowship, Regional Philanthropic, etc.) |
| `region` | Geographic scope or primary region |
| `individual_eligible` | `yes` / `no` / `unknown` — whether individuals without institutional affiliation can apply |
| `notes` | Key context: eligibility hints, language, focus areas, access notes |
| `confidence` | `high` / `medium` / `low` — confidence in this being an active grant-making body with English-language pages |
| `gap_flag` | `yes` if coverage of this region/category is thin and needs supplementation |

---

## Coverage Summary (v0.3 Combined)

| Category | Count |
|---|---|
| UN Agencies | 18 |
| Regional Development Banks | 13 |
| Bilateral Aid Agencies | 14 |
| National Research Councils — Asia | 20 |
| National Research Councils — Africa | 20 |
| National Research Councils — Latin America | 14 |
| National Research Councils — Middle East/MENA | 10 |
| National Research Councils — Eastern Europe | 11 |
| Global Philanthropics | 15 |
| EA-Adjacent / Fast Grants | 6 |
| AI Safety / AI Governance | 12 |
| AI Research — Global South Specific | 8 |
| Academic Fellowships | 20 |
| Regional Philanthropics | 12 |
| Pan-African / Pan-Regional Bodies | 15 |
| CGIAR Research Centers | 8 |
| South-South Cooperation Bodies | 8 |
| Islamic World / OIC Bodies | 5 |
| Pacific Regional Bodies | 4 |
| Policy Research | 8 |
| Tech Philanthropics | 4 |
| Other (Innovation, Social Entrepreneurship, etc.) | 15 |
| **TOTAL** | **~320** |

**Individual-eligible (confirmed yes):** 173 entries
**Individual-eligible (unknown — to be resolved in Stage 3):** 147 entries

---

## Stage Workflow

**Stage 1 (Jess):** ✅ Complete — 320 domains across two passes: baseline skeleton + Global South extension

**Stage 2 (Jason):** Add domains from your own GAID research experience + fill the gaps in GAP_FLAGS.md. Focus especially on:
- Non-Western sources you encountered during data collection
- Funders you applied to that aren't here
- Any bodies publishing grant calls you've seen but are likely poorly indexed

**Stage 3 (Jess):** Verify each domain:
- Is the domain live and resolving?
- Does it actually publish open grant calls (not just press releases)?
- Is there an English-language grants page?
- Flag dead/restructured/redirect domains for removal or replacement

**Output of Stage 3:** Verified, clean CSV ready to hand to the crawler (Layer 2)

---

## Target: 300–400 verified domains before crawler hand-off

Current v0.3 combined: 320
Jason's additions expected: ~30–80 (especially non-Western sources from GAID experience)
After deduplication and dead-domain removal: target 300–400 clean verified entries
