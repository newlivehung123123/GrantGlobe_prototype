# GrantGlobe Source List — Layer 1

## Purpose
Geographically balanced inventory of ~200-400 target domains for automated crawling.
Source list is the primary intellectual moat of GrantGlobe — the selection of which organisations to track determines what opportunities users discover.

## Structure
Files organised by category/region:
- `00-un-agencies.md` — UN bodies and multilateral organisations
- `01-development-banks.md` — Regional and multilateral development banks
- `02-africa.md` — African research councils, foundations, regional bodies
- `03-asia.md` — Asian research councils, foundations, regional bodies
- `04-latin-america.md` — Latin American and Caribbean research councils, foundations
- `05-middle-east-central-asia.md` — MENA and Central Asian research councils, foundations
- `06-oceania-pacific.md` — Oceania and Pacific Islands research councils
- `07-bilateral-aid.md` — Bilateral aid agencies with research/innovation funding
- `08-philanthropic-foundations.md` — Global and regional philanthropic foundations
- `09-ai-governance-tech.md` — AI-specific bodies, tech policy, digital governance
- `10-global-health.md` — Global health research funders
- `11-other-specialized.md` — Science academies, specialised grant bodies
- `12-western.md` — Western funders with global reach (complementary, not dominant)
- `master-index.md` — Consolidated flat list with classification, region, priority

## Field Definitions

Each entry includes:
- **Name** — Organisation name
- **URL** — Main grants/funding page (crawl target)
- **Region** — Primary geographic focus (Global, Africa, Asia, LAC, MENA, Oceania, Europe, North America)
- **Type** — UN, MDB, Bilateral, ResearchCouncil, Foundation, AI_Body, GlobalHealth, Other
- **Individual Eligible** — Yes / No / Mixed / Unknown
- **Institutional Affiliation Required** — Yes / No / Mixed / Unknown
- **Fiscal Sponsor Accepted** — Yes / No / Unknown
- **Language** — Primary language of funding page
- **Priority** — 🟢 High (strong individual eligibility, active), 🟡 Medium, 🔵 Low (institutional-only or limited)
- **Notes** — Key observations for extraction
