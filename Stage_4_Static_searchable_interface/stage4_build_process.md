# GrantGlobe Stage 4 — Static Searchable Interface: Build Process Documentation

**Author:** Jason Hung  
**Reviewer:** openclaw team  
**Date:** May 2026  
**Scope:** Stage 4 of the GrantGlobe prototype — a zero-backend, statically served searchable interface for the grant database produced by Stage 3.

---

## 1. Stage 4 in the GrantGlobe Architecture

GrantGlobe is structured as a five-stage pipeline:

| Stage | Description |
|---|---|
| 1 — Source List | Curated registry of grant-publishing websites |
| 2 — Crawler | Automated content retrieval from source URLs |
| 3 — LLM Extraction | Structured grant record extraction and PostgreSQL persistence |
| **4 — Static Interface** | **Export + browser-side searchable interface (this stage)** |
| 5 — Freshness Mechanism | Scheduled re-crawl and status refresh (implemented within Stages 2–3) |

Stage 4 sits at the user-facing end of the pipeline. Its inputs are the quality-assured grant records stored in the Stage 3 PostgreSQL database; its output is a static HTML page that a grant-seeker can open in a browser and search, filter, and explore without any server-side computation.

---

## 2. Architectural Decision: Static Site over Dynamic Backend

### Why static?

A conventional approach would build a server-side application (e.g. Django, Flask, FastAPI) that queries PostgreSQL in response to each user request. For the MVP prototype, this approach was rejected on the following grounds:

- **Cost.** A static site served via GitHub Pages incurs zero hosting cost. A persistent server process (even the smallest cloud VM or managed container) incurs ongoing cost that is inappropriate before the project generates revenue.
- **Complexity.** A backend application introduces a deployment surface, API versioning, authentication concerns, and uptime obligations that are not necessary at the prototype stage.
- **Sufficient capability.** The grant dataset at MVP scale (hundreds to low thousands of records) fits comfortably in a single JSON file. Modern browser JavaScript — specifically the Fuse.js fuzzy-search library — can execute all search and filter operations client-side with sub-millisecond latency on this scale.
- **Separation of concerns.** The static export model decouples the data pipeline (Stages 1–3, which run on a schedule) from the interface. The interface is updated simply by regenerating `data/grants.json` and pushing it to the repository.

### Upgrade path

When the project reaches pre-seed stage and the dataset exceeds what is practical to serve as a flat JSON file (rough threshold: above ~20,000 records, or when server-side personalisation is required), the interface can be migrated to a dynamic backend without altering the data pipeline. The static interface is therefore a deliberate interim architecture, not a permanent design constraint.

---

## 3. Components Built

Stage 4 was constructed in three phases, each implemented by issuing a structured prompt to the Cursor AI coding assistant and subsequently audited and corrected by hand.

### Phase 0 — `export_grants.py`

**Purpose:** Query the Stage 3 PostgreSQL `grants` table and serialise approved records to `data/grants.json`.

**Inclusion rule:**
```
(review_status = 'approved')
OR (requires_review = false AND review_status = 'pending')
```
Records with `review_status = 'rejected'`, and those where `requires_review = true AND review_status = 'pending'`, are excluded. Records with `current_status = 'Closed'` are excluded by default; the `--include-closed` flag overrides this.

**Sort order in the output JSON:**

| Priority | Status |
|---|---|
| 1 | Open |
| 2 | Upcoming |
| 3 | Rolling |
| 4 | All other statuses (None, Suspended, etc.) |
| 5 | Closed |

Within each status group, records are sorted by `application_deadline ASC NULLS LAST`.

**Columns exported** (29 fields):

`id`, `grant_title`, `funder_name`, `source_url`, `application_portal_url`, `description`, `application_deadline`, `application_deadline_raw`, `application_deadline_type`, `deadline_notes`, `eoi_deadline`, `eoi_deadline_raw`, `grant_opening_date`, `funding_amount_min`, `funding_amount_max`, `currency`, `current_status`, `source_language`, `ai_focused`, `individuals_not_eligible`, `organisation_types`, `individual_eligibility`, `applicant_base_regions`, `applicant_base_countries`, `geographic_focus_regions`, `geographic_focus_countries`, `thematic_sectors`, `grant_types`, `domain`, `crawl_date`.

The JSONB audit columns `confidence_scores` and `raw_extraction` are deliberately omitted — they are internal quality-assurance artefacts not needed by the interface.

**Serialisation rules:**

| PostgreSQL type | JSON serialisation |
|---|---|
| DATE / DATETIME | ISO 8601 string (`value.isoformat()`) |
| NUMERIC (Decimal) | `float(value)` |
| UUID | `str(value)` |
| TEXT[] (array) | Python list; NULL → `[]` for array columns |
| NULL (non-array column) | `null` |

Array columns that are NULL in the database serialise as `[]` rather than `null`. This simplifies the JavaScript side, which can call `.includes()` and `.slice()` on these fields without null-guards.

**Output format:**
```json
{
  "metadata": {
    "exported_at": "2026-05-28T14:00:00+00:00",
    "total_grants": 312,
    "schema_version": "1.0",
    "includes_closed": false
  },
  "grants": [ … ]
}
```

**CLI interface:**
```
python export_grants.py
python export_grants.py --include-closed
python export_grants.py --output /path/to/custom.json
```

**Environment:** Reads `DATABASE_URL` from environment or a `.env` file in the script directory (via `python-dotenv`). Exits with a clear error message if `DATABASE_URL` is unset or if the connection fails.

**Bug found during audit:** In the initial Cursor build, `main()` recomputed `exported_at` with a second `datetime.datetime.now()` call after `export()` had already written the JSON. The timestamp printed to the terminal was therefore always slightly later than the timestamp recorded in the JSON metadata. Fixed by returning `exported_at` from `export()` and using that value in `main()`:
```python
# Before fix:
def export(...) -> int:
    ...
    return len(grants)

def main():
    total = export(...)
    exported_at = datetime.datetime.now(...)   # second, later timestamp

# After fix:
def export(...) -> tuple[int, str]:
    ...
    return len(grants), exported_at

def main():
    total, exported_at = export(...)           # single, consistent timestamp
```

---

### Phase A — `index.html` and `styles.css`

**Purpose:** Define the page structure and visual design. No JavaScript logic is present in these files.

#### `index.html` — structure

The document is organised top-to-bottom as follows:

1. **`<head>`** — UTF-8 charset, viewport meta, title (`GrantGlobe — Find Funding`), Inter typeface loaded via Google Fonts preconnect (weights 400/500/600/700), Fuse.js 7.x loaded synchronously from jsDelivr CDN, `styles.css` linked.
2. **`.site-header`** — sticky, 64px. Wordmark ("GrantGlobe") left; subtitle ("Open funding intelligence") right.
3. **`.hero`** — min-height 120px, centred. Contains `#search-input` (type=search) and `#result-count` span below it.
4. **`.filter-strip`** — horizontal row of four `<select>` elements and one `<button>`:
   - `#filter-status`: All Statuses / Open / Upcoming / Rolling / Closed (static options).
   - `#filter-region`: All Regions + 11 UN macro-regions (static options, pre-populated in HTML).
   - `#filter-sector`: placeholder only — populated dynamically by `app.js` from the dataset.
   - `#filter-org-type`: placeholder only — populated dynamically by `app.js`.
   - `#reset-filters`: "Clear filters" button.
5. **`#grant-grid`** — empty `<div>`, populated by `app.js`.
6. **`#modal-overlay`** — `role="dialog" aria-modal="true"`, starts with the `hidden` class. Contains `#modal-content`, which `app.js` populates on card click.
7. **`.site-footer`** — disclaimer text.
8. **`<script src="app.js" defer>`** — loaded last, deferred so all DOM elements are available when the script executes.

All 11 element IDs that `app.js` references are present: `search-input`, `result-count`, `filter-status`, `filter-region`, `filter-sector`, `filter-org-type`, `reset-filters`, `grant-grid`, `modal-overlay`, `modal-content`, `modal-close`.

**Note on Fuse.js load order:** Fuse.js is loaded as a synchronous (non-deferred) script in `<head>`. This guarantees that `window.Fuse` is defined before `app.js` executes (since `app.js` is deferred and therefore runs only after the HTML has been fully parsed, by which point all synchronous `<head>` scripts have already executed).

#### `styles.css` — design tokens and component styles

**Design tokens** (CSS custom properties on `:root`):

```css
--clr-bg:           #F8F9FA
--clr-surface:      #FFFFFF
--clr-primary:      #2563EB
--clr-primary-dark: #1D4ED8
--clr-text:         #111827
--clr-text-muted:   #6B7280
--clr-border:       #E5E7EB
--clr-open:         #16A34A
--clr-upcoming:     #D97706
--clr-rolling:      #2563EB
--clr-closed:       #6B7280
--radius:           8px
--shadow:           0 1px 3px rgba(0,0,0,0.10), 0 1px 2px rgba(0,0,0,0.06)
```

**Component highlights:**

- **Grant card (`.grant-card`):** CSS grid using `repeat(auto-fill, minmax(320px, 1fr))`, 20px gap. Cards hover with `translateY(-2px)` and a deeper shadow at 150ms ease.
- **Status badges (`.badge--open/.badge--upcoming/.badge--rolling/.badge--closed`):** pill-shaped, with light background tints and matching text colours drawn from the design-token palette.
- **Modal:** `position: fixed; inset: 0; z-index: 1000`, overlay at `rgba(0,0,0,0.50)`. Modal content: max-width 720px, max-height 90vh, `overflow-y: auto` (chosen over `overflow-y: scroll` to avoid a persistent scrollbar when content fits within the viewport height — an improvement on the specification). Slide-up animation at 180ms ease.
- **Responsive breakpoints:** ≤640px: filter strip wraps to multiple rows; ≤480px: grid collapses to a single column, header subtitle hidden.

**No bugs found in Phase A files.**

---

### Phase B Prompt 1 — `app.js`: data loading, card rendering, and detail modal

`app.js` is structured as a single `'use strict'` module with a `DOMContentLoaded` bootstrap.

#### Data loading

```javascript
fetch('data/grants.json')
  .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
  .then(payload => init(payload.grants))
  .catch(err => showError(err));
```

On failure (including the `file://` protocol CORS block that occurs when the page is opened directly from the filesystem), `showError()` renders a message in `#grant-grid` instructing the user to use `python -m http.server`.

#### Module-level state

```javascript
const state = {
  allGrants: [],   // full dataset, set once in init()
  filtered:  [],   // current filtered + searched subset
};
```

#### `init(grants)`

Sets `state.allGrants` and `state.filtered`, then calls `populateDynamicFilters`, `renderCards`, and `updateResultCount`.

#### `populateDynamicFilters(grants)`

Scans all grant records to collect unique values from `thematic_sectors` and `organisation_types`. Sorts each set alphabetically and appends `<option>` elements to `#filter-sector` and `#filter-org-type` respectively, without removing the existing placeholder options.

#### `renderCards(grants)`

Clears `#grant-grid` via `innerHTML = ''`, then builds each card as a temporary `<div>` wrapper and appends `tmp.firstElementChild` to a `DocumentFragment`. The `DocumentFragment` is appended to the grid in a single DOM operation. This approach preserves event delegation on `#grant-grid` (the click listener attached to the grid is never removed).

**Card structure:**
```html
<div class="grant-card" tabindex="0" data-id="{{grant.id}}">
  <div class="grant-card__header">
    <span class="grant-card__title">…</span>
    <span class="badge badge--{{statusClass}}">…</span>
  </div>
  <div class="grant-card__funder">…</div>
  <div class="grant-card__meta">
    <span class="grant-card__deadline">…</span>
    <span class="grant-card__amount">…</span>  <!-- omitted if no amount data -->
  </div>
  <div class="grant-card__sectors">…</div>
</div>
```

**Deadline display logic:**
- `application_deadline` is non-null → `"Deadline: 30 Jun 2027"` (formatted via `formatDate`).
- `application_deadline` is null and `current_status === 'Rolling'` → `"Rolling deadline"`.
- All other cases → `"Deadline: TBC"`.

**Formatting helpers:**

`formatDate(isoStr)` appends `T00:00:00` to the ISO date string before constructing a `Date` object, preventing the browser's UTC-to-local shift (an ISO-only date string like `"2027-06-30"` is parsed as UTC midnight, which renders as the previous calendar day in UTC− time zones).

`formatAmount(grant)` builds a human-readable funding range string. Returns `null` when no amount data is present. Currency symbols used: `£` (GBP), `€` (EUR), `$` (USD); all others prefixed as the currency code followed by a non-breaking space.

`esc(value)` HTML-escapes `&`, `<`, `>`, `"`, and `'` before any user-data value is inserted into an HTML string, preventing XSS.

#### Detail modal (`openModal` / `closeModal`)

`openModal(grant)` constructs the full modal HTML string from the grant record and assigns it to `#modal-content.innerHTML`. It then re-attaches the `#modal-close` click listener (necessary because `innerHTML` assignment destroys the previous DOM node and any listeners attached to it) and removes the `hidden` class from `#modal-overlay`.

The modal displays: grant title + status badge, funder name, application deadline (with "(estimated)" note where applicable), EOI deadline (if present), funding amount with currency (if present), description, eligible organisation types, geographic focus (regions and countries combined), thematic sectors, grant types (if present), and an "Apply / View Grant ↗" link (preferring `application_portal_url` over `source_url`). Empty array fields display a "Not specified" tag.

Modal close is triggered by: clicking the `#modal-close` button; clicking the overlay background (detected by `e.target === modal-overlay`); or pressing the `Escape` key. All three listeners are attached once at `DOMContentLoaded` and are never removed.

**Bug found during audit:** In the initial Cursor build, the thematic-sectors join separator in `renderCards` was `'· '` (middle dot + space, no leading space), producing `"Health Research· Climate Action"` rather than the specified `"Health Research · Climate Action"`. Fixed to `' · '` (space + middle dot + space).

---

### Phase B Prompt 2 — `app.js`: search and filter engine

`applySearchAndFilters()` replaces the stub function in place. All other functions in `app.js` are untouched.

#### Execution order

1. **Read UI state** — query string (trimmed), and the values of all four filter selects.
2. **Hard filter** — a single `Array.prototype.filter` pass over `state.allGrants`. Each of the four selects is applied only when its value is non-empty:
   - Status: `grant.current_status === status`
   - Region: `(grant.geographic_focus_regions || []).includes(region)`
   - Sector: `(grant.thematic_sectors || []).includes(sector)`
   - Org type: `(grant.organisation_types || []).includes(orgType)`
3. **Fuse.js fuzzy search** — only instantiated when `query.length > 0`. Applied on the already hard-filtered subset:
   ```javascript
   const fuse = new Fuse(hardFiltered, {
     keys: [
       { name: 'grant_title',      weight: 0.40 },
       { name: 'funder_name',      weight: 0.30 },
       { name: 'description',      weight: 0.15 },
       { name: 'thematic_sectors', weight: 0.15 },
     ],
     threshold:          0.35,
     ignoreLocation:     true,
     minMatchCharLength: 2,
   });
   state.filtered = fuse.search(query).map(r => r.item);
   ```
   When the query is empty, `state.filtered = hardFiltered` (preserving the original `grants.json` sort order: Open → Upcoming → Rolling → Others → Closed, then by deadline ascending).
4. **Render** — `renderCards(state.filtered)` and `updateResultCount(state.filtered.length, state.allGrants.length)`.

**Design note on Fuse.js and array fields:** In Fuse.js 7.x, when a search key points to an array of strings (as `thematic_sectors` does), Fuse searches within each element of the array individually. No pre-processing of the field is required.

**No bugs found in Phase B Prompt 2.**

---

### Phase C — Deployment files

Three files were added to complete the deployment configuration.

**`.nojekyll`** (empty, 0 bytes): Placed at the root of the `Stage_4_Static_Searchable_Interface/` directory. Instructs GitHub Pages to bypass the Jekyll build pipeline entirely. Without this file, Jekyll would silently ignore any file or directory whose name begins with an underscore (e.g. `_data/`, `_site/`) and might interfere with the static file structure.

**`data/.gitkeep`** (empty, 0 bytes): Ensures the `data/` directory is tracked by git in the absence of `grants.json`. Without this file, git would not commit an empty directory, and a fresh clone of the repository would be missing the `data/` folder, causing the fetch to fail even after `export_grants.py` is run (since the directory the script writes to would not exist — though `export_grants.py` calls `output_path.parent.mkdir(parents=True, exist_ok=True)`, so this is a belt-and-braces precaution rather than a hard requirement).

**`README.md`**: Documents prerequisites, the three-step deployment workflow (export → local preview → GitHub Pages), the data-refresh procedure, the directory structure, and CDN dependencies. The `data/grants.json` file is committed to the repository so GitHub Pages can serve it; it is not gitignored.

---

## 4. Complete File Inventory

```
Stage_4_Static_Searchable_Interface/
├── export_grants.py          # Phase 0 — PostgreSQL → data/grants.json
├── index.html                # Phase A — page structure and CDN imports
├── styles.css                # Phase A — visual design and layout
├── app.js                    # Phase B — data loading, rendering, search, modal
├── data/
│   ├── .gitkeep              # Phase C — ensures directory is tracked by git
│   └── grants.json           # Generated by export_grants.py (not yet present)
├── .nojekyll                 # Phase C — disables Jekyll on GitHub Pages
├── README.md                 # Phase C — deployment documentation
└── cursor_prompts_stage4.md  # Build prompts archive
```

---

## 5. Bugs Found and Fixed During Audit

Fixes are listed in the order they were identified and applied across three audit rounds.

### Round 1 — Initial Cursor build

| File | Bug | Fix |
|---|---|---|
| `export_grants.py` | `main()` recomputed `exported_at` with a second `datetime.datetime.now()` call after `export()` had already written the JSON, producing a slightly later timestamp in the terminal output than in the file | `export()` changed to return `tuple[int, str]`; `main()` uses the returned timestamp for printing |
| `app.js` | Thematic-sectors join separator in `renderCards` was `'· '` (no leading space), producing `"Sector A· Sector B"` | Changed to `' · '` (space + middle dot + space) |

No bugs were found in `index.html`, `styles.css`, or the Phase B Prompt 2 implementation.

### Round 2 — Post-openclaw review (four confirmed gaps)

| File | Issue | Fix |
|---|---|---|
| `styles.css` | `.grant-card--closed` CSS class absent — closed grants rendered identically to open ones | Added `.grant-card--closed { opacity: 0.65; }` after `.grant-card:focus-visible` |
| `app.js` | `renderCards` never applied `.grant-card--closed` to the card element | Added `closedClass` conditional and interpolated into the card's class attribute |
| `app.js` | Search input fired `applySearchAndFilters` on every keystroke with no delay | Replaced direct listener with 200ms debounce via `_searchTimer` in `DOMContentLoaded` scope |
| `app.js` | `payload.metadata` was discarded — fetch passed only `payload.grants` to `init()` | `payload.metadata \|\| {}` now forwarded into `init()`; new `populateMetadata()` function writes `"N grants · Last updated D Mon YYYY"` to `.site-header__subtitle` |
| `export_grants.py` | `_STATUS_ORDER` and `_STATUS_ORDER_DEFAULT` defined but never referenced — SQL `CASE WHEN` is the sole sort driver | Both constants deleted |

### Round 3 — Post-openclaw review (two small spec inconsistencies)

| File | Issue | Fix |
|---|---|---|
| `app.js` | `populateMetadata` used `grants.length` as the displayed count rather than the authoritative `metadata.total_grants` field | Changed to `metadata.total_grants ?? grantCount` so the JSON metadata is the primary source; `grantCount` is the fallback |
| `app.js` | Card funding amounts displayed without the currency code (e.g. `£50,000`) while the modal displayed it correctly (e.g. `£50,000 (GBP)`) | `renderCards` now appends the ISO currency code after the formatted amount: `£50,000 GBP` |

---

## 6. Deployment Workflow

### Initial deployment

```bash
# 1. Populate the database (Stages 2 and 3 must have been run)
# 2. Export grant data
cd Stage_4_Static_Searchable_Interface/
python export_grants.py

# 3. Preview locally (do NOT open index.html directly — fetch() fails on file://)
python -m http.server 8000
# Open http://localhost:8000

# 4. Commit and push
git add .
git commit -m "Stage 4: initial static interface with grant export"
git push

# 5. Enable GitHub Pages
# Repository Settings → Pages → Source: branch + folder
```

### Refreshing data after pipeline re-runs

```bash
cd Stage_4_Static_Searchable_Interface/
python export_grants.py
git add data/grants.json
git commit -m "Refresh grant data"
git push
```

GitHub Pages will serve the updated `grants.json` on the next page load. No rebuild step is required.

---

## 7. Known Limitations and Future Considerations

**File-size ceiling.** The flat-JSON architecture is appropriate up to approximately 20,000 grant records (estimated ~30–50 MB JSON). Beyond this threshold, initial page load time will degrade and Fuse.js indexing will become noticeably slow. At that point, a paginated API backend should replace the current fetch-all approach.

**Search relevance.** Fuse.js fuzzy search with `threshold: 0.35` and `ignoreLocation: true` provides adequate recall for keyword and funder name searches. It does not support Boolean operators, phrase matching, or field-scoped queries. A more capable search backend (e.g. PostgreSQL full-text search via an API, or a managed search service) would be appropriate at production scale.

**No authentication or access control.** The interface and its data are fully public. If GrantGlobe were to introduce restricted grant records (e.g. those requiring institutional affiliation to view), the static model would need to be supplemented with an access layer.

**No automated re-export.** The data in `grants.json` reflects the state of the database at the time `export_grants.py` was last run. There is no mechanism to trigger a re-export automatically when new grants are extracted by Stage 3. This could be addressed by integrating `export_grants.py` into the Stage 3 batch pipeline as a post-processing step.

**`javascript:` protocol in URLs.** The `esc()` function escapes HTML entities but does not sanitise `javascript:` protocol URLs in `source_url` or `application_portal_url`. In practice this is not a risk since all URLs originate from the GrantGlobe database, which is operator-controlled. If the data provenance were broadened (e.g. user-submitted URLs), a URL scheme whitelist (`https://` and `http://` only) should be added.
