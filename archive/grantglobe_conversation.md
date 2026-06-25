# GrantGlobe: Research Conversation Log

**Topics covered:** GAID Project funding alignment · OpenAI Cybersecurity Grant assessment · Global funding landscape · GrantGlobe concept development · General Intelligence Fellowship application drafts

---

## 1. GAID Project vs. OpenAI Cybersecurity Grant Program

**Query:** Does the milestone-based GAID Project portfolio fit the OpenAI Cybersecurity Grant Program, and can the GAID dataset serve as a framework for a competitive proposal?

### Honest Fit Assessment

**Short answer:** The current GAID portfolio has indirect thematic overlap but does not naturally fit the Cybersecurity Grant Program as it stands. A credible pathway exists, but only with significant reframing of Phase 4 work toward a specific cybersecurity angle.

### Where the Misalignment Lies

OpenAI's programme is specifically focused on empowering cyber defenders, quantifying AI cybersecurity capabilities, and changing the power dynamics of cybersecurity through AI. Its priority areas include software patching, model privacy, detection and response against advanced persistent threats, security integration, and agentic security.

The GAID work, as currently framed, is centred on AI governance, global bias auditing, geographical hallucination, and responsible AI policy — a different domain entirely.

### Where Genuine Alignment Exists

Two legitimate bridges between GAID and the grant's goals exist:

**1. Model Privacy / Hallucination as a Security Vector**
The Phase 4 AI Eval pipeline — which stress-tests foundation models for factual grounding against GAID ground-truth data — touches on model reliability and output trustworthiness. OpenAI explicitly asks: *"Have you encountered cases where today's AI models fall short in security applications? If so, show us the data that highlights those gaps."* The GAID dataset is a tool for surfacing such gaps, which is a compelling angle — but the framing would need to pivot toward security-relevant failure modes, not solely geographical bias.

**2. AI Governance Data as a Security Infrastructure Layer**
A proposal arguing that the global indicator framework can benchmark a country's AI security readiness — and that models hallucinate about the security posture of Global South nations in ways that create downstream risk — would be more targeted.

### What Would Make It Competitive

OpenAI values small, well-executed projects over spread-thin larger ones, prioritising clear goal definition, practical impact, and commitment to open distribution of results. The track record (Harvard Dataverse publications, open-source ethos, Python pipeline) fits their process preferences. However, to build a competitive proposal, it would be necessary to:

- Narrow the scope to one of the five priority focus areas — the strongest fit is likely "model privacy" (hallucination as informational unreliability) or "detection and response" (using GAID indicators to flag countries where AI safety monitoring infrastructure is absent)
- Reframe the Phase 4 AI Eval pipeline as a cybersecurity reliability auditing tool — specifically, auditing whether LLMs can be trusted to provide accurate threat landscape or security posture assessments for non-Western nations
- Quantify the security risk of geographical hallucination: if a security professional uses an LLM to assess cyber risk in Southeast Asia and the model hallucinates, what are the downstream consequences?
- Keep the proposal under 3,000 words with a tight methodology and clear deliverable

---

## 2. Can GAID Support a Cybersecurity Reliability Auditing Tool?

### Transparency on Data Access

The raw `.csv` files and full codebooks from Harvard Dataverse could not be directly accessed (the repository blocks automated fetching). What was accessible included the EA Forum posts describing the dataset's full structure, domains, and metrics; the Apart Research Phase 4 exploratory project report and reviewer feedback; and published descriptions of all 20 GAID domains and 8 additional data sources in Version 2.

### Relevant Data Threads Within GAID

**Strong relevance:**
- Policy and Governance (OECD.ai, GIRAI) — national AI regulation, legal frameworks, enforcement capacity
- Responsible AI (GIRAI, UNESCO) — ethics frameworks, AI accountability mechanisms, transparency requirements
- GovTech Maturity Index (World Bank) — digital government infrastructure, citizen engagement, e-governance readiness
- Infrastructure (Tortoise Media Global AI Index) — electricity access, internet penetration, data privacy laws
- Operating Environment (Tortoise Media) — public opinion on AI, regulatory environment

**Moderate relevance:**
- R&D — national AI research capacity (proxy for security research capacity)
- AI Patent Landscapes (WIPO) — technical capability concentration by country
- Compute/Training Trends (Epoch AI) — who controls frontier model infrastructure

**Weaker/indirect relevance:**
- Diversity, Education, Economy, Energy, Talent (MacroPolo) — contextually useful but not directly cybersecurity-related

### Core Finding

The GAID dataset does not contain cybersecurity-specific variables — there are no indicators on national incident response capacity, CERT infrastructure, vulnerability disclosure rates, breach statistics, cyber threat intelligence sharing, or patching behaviour. However, the dataset does contain ground-truth national data on AI governance readiness, regulatory capacity, and infrastructure maturity — legitimate preconditions for cybersecurity resilience in an AI-enabled world.

The Apart Research Phase 4 project already demonstrated this empirically: by stress-testing Llama-3 8B with 1,704 queries across 213 countries and eight technical metrics, the model could provide factual responses in only 11.4% of queries, with knowledge heavily concentrated in higher-income regions — and the reviewer confirmed that the GAID dataset provides a solid ground-truth benchmark for this kind of evaluation.

### The Defensible Cybersecurity Angle

**Problem statement:** Security professionals and threat analysts increasingly use LLMs (GPT-4, Claude, Gemini) to assess the cyber risk posture, regulatory environment, and AI governance readiness of countries — particularly for supply chain risk assessments, vendor due diligence, or geopolitical threat modelling. If those models hallucinate or systematically underperform on Global South countries, downstream security decisions are compromised.

**GAID as the solution:** 27 years of longitudinal, 227-country ground-truth data across governance, infrastructure, and responsible AI domains constitutes precisely the kind of structured, verifiable benchmark needed to audit whether LLMs give reliable answers when asked about a country's AI governance posture, regulatory capacity, or digital infrastructure — all of which directly feed into cybersecurity risk assessment workflows.

**Existing proof of concept:** The Apart Research project is literally this — not yet framed in security language. The evaluation pipeline was already built and run. The reviewer's critique (conflating training cutoff limitations with geographic bias) is solvable with longitudinal data, since models can be queried about historical years well within their training window.

### Gaps to Address for a Competitive Proposal

1. Add explicit cybersecurity framing to 3–5 GAID variables that proxy cyber governance readiness (e.g., data privacy law existence, AI accountability frameworks, digital government maturity scores from GTMI)
2. Fix the methodological weakness flagged by the Apart reviewer: design LLM queries around years within the model's training cutoff (e.g., 2022–2023 data), so the evaluation measures genuine geographic knowledge gaps rather than temporal limitations
3. Connect the failure mode explicitly to security harm: show a worked example of how an LLM hallucinating about a country's AI governance capacity could cause a real security analyst to misjudge supply chain risk or threat actor capability

---

## 3. Pragmatic Assessment: Should the Cybersecurity Grant Be Pursued?

**Honest answer: probably not competitive enough. The application is inadvisable.**

### The Core Problem

OpenAI's reviewers for this programme are cybersecurity engineers and researchers. They are looking for work that directly moves the needle on prompt injection detection, vulnerability patching, protection of AI agents from adversarial exploitation, or threat detection improvement. The GAID work — even reframed — sits two to three conceptual steps away from those problems. Reviewers will perceive that distance immediately.

The Apart Research project already received a pointed methodological critique from a technically literate reviewer. The same level of scrutiny — arguably higher — would be applied by OpenAI's cybersecurity-focused reviewers.

### Context on Acceptance Rates

OpenAI has funded 28 research initiatives from over a thousand applications — roughly a 2–3% acceptance rate. The funded projects cluster around direct, technical, defensive cybersecurity work: prompt injection detection, secure code generation, autonomous cyber defences.

### Better-Aligned Opportunities

- UK DSIT / AISI (AI Safety Institute) — bias audit work and global governance dataset directly serves their mandate
- Open Philanthropy — AI governance and global AI equity is core to their portfolio
- Mozilla Foundation's Technology Fund — open-source, equity-focused AI tools
- Wellcome Trust / Omidyar Network — responsible AI infrastructure in the Global South
- NeurIPS or FAccT workshops — for building research credibility that unlocks future funding

---

## 4. Open Funding Opportunities — Status as of 8 March 2026

### Status by Organisation

| Organisation | Status | Notes |
|---|---|---|
| AISI Challenge Fund | **Closed** | Requires institutional affiliation; applications now closed |
| AISI Alignment Project Round 2 | **Closed** | Reopening summer 2026; requires institutional affiliation |
| Open Philanthropy AI Governance RFP | **Closed** | Closed 25 January 2026; next round timing unknown |
| Mozilla Democracy × AI Incubator | **Open** | Deadline 16 March 2026; $50,000; individual-eligible |
| Mozilla Fellows Program 2026 | **Closed** | Nominations closed 30 January 2026 |
| Omidyar Network | **No open call** | Funds established organisations proactively |
| FAccT 2026 | **Closed** | Submission deadline 13 January 2026 |
| NeurIPS 2026 | **Not yet open** | Main track deadlines typically open in May |

### Small and Rapid Grants — Open as of 8 March 2026

| Mechanism | Amount | Speed | Urgency | Fit |
|---|---|---|---|---|
| Manifund Regrants | $1,000–$50,000 | Days | Now | Moderate |
| Open Phil CDTF | $10,000–$80,000 | Rolling | Now | Strong |
| LTFF | $1,000–$200,000 | Rolling | Now | Moderate |
| Apart Hackathon | Up to $2,000 | 12 days | 20–22 March | Weak-Moderate |
| Open Phil Capacity Building | Flexible | Before 1 July | Now | Moderate |

### Non-Western and Multilateral Opportunities

**Genuinely open:**

- **ITU AI for Good Scholars Programme** — open to any individual from ITU Member States; recognition and platform at AI for Good Global Summit, Geneva, 7–10 July 2026; not a cash grant but provides UN-level visibility and direct policymaker access
- **Rockefeller Foundation — Bellagio Center Residency** — deadline 20 March 2026; fully funded residential fellowship at Lake Como; not a cash grant but provides Rockefeller-level credibility and convening with senior global policymakers

**Large funds, structurally inaccessible to individual applicants:**

- **Humanity AI** ($500M coalition — Ford, MacArthur, Mozilla, Omidyar, Mellon, Packard) — funds established organisations and think tanks at $500,000–$2,000,000; fiscal sponsorship required for individuals; register for updates at humanityai.ai
- **Patrick J. McGovern Foundation** — relationship-driven grantmaking to established organisations; no public open call; pathway is via existing grantee relationships

### Structural Reality

The research funding ecosystem for independent AI governance researchers in 2026:

- ~5–10 organisations globally fund independent researchers directly without institutional affiliation (LTFF, Manifund, Open Phil CDTF, Mozilla, Apart Research, Schmidt Sciences at Tier 1)
- ~20–30 organisations fund registered nonprofits and think tanks that then employ researchers
- ~100+ organisations fund at the national government or development bank level, requiring institutional affiliation and often national residence

Non-Western government funders almost universally require institutional affiliation and national residency. The multilateral UN funders offer platforms and recognition more than direct research funding. The bottleneck for independent researchers is not search coverage but institutional scaffolding — fiscal sponsorship, nonprofit status, or formal affiliation — which unlocks the larger funding pool.

---

## 5. The GrantGlobe Concept

### Motivation

General-purpose LLMs and existing grant databases systematically underrepresent funding opportunities from non-Western, non-EA-adjacent sources. The bias is not solely in the LLMs themselves but in the search architecture: LLMs perform real-time web searches against pre-built search engine indices, and PageRank-style algorithms systematically favour well-resourced Western organisations with high web traffic and strong inbound link profiles. Well-capitalised Western philanthropic ecosystems dominate results; equivalent opportunities from regional development banks, national research councils in the Global South, multilateral agencies, and non-Western philanthropic bodies remain poorly indexed.

The gap between what AI models surface versus what actually exists in English is a function of query architecture and source coverage, not language barriers. A purpose-built crawler targeting underrepresented source domains would surface opportunities that general-purpose search engines never reach — not because of language, but because of source selection bias.

### What GrantGlobe Is

GrantGlobe is an open-source, geographically balanced funding discovery engine that fixes the Western and institutional bias in existing grant databases — so independent researchers anywhere in the world can find opportunities they actually qualify for.

The distinguishing methodological contribution relative to existing tools is the **eligibility-inference layer**: current grant databases are funder-centric and do not systematically infer whether a given applicant profile can legally or practically access an opportunity. A researcher who is an individual, unaffiliated, and based outside the United States may discover through GrantGlobe not only that an opportunity exists but also that it requires US 501(c)(3) nonprofit status — information that saves application effort and redirects attention to opportunities where eligibility is genuine. No existing database captures this at scale.

### Five-Layer Architecture

**Layer 1: Source List** *(the primary intellectual work)*

A manually compiled, geographically balanced inventory of approximately 200–400 target domains:

- UN agency grant pages (UNDP, UNESCO, ITU, UNEP, WHO, FAO)
- Regional development banks (ADB, AfDB, IDB, IsDB, EBRD, World Bank)
- National research councils publishing in English across Africa, Asia, Oceania, and Latin America
- Bilateral aid agencies (FCDO, GIZ, USAID, DFAT Australia, IDRC Canada)
- Domain-specific bodies for AI (OECD.AI, GPAI, ITU AI for Good, Partnership on AI)
- Regional philanthropic foundations (Aga Khan Foundation, Wellcome Trust, Nippon Foundation, Samsung Foundation of Culture, Tata Trusts)

This source list is the primary differentiator and intellectual moat.

**Layer 2: Crawler**

Python-based crawler using Requests, BeautifulSoup, Scrapy, and Playwright (for JavaScript-rendered sites), visiting each target domain on a scheduled basis and extracting raw page content, including PDF-hosted announcements.

**Layer 3: LLM Extraction Pipeline**

Each crawled page passed through a structured LLM prompt to classify whether the content constitutes a genuine funding opportunity and, if so, to extract structured metadata:

- Funder name
- Deadline
- Funding range
- Geographic eligibility
- Thematic domain
- Individual-eligible (yes/no)
- Institutional affiliation required (yes/no)
- Fiscal sponsor accepted in lieu of registered nonprofit (yes/no)

**Layer 4: Static Searchable Database and Filterable Interface**

Hosted at zero cost on GitHub Pages or Netlify during the prototype phase. No cloud infrastructure required prior to the securing of external funding. A static snapshot demonstrates the concept as effectively as a live database for funding application purposes.

**Layer 5: Freshness Mechanism**

Scheduled re-crawling of source domains weekly; automatic flagging of lapsed deadlines.

### Build Timeline

| Month | Work |
|---|---|
| April 2026 | Source list compilation (200+ domains); crawler setup; test on 20 domains |
| May 2026 | Scale crawler to full source list; build LLM extraction pipeline |
| June 2026 | Clean database; build basic search interface; soft launch |
| July–August 2026 | User feedback; expand source list; refine extraction quality |

By August 2026, a working **MVP** is publicly available, with geographic and eligibility-metadata coverage exceeding any existing tool and a documented open methodology suitable for peer review and funder reporting.

### Hosting During Prototype Phase

No cloud hosting is required during prototype development. Everything in Layers 1–3 runs locally on a laptop. For a funding application demo, a static export (CSV or JSON) with a simple filterable HTML/JS interface hosted on GitHub Pages incurs zero ongoing cost. Live cloud hosting with a scheduled crawler becomes relevant only post-funding, when user-facing freshness is required.

### Honest Risks

- **Extraction accuracy:** LLMs will occasionally misclassify or hallucinate fields from messy grant pages; a human review layer or confidence scoring is needed for critical fields such as deadlines and eligibility
- **Site changes:** Grant pages restructure constantly; extraction prompts will require maintenance
- **Source list compilation:** Building a comprehensive list for Africa, Southeast Asia, Latin America, and Central Asia in English requires knowing which agencies to target; domain expertise in each region is an advantage here

### Funding Alignment

GrantGlobe is directly fundable, particularly through:

- Mozilla Foundation (democracy/information access angle)
- Patrick J. McGovern Foundation (data as a public good)
- LTFF (field-building infrastructure for global AI safety researchers)
- Open Philanthropy Capacity Building (rolling, before July 2026)

---

## 6. General Intelligence Fellowship — Application Drafts

### (1) Describe the company you want to build during the fellowship

*(990–1,010 words; plain language; product, users, revenue model)*

GrantGlobe is an open-source, geographically balanced funding discovery engine designed to close a structural gap that independent researchers worldwide encounter when searching for grants and fellowships: the systematic bias embedded in how funding opportunities are surfaced, discovered, and indexed.

The problem is not merely that existing grant databases are incomplete. Platforms such as Instrumentl, Candid, GrantForward, and Pivot are predominantly funder-centric, subscription-gated, and skewed towards United States and United Kingdom institutional applicants. More fundamentally, when independent researchers turn to general-purpose large language models (LLMs) such as Claude or Gemini as a practical substitute for grant search, they encounter a compounding bias problem that is architectural rather than incidental. LLMs do not maintain proprietary funding databases; they perform real-time web searches against pre-built search engine indices. The results that surface are those that have been crawled, ranked, and prioritised by PageRank-style algorithms, which systematically favour organisations with high web traffic, strong inbound link profiles, and well-resourced digital presences. In practice, this means that well-capitalised Western philanthropic ecosystems — Open Philanthropy, effective altruism-adjacent funders, and major United States foundations — dominate the results landscape, whilst equivalent opportunities from regional development banks, national research councils in the Global South, multilateral agencies, and non-Western philanthropic bodies remain invisible. They are not absent from the internet; they are simply poorly indexed and ranked. The outcome is that an independent researcher in Hong Kong, Nairobi, or São Paulo receives a functionally identical list to a researcher in Cambridge or San Francisco — a list that overwhelmingly reflects the funding infrastructure of a narrow institutional and geographic corridor, irrespective of actual eligibility or thematic fit.

GrantGlobe corrects this at the source. The product is a purpose-built, automated funding discovery engine that bypasses general-purpose search indices by crawling a curated list of target domains directly. The architecture consists of five layers. The first and most intellectually substantive layer is the source list: a manually compiled, geographically balanced inventory of approximately 200 to 400 target domains, spanning United Nations agencies, regional development banks (the Asian Development Bank, the African Development Bank, the Inter-American Development Bank), national research councils that publish in English across Africa, Asia, Oceania, and Latin America, bilateral aid agencies, and domain-specific bodies covering AI governance and global health. This source list constitutes the primary differentiator and intellectual moat of the product. The second layer is a Python-based crawler, built with standard libraries including Requests, BeautifulSoup, Scrapy, and Playwright for JavaScript-rendered sites, which visits each target domain on a scheduled basis and extracts raw page content, including PDF-hosted announcements. The third layer is an LLM extraction pipeline that passes each crawled page through a structured prompt to classify whether the content constitutes a genuine funding opportunity and, if so, to extract structured metadata fields: funder name, deadline, funding range, geographic eligibility, thematic domain, and — critically — applicant-type fields that no existing database consistently captures, namely whether the opportunity is open to individuals, whether institutional affiliation is required, and whether a fiscal sponsor suffices in lieu of a registered nonprofit. The fourth layer is a static searchable database and filterable interface, hosted at zero cost on GitHub Pages or Netlify during the prototype phase, requiring no cloud infrastructure prior to the securing of external funding. The fifth layer is a freshness mechanism that re-crawls source domains weekly and automatically flags lapsed deadlines.

The primary users are independent researchers — those without institutional affiliation, based outside Western funding corridors, working across AI governance, global health, climate, and adjacent fields — for whom existing tools return systematically unhelpful results. A secondary user group comprises research-active professionals at under-resourced institutions in low- and middle-income countries who lack access to subscription-gated databases. The revenue model during the prototype phase is grant-funded, with GrantGlobe positioned as an open-source public good whose eligibility-inference layer, geographic coverage, and open licensing create natural alignment with funders such as the Mozilla Foundation, the Patrick J. McGovern Foundation, and pooled philanthropic vehicles focused on democratising research infrastructure. Post-prototype, a freemium model is viable, with a free tier providing full search access and a paid tier offering personalised eligibility alerts, deadline tracking, and API access for institutional research offices.

The development timeline runs from April through August 2026. Months one and two focus on source list compilation and crawler deployment across an initial domain set. Months three and four deliver the LLM extraction pipeline and structured database. Month five produces the filterable interface and soft public launch. Months six through eight incorporate user feedback, expand source coverage, and refine extraction quality. By August, a working MVP is publicly available, with geographic and eligibility-metadata coverage exceeding any existing tool and a documented open methodology suitable for peer review and funder reporting.

GrantGlobe emerges directly from lived experience. Having built the most geographically comprehensive open AI dataset in existence — the Global AI Indicator Database (GAID), covering 227 countries across 20 thematic domains — I encountered at first hand the same geographic blindspot in the funding infrastructure that GAID was designed to correct in the data infrastructure. The researcher who built the dataset is also the researcher who consistently cannot locate appropriate funding for it. GrantGlobe is the systematic answer to that problem.

The distinguishing methodological contribution of GrantGlobe relative to existing tools is the eligibility-inference layer. Current grant databases are designed from the funder's perspective: they catalogue what a funder offers, but do not systematically infer whether a given applicant profile can legally or practically access it. A researcher who is an individual, unaffiliated, and based outside the United States may discover through GrantGlobe not only that an opportunity exists but also that it requires United States 501(c)(3) nonprofit status — information that saves application effort and redirects attention to opportunities where eligibility is genuine. No existing database captures this at scale. Building it requires a combination of structured LLM extraction and a controlled vocabulary of eligibility categories applied consistently across the full source list. This is the technical challenge at the core of the project, and it is the feature that most directly addresses the frustration that motivated its design.

---

### (2) What is something you've done that you're most proud of?

*(990–1,010 words; milestone-based GAID Project)*

The project I am most proud of is the Global AI Indicator Database (GAID) Project, a self-initiated, self-funded, milestone-based research infrastructure initiative that I began building in November 2025. The GAID Project emerged from a straightforward observation and a deliberate decision to act on it: global panel data on artificial intelligence are scattered across disparate institutional reports, interactive dashboards, and downloadable datasets produced by different organisations on different schedules in different formats. No centralised, standardised, publicly accessible longitudinal panel dataset existed that would allow researchers, data scientists, and policy teams to study AI across countries, domains, and time without first conducting weeks of manual data engineering themselves. I concluded that I could build one, and I did.

The overarching aim of the GAID Project is to close existing data and research gaps in the global AI landscape by constructing open-access data infrastructure that facilitates rigorous, reproducible, and globally inclusive AI research. The project is milestone-based and explicitly designed to be ever-scaling: each completed phase delivers a standalone output whilst simultaneously enabling the next phase. As of March 2026, I have completed Phases 0 through 2 and am actively developing Phases 3 and 4.

Phase 0 involved engineering a web application, AI in Society (https://aiinsocietyhub.com/), in December 2025. The platform serves two primary functions. First, it provides a non-paywalled, publicly accessible space for data-driven articles addressing AI societal impacts — a genre underserved by both academic publishing (which is paywalled) and popular technology media (which is non-specialist). Second, it hosts a curated AI Opportunities Board featuring fellowships and funding opportunities that are relevant to the AI safety and AI governance research community but often absent from established aggregators such as the EA Opportunities Board or the 80,000 Hours Job Board. Phase 0 also established a centralised home for all future GAID Project deliverables, ensuring that outputs are housed on a single platform rather than distributed across disconnected repositories and data archives.

Phase 1 produced the first public release of the GAID dataset (Version 1), deposited on Harvard Dataverse in January 2026 (DOI: 10.7910/DVN/QYLYSA). The dataset covers 214 countries and territories from 1998 to 2025, comprising over 2.3 million data points across eight thematic domains, including AI governance, research and development, education, diversity, and responsible AI. Data were harmonised from three major global AI databases — Stanford's AI Index, the Global Index on Responsible AI (GIRAI), and OECD.ai — through 123 documented cleaning and deduplication steps designed to optimise data integrity. The methodological contribution of Phase 1 was not merely compilation; it was the construction of a reproducible data engineering pipeline capable of harmonising heterogeneous sources into a single, analysis-ready longitudinal panel.

Phase 2 expanded the dataset substantially. Version 2, also deposited on Harvard Dataverse (DOI: 10.7910/DVN/PUMGYU), covers 227 countries and territories, 24,453 unique metrics, and 20 thematic domains, integrating eight additional data sources: the UNESCO AI Ethics Observatory, the IEA Energy and AI Observatory, Epoch AI, the MacroPolo AI Talent Tracker, WIPO AI Patent Landscapes, the Coursera Global Skills Report, the Tortoise Media Global AI Index, and the World Bank GovTech Maturity Index. The resulting dataset spans 1998 to 2025 and represents, to my knowledge, the most geographically and thematically comprehensive open-access longitudinal AI dataset currently available.

An exploratory precursor to Phases 3 and 4 was conducted as an Apart Research project and subsequently published as an arXiv preprint (arXiv:2602.13246). Using GAID Version 2 as ground truth, I stress-tested the Llama-3 8B model with 1,704 queries across 213 countries and eight technical metrics, identifying a significant knowledge gap separating the Global North and the Global South: the model produced factual responses in only 11.4% of queries, with knowledge heavily concentrated in higher-income regions.

Phases 3 and 4, currently in development, constitute a Global AI Bias Audit: an automated evaluation and interpretability dashboard for foundation models and AI agents. The planned objectives are threefold. First, I will build an interactive visualisation layer on top of the GAID dataset, incorporating heatmaps and radar charts for all 227 countries across all 20 thematic domains, hosted on the AI in Society platform as a publicly accessible dashboard. Second, I will engineer an automated AI evaluation pipeline to systematically stress-test major foundation models — including GPT, Gemini, and Claude — against GAID as a structured ground truth, measuring factual accuracy and geographic coverage across socioeconomic tiers. Third, the large-scale audit findings will be written up as a peer-reviewed paper targeting arXiv submission and a venue such as NeurIPS 2027, with all code open-sourced.

The GAID Project represents the kind of research I believe most needs doing and least gets funded: foundational, open, globally inclusive data infrastructure that enables other researchers to ask questions they currently cannot. Every phase has been completed without external funding, on the basis of methodological conviction and a recognition that waiting for institutional support before beginning substantive work is itself a choice with costs.

What makes the GAID Project a source of genuine pride is not simply the scale of the output — though covering 227 countries across 24,453 unique metrics across 27 years is not a trivial undertaking for a single independent researcher — but the methodological rigour brought to each phase, the explicit commitment to geographic inclusivity as a design principle rather than an aspiration, and the decision to make every output freely and publicly accessible. In an era when AI research infrastructure is increasingly consolidated within a small number of well-resourced laboratories and institutions, the GAID Project is a deliberate attempt to construct a counterweight: a piece of global public goods infrastructure that any researcher, anywhere, can use. The transition from Phase 2 data curation to Phase 3 automated evaluation reflects a natural and logical extension of the same underlying question — what does AI actually know about the world, and whose world does it know? — that has motivated the project from the outset. Answering that question rigorously, at scale, and with openly available tools and data is what Phases 3 and 4 are designed to accomplish.

---

## 7. Terminology Clarification

**Prototype vs. MVP**

| Term | Definition |
|---|---|
| Prototype | Proof of concept; not publicly available; demonstrates technical feasibility; shown to funders or small tester groups; not expected to work reliably at scale |
| MVP (Minimum Viable Product) | Smallest version that delivers genuine value to real users and is publicly available; works, is usable, and solves the core problem for a defined user group; deliberately not feature-complete |

The August 2026 target is an **MVP** — publicly available, solving a real problem for a real user group, with a documented methodology, and deliberately deferring live crawling, cloud hosting, and advanced alerting until post-funding validation. Calling it an MVP signals product development discipline; it is a stronger claim than "prototype."

---

*Conversation date: 8 March and 27 March 2026. GAID Project EA Forum post: https://forum.effectivealtruism.org/posts/DvzguceNKaQcYPgwb/the-global-ai-dataset-gaid-project-from-closing-research*
