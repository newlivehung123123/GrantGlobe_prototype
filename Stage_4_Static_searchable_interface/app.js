'use strict';

/* ============================================================
   GrantGlobe — app.js
   Phase B Prompt 1: data loading · card rendering · detail modal
   Phase B Prompt 2 will replace applySearchAndFilters() in-place.
   ============================================================ */

// ── Bootstrap ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // ── Fetch grant data ─────────────────────────────────────────────────
  fetch('data/grants.json')
    .then(res => { if (!res.ok) throw new Error(res.status); return res.json(); })
    .then(payload => init(payload.grants, payload.metadata || {}))
    .catch(err => showError(err));

  // ── Card interaction (event delegation on the grid) ──────────────────
  const grid = document.getElementById('grant-grid');

  grid.addEventListener('click', e => {
    const card = e.target.closest('.grant-card');
    if (!card) return;
    const grant = state.allGrants.find(g => g.id === card.dataset.id);
    if (grant) openModal(grant);
  });

  grid.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const card = e.target.closest('.grant-card');
    if (!card) return;
    e.preventDefault();
    const grant = state.allGrants.find(g => g.id === card.dataset.id);
    if (grant) openModal(grant);
  });

  // ── Modal close handlers (attached once) ─────────────────────────────
  document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  // ── Filter + search change handlers ──────────────────────────────────
  ['filter-status', 'filter-region', 'filter-sector', 'filter-org-type'].forEach(id => {
    document.getElementById(id).addEventListener('change', applySearchAndFilters);
  });

  let _searchTimer = null;
  document.getElementById('search-input').addEventListener('input', () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(applySearchAndFilters, 200);
  });

  document.getElementById('reset-filters').addEventListener('click', () => {
    ['filter-status', 'filter-region', 'filter-sector', 'filter-org-type'].forEach(id => {
      document.getElementById(id).value = '';
    });
    document.getElementById('search-input').value = '';
    applySearchAndFilters();
  });

  // ── Personalisation controls ─────────────────────────────────────────
  document.getElementById('sort-mode').addEventListener('change', e => {
    state.sortMode = e.target.value;
    applySearchAndFilters();
  });

  document.getElementById('personalize-toggle').addEventListener('click', () => {
    const panel  = document.getElementById('personalize-panel');
    const toggle = document.getElementById('personalize-toggle');
    const open   = panel.classList.toggle('hidden') === false;
    toggle.setAttribute('aria-expanded', String(open));
  });

  document.getElementById('pz-save').addEventListener('click', () => {
    saveProfileFromPanel();
    const panel = document.getElementById('personalize-panel');
    panel.classList.add('hidden');
    document.getElementById('personalize-toggle').setAttribute('aria-expanded', 'false');
    // Saving implies the user wants their personalised feed.
    state.sortMode = 'recommended';
    document.getElementById('sort-mode').value = 'recommended';
    applySearchAndFilters();
  });

  document.getElementById('pz-clear').addEventListener('click', () => {
    state.profile = null;
    try { localStorage.removeItem(LS_PROFILE); } catch (e) { /* ignore */ }
    syncPanelToProfile();
    updatePersonalizeLabel();
    applySearchAndFilters();
  });
});

// ── Module-level state ──────────────────────────────────────────────────────
const state = {
  allGrants: [],          // full dataset, set once in init()
  filtered:  [],          // current filtered + searched subset
  sortMode:  'recommended', // recommended | toprated | deadline | funding
  profile:   null,        // { stage, fields:[], region } from localStorage
  affinity:  null,        // { sectors:{}, funders:{} } learned from clicks
};

// localStorage keys
const LS_PROFILE  = 'gg_profile_v1';
const LS_AFFINITY = 'gg_affinity_v1';

// ── Error display ───────────────────────────────────────────────────────────
function showError(err) {
  console.error('Failed to load grants data:', err);
  const grid = document.getElementById('grant-grid');
  grid.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'grant-grid__empty';
  div.innerHTML =
    '<strong>Could not load grant data.</strong> ' +
    'Open this page via a local server (e.g. <code>python -m http.server</code>) ' +
    'rather than directly from the filesystem, or check that data/grants.json exists.';
  grid.appendChild(div);
}

// ── init ────────────────────────────────────────────────────────────────────
function init(grants, metadata) {
  state.allGrants = grants;
  state.profile   = loadProfile();
  state.affinity  = loadAffinity();
  populateDynamicFilters(grants);
  buildPersonalizePanel(grants);
  syncPanelToProfile();
  updatePersonalizeLabel();
  // Initial render uses the recommended ordering (global prior, personalised
  // if a saved profile/affinity exists).
  state.filtered = orderGrants(grants);
  renderCards(state.filtered);
  updateResultCount(state.filtered.length, grants.length);
  populateMetadata(metadata, grants.length);
}

// ── populateMetadata ────────────────────────────────────────────────────────
function populateMetadata(metadata, grantCount) {
  // Format the exported_at ISO string as a human-readable date.
  // exported_at is already UTC (ends in +00:00 or Z), so parse it directly.
  let dateStr = '';
  if (metadata.exported_at) {
    const d = new Date(metadata.exported_at);
    dateStr = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  // Build the meta string: "847 grants · Last updated 28 May 2026"
  const count = metadata.total_grants ?? grantCount;
  const parts = [];
  parts.push(`${count} grant${count !== 1 ? 's' : ''}`);
  if (dateStr) parts.push(`Last updated ${dateStr}`);
  const metaText = parts.join(' \u00b7 ');

  // Inject into the page subtitle in the header.
  // The .site-header__subtitle element already exists in the HTML.
  const subtitle = document.querySelector('.site-header__subtitle');
  if (subtitle) subtitle.textContent = metaText;
}

// ── populateDynamicFilters ──────────────────────────────────────────────────
function populateDynamicFilters(grants) {
  // Helper: append a sentinel "Not specified" option if any records have no value
  function maybeAddUnspecified(el, hasNone) {
    if (!hasNone) return;
    const sep = document.createElement('option');
    sep.disabled = true;
    sep.textContent = '──────────';
    el.appendChild(sep);
    const opt = document.createElement('option');
    opt.value = '__unspecified__';
    opt.textContent = 'Not specified';
    el.appendChild(opt);
  }

  // Regions
  const regions = new Set();
  let hasNoRegion = false;
  grants.forEach(g => {
    const ab = g.applicant_base_regions   || [];
    const gf = g.geographic_focus_regions || [];
    ab.forEach(r => { if (r) regions.add(r); });
    gf.forEach(r => { if (r) regions.add(r); });
    if (!ab.length && !gf.length) hasNoRegion = true;
  });
  const regionEl = document.getElementById('filter-region');
  [...regions].sort().forEach(r => {
    const opt = document.createElement('option');
    opt.value = r;
    opt.textContent = r;
    regionEl.appendChild(opt);
  });
  maybeAddUnspecified(regionEl, hasNoRegion);

  // Sectors
  const sectors = new Set();
  let hasNoSector = false;
  grants.forEach(g => {
    const ts = g.thematic_sectors || [];
    ts.forEach(s => { if (s) sectors.add(s); });
    if (!ts.length) hasNoSector = true;
  });
  const sectorEl = document.getElementById('filter-sector');
  [...sectors].sort().forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sectorEl.appendChild(opt);
  });
  maybeAddUnspecified(sectorEl, hasNoSector);

  // Organisation types
  const orgTypes = new Set();
  let hasNoOrgType = false;
  grants.forEach(g => {
    const ot = g.organisation_types || [];
    ot.forEach(t => { if (t) orgTypes.add(t); });
    if (!ot.length) hasNoOrgType = true;
  });
  const orgEl = document.getElementById('filter-org-type');
  [...orgTypes].sort().forEach(t => {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    orgEl.appendChild(opt);
  });
  maybeAddUnspecified(orgEl, hasNoOrgType);

  // Status — built dynamically from whatever current_status values actually
  // appear in the data, same as Region/Sector/Org Type above. This avoids
  // silently dropping records into "Not specified" whenever a connector
  // introduces a new status string (e.g. "Forthcoming", "Invitation Only")
  // that a hardcoded list hasn't been updated to recognise.
  const statuses = new Set();
  let hasNoStatus = false;
  grants.forEach(g => {
    if (g.current_status) statuses.add(g.current_status);
    else hasNoStatus = true;
  });
  const statusEl = document.getElementById('filter-status');
  [...statuses].sort().forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    statusEl.appendChild(opt);
  });
  maybeAddUnspecified(statusEl, hasNoStatus);
}

// ── Formatting helpers ──────────────────────────────────────────────────────

/**
 * Format an ISO-8601 date string as a human-readable date.
 * Appends T00:00:00 to force local-midnight parsing and avoid UTC date shift.
 */
function formatDate(isoStr) {
  if (!isoStr) return null;
  const d = new Date(isoStr + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * Build a human-readable funding range string.
 * Returns null when no amount data is present.
 */
function formatAmount(grant) {
  const fmt = (n, currency) => {
    if (n == null) return null;
    const sym = currency === 'GBP' ? '£'
              : currency === 'EUR' ? '€'
              : currency === 'USD' ? '$'
              : (currency ? currency + '\u00a0' : '');
    return sym + Number(n).toLocaleString('en-GB', { maximumFractionDigits: 0 });
  };
  const min = fmt(grant.funding_amount_min, grant.currency);
  const max = fmt(grant.funding_amount_max, grant.currency);
  if (min && max && min !== max) return `${min}\u2013${max}`;  // en-dash
  if (max) return `Up to ${max}`;
  if (min) return `From ${min}`;
  return null;
}

/**
 * Escape a plain-text value for safe insertion into HTML content or
 * attribute values.  Keeps the DOM-construction helpers XSS-safe.
 */
function esc(value) {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── renderCards ─────────────────────────────────────────────────────────────
function renderCards(grants) {
  const grid = document.getElementById('grant-grid');
  grid.innerHTML = '';

  if (!grants.length) {
    const empty = document.createElement('div');
    empty.className = 'grant-grid__empty';
    empty.innerHTML =
      '<strong>No grants match your search.</strong> ' +
      'Try adjusting your filters or search terms.';
    grid.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();

  grants.forEach(grant => {
    const cls         = (grant.current_status || 'unknown').toLowerCase().replace(/\s+/g, '-');
    const statusLabel = grant.current_status || 'Unknown';

    // Deadline text — some funders accept applications on a rolling basis
    // with no real deadline; their connector sets application_deadline_raw
    // to say so even though application_deadline itself holds a far-future
    // sentinel date (needed internally to keep the record's status fresh).
    // Prefer that raw text over the literal date whenever it says "rolling".
    let deadlineText;
    if (grant.application_deadline_raw && /rolling/i.test(grant.application_deadline_raw)) {
      deadlineText = 'Rolling deadline';
    } else if (grant.application_deadline) {
      deadlineText = 'Deadline: ' + formatDate(grant.application_deadline);
    } else if (grant.current_status === 'Rolling') {
      deadlineText = 'Rolling deadline';
    } else {
      deadlineText = 'Deadline: TBC';
    }

    // Funding amount — append currency code to match modal display ("£50,000 GBP")
    const amount    = formatAmount(grant);
    const amountWithCurrency = amount && grant.currency
      ? `${amount} ${grant.currency}`
      : amount;
    const amountHtml = amountWithCurrency
      ? `<span class="grant-card__amount">${esc(amountWithCurrency)}</span>`
      : '';

    // Thematic sectors — at most 3, joined by · (middle dot)
    const sectorsText = (grant.thematic_sectors || []).slice(0, 3).join(' \u00b7 ');

    // Build card using a temporary container so we can extract the element.
    // We never assign directly to grid.innerHTML to preserve event delegation.
    const closedClass = grant.current_status === 'Closed' ? ' grant-card--closed' : '';
    const forYouHtml = grant._forYou
      ? `<span class="grant-card__foryou" aria-label="Recommended for you">✦ For you</span>`
      : '';
    const tmp = document.createElement('div');
    tmp.innerHTML =
      `<div class="grant-card${closedClass}" tabindex="0" data-id="${esc(grant.id)}">` +
        forYouHtml +
        `<div class="grant-card__header">` +
          `<span class="grant-card__title">${esc(grant.grant_title)}</span>` +
          `<span class="badge badge--${esc(cls)}">${esc(statusLabel)}</span>` +
        `</div>` +
        `<div class="grant-card__funder">${esc(grant.funder_name)}</div>` +
        `<div class="grant-card__meta">` +
          `<span class="grant-card__deadline">${esc(deadlineText)}</span>` +
          amountHtml +
        `</div>` +
        `<div class="grant-card__sectors">${esc(sectorsText)}</div>` +
      `</div>`;

    fragment.appendChild(tmp.firstElementChild);
  });

  grid.appendChild(fragment);
}

// ── updateResultCount ───────────────────────────────────────────────────────
function updateResultCount(shown, total) {
  const el = document.getElementById('result-count');
  if (shown === total) {
    el.textContent = `Showing all ${total} grant${total !== 1 ? 's' : ''}`;
  } else {
    el.textContent = `Showing ${shown} of ${total} grant${total !== 1 ? 's' : ''}`;
  }
}

// ── openModal ───────────────────────────────────────────────────────────────
function openModal(grant) {
  // Behavioural signal: opening a grant nudges future recommendations toward
  // its sectors and funder (stored client-side, like a feed that learns).
  recordAffinity(grant);

  const cls         = (grant.current_status || 'unknown').toLowerCase();
  const statusLabel = grant.current_status || 'Unknown';

  // ── Deadline ────────────────────────────────────────────────────────
  // Same rolling-basis check as the card view — see comment there.
  const isRolling = grant.application_deadline_raw && /rolling/i.test(grant.application_deadline_raw);
  const deadlineText = isRolling
    ? 'Rolling (no fixed deadline)'
    : grant.application_deadline
      ? formatDate(grant.application_deadline)
      : 'TBC';
  const deadlineTypeNote =
    grant.application_deadline_type === 'estimated'
      ? ' <span style="color:var(--clr-text-muted);font-size:13px;">(estimated)</span>'
      : '';

  // ── EOI deadline ────────────────────────────────────────────────────
  const eoiHtml = grant.eoi_deadline
    ? `<p class="modal-section-label" style="margin-top:12px;">EOI Deadline</p>` +
      `<p class="modal-section-value">${esc(formatDate(grant.eoi_deadline))}</p>`
    : '';

  // ── Funding section ─────────────────────────────────────────────────
  const amount = formatAmount(grant);
  const fundingSection = amount
    ? `<div class="modal-section">` +
        `<p class="modal-section-label">Funding</p>` +
        `<p class="modal-section-value">${esc(amount)}` +
          (grant.currency
            ? ` <span style="color:var(--clr-text-muted);">(${esc(grant.currency)})</span>`
            : '') +
        `</p>` +
      `</div>`
    : '';

  // ── Tag builder ─────────────────────────────────────────────────────
  function makeTags(arr) {
    if (!arr || !arr.length) return '<span class="tag">Not specified</span>';
    return arr.map(t => `<span class="tag">${esc(t)}</span>`).join('');
  }

  // ── Geographic focus — merge regions + countries ─────────────────────
  const geoItems = [
    ...(grant.geographic_focus_regions  || []),
    ...(grant.geographic_focus_countries || []),
  ];

  // ── Grant types section ─────────────────────────────────────────────
  const grantTypesSection = (grant.grant_types || []).length
    ? `<div class="modal-section">` +
        `<p class="modal-section-label">Grant Types</p>` +
        `<div class="modal-tags">${makeTags(grant.grant_types)}</div>` +
      `</div>`
    : '';

  // ── Apply button — prefer application_portal_url over source_url ────
  const applyUrl = grant.application_portal_url || grant.source_url;
  const applyBtn = applyUrl
    ? `<a class="modal-apply-btn" href="${esc(applyUrl)}" target="_blank" ` +
        `rel="noopener noreferrer">Apply\u00a0/\u00a0View Grant\u00a0\u2197</a>`
    : '';

  // ── Compose modal HTML ──────────────────────────────────────────────
  const html =
    `<button id="modal-close" class="modal-close" aria-label="Close detail panel">\u2715</button>` +

    `<div class="modal-header">` +
      `<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding-right:32px">` +
        `<h2 id="modal-title" class="modal-title">${esc(grant.grant_title)}</h2>` +
        `<span class="badge badge--${esc(cls)}">${esc(statusLabel)}</span>` +
      `</div>` +
      `<p class="modal-funder">${esc(grant.funder_name)}</p>` +
    `</div>` +

    `<div class="modal-section">` +
      `<p class="modal-section-label">Application Deadline</p>` +
      `<p class="modal-section-value">${esc(deadlineText)}${deadlineTypeNote}</p>` +
      eoiHtml +
    `</div>` +

    fundingSection +

    `<div class="modal-section">` +
      `<p class="modal-section-label">Description</p>` +
      `<p class="modal-section-value">${esc(grant.description || 'No description available.')}</p>` +
    `</div>` +

    `<div class="modal-section">` +
      `<p class="modal-section-label">Eligible Organisation Types</p>` +
      `<div class="modal-tags">${makeTags(grant.organisation_types)}</div>` +
    `</div>` +

    `<div class="modal-section">` +
      `<p class="modal-section-label">Geographic Focus</p>` +
      `<div class="modal-tags">${makeTags(geoItems)}</div>` +
    `</div>` +

    `<div class="modal-section">` +
      `<p class="modal-section-label">Thematic Sectors</p>` +
      `<div class="modal-tags">${makeTags(grant.thematic_sectors)}</div>` +
    `</div>` +

    grantTypesSection +

    applyBtn;

  // Write into modal and re-attach close listener
  // (innerHTML replaces the old #modal-close element, so we must re-bind)
  const modalContent = document.getElementById('modal-content');
  modalContent.innerHTML = html;
  document.getElementById('modal-close').addEventListener('click', closeModal);

  // Reveal the overlay
  document.getElementById('modal-overlay').classList.remove('hidden');
}

// ── closeModal ──────────────────────────────────────────────────────────────
function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// ── Search & filter engine ──────────────────────────────────────────────────
function applySearchAndFilters() {
  // Step 1 — read current UI state
  const query   = document.getElementById('search-input').value.trim();
  const status  = document.getElementById('filter-status').value;
  const region  = document.getElementById('filter-region').value;
  const sector  = document.getElementById('filter-sector').value;
  const orgType = document.getElementById('filter-org-type').value;

  // Step 2 — hard filters (exact-match; skipped when the select is at "All …")
  // '__unspecified__' sentinel matches records with no value in that field.
  const hardFiltered = state.allGrants.filter(g => {
    // Status
    if (status === '__unspecified__') {
      if (g.current_status) return false;
    } else if (status !== '') {
      if (g.current_status !== status) return false;
    }
    // Region
    const ab = g.applicant_base_regions   || [];
    const gf = g.geographic_focus_regions || [];
    if (region === '__unspecified__') {
      if (ab.length || gf.length) return false;
    } else if (region !== '') {
      if (!ab.includes(region) && !gf.includes(region)) return false;
    }
    // Sector
    const ts = g.thematic_sectors || [];
    if (sector === '__unspecified__') {
      if (ts.length) return false;
    } else if (sector !== '') {
      if (!ts.includes(sector)) return false;
    }
    // Org type
    const ot = g.organisation_types || [];
    if (orgType === '__unspecified__') {
      if (ot.length) return false;
    } else if (orgType !== '') {
      if (!ot.includes(orgType)) return false;
    }
    return true;
  });

  // Step 3 — fuzzy search with Fuse.js (only when a query is typed)
  if (query.length > 0) {
    const fuse = new Fuse(hardFiltered, {
      keys: [
        { name: 'grant_title',      weight: 0.40 },
        { name: 'funder_name',      weight: 0.30 },
        { name: 'description',      weight: 0.15 },
        { name: 'thematic_sectors', weight: 0.15 },
      ],
      threshold:        0.35,
      ignoreLocation:   true,
      minMatchCharLength: 2,
    });
    // A typed query means the user is looking for something specific, so
    // text relevance leads. We keep Fuse's ordering rather than re-ranking.
    state.filtered = fuse.search(query).map(r => r.item);
    clearForYou(state.filtered);
  } else {
    // No query — order by the selected sort mode (recommended/personalised
    // by default) instead of the raw grants.json order.
    state.filtered = orderGrants(hardFiltered);
  }

  // Step 4 — render
  renderCards(state.filtered);
  updateResultCount(state.filtered.length, state.allGrants.length);
}

/* ============================================================
   Personalisation & ranking (Layer 2 — client-side)
   ------------------------------------------------------------
   The build-time ranking (ranking.py) writes a global prior `_rank_score`
   onto every grant. Here we re-rank that prior against a lightweight visitor
   profile and their click history — entirely in the browser, no backend.
   ============================================================ */

// Career-stage → eligibility keyword hints (matched against grant fields).
const STAGE_OPTIONS = [
  { value: 'student',     label: 'Student / PhD' },
  { value: 'early',       label: 'Postdoc / Early-career' },
  { value: 'established', label: 'Established researcher' },
  { value: 'nonprofit',   label: 'Non-profit / NGO' },
  { value: 'industry',    label: 'Industry / Startup' },
];

const STAGE_KEYWORDS = {
  student:     ['phd', 'doctoral', 'studentship', 'scholarship', 'student',
                'master', 'graduate', 'fellowship', 'early career', 'early-career'],
  early:       ['postdoc', 'post-doctoral', 'postdoctoral', 'early career',
                'early-career', 'fellowship', 'junior', 'new investigator', 'first grant'],
  established: ['research grant', 'project grant', 'programme grant', 'program grant',
                'investigator', 'senior', 'consolidator', 'advanced grant', 'professor'],
};

// Rough FX→USD for the "Funding (largest)" sort (mirrors ranking.py).
const FX_USD = {
  USD: 1, EUR: 1.08, GBP: 1.27, CHF: 1.10, CAD: 0.73, AUD: 0.66, NZD: 0.61,
  JPY: 0.0067, CNY: 0.14, HKD: 0.128, SGD: 0.74, KRW: 0.00073, INR: 0.012,
  SEK: 0.095, NOK: 0.094, DKK: 0.145, PLN: 0.25, CZK: 0.043, ZAR: 0.054,
  BRL: 0.18, MXN: 0.058, ILS: 0.27, AED: 0.27, SAR: 0.27, TWD: 0.031,
};

// ── localStorage persistence ──────────────────────────────────────────────
function loadProfile() {
  try { const raw = localStorage.getItem(LS_PROFILE); if (raw) return JSON.parse(raw); }
  catch (e) { /* ignore */ }
  return null;
}
function saveProfile(p) {
  try { localStorage.setItem(LS_PROFILE, JSON.stringify(p)); } catch (e) { /* ignore */ }
}
function loadAffinity() {
  try { const raw = localStorage.getItem(LS_AFFINITY); if (raw) return JSON.parse(raw); }
  catch (e) { /* ignore */ }
  return { sectors: {}, funders: {} };
}
function saveAffinity(a) {
  try { localStorage.setItem(LS_AFFINITY, JSON.stringify(a)); } catch (e) { /* ignore */ }
}

function recordAffinity(grant) {
  const a = state.affinity || { sectors: {}, funders: {} };
  a.sectors = a.sectors || {};
  a.funders = a.funders || {};
  (grant.thematic_sectors || []).slice(0, 4).forEach(s => {
    if (s) a.sectors[s] = (a.sectors[s] || 0) + 1;
  });
  if (grant.funder_name) a.funders[grant.funder_name] = (a.funders[grant.funder_name] || 0) + 1;
  state.affinity = a;
  saveAffinity(a);
}

// ── Profile helpers ─────────────────────────────────────────────────────────
function hasAnyProfile(p) {
  return !!(p && (p.stage || (p.fields && p.fields.length) ||
                  (p.region && p.region !== 'any')));
}
function hasAffinity(a) {
  return !!(a && a.sectors && Object.keys(a.sectors).length);
}

// ── Personalisation panel (chips built from the data) ───────────────────────
function buildPersonalizePanel(grants) {
  renderChips('pz-stage', STAGE_OPTIONS, 'single');

  // Fields — the most common thematic sectors in the dataset (top 14).
  const secCount = {};
  grants.forEach(g => (g.thematic_sectors || []).forEach(s => {
    if (s) secCount[s] = (secCount[s] || 0) + 1;
  }));
  const topSectors = Object.entries(secCount)
    .sort((a, b) => b[1] - a[1]).slice(0, 14)
    .map(([s]) => ({ value: s, label: s }));
  renderChips('pz-fields', topSectors, 'multi');

  // Region — distinct applicant/focus regions, with an "Anywhere" default.
  const regSet = new Set();
  grants.forEach(g => {
    (g.applicant_base_regions || []).forEach(r => r && regSet.add(r));
    (g.geographic_focus_regions || []).forEach(r => r && regSet.add(r));
  });
  const regions = [{ value: 'any', label: 'Anywhere' },
    ...[...regSet].sort().map(r => ({ value: r, label: r }))];
  renderChips('pz-region', regions, 'single');
}

function renderChips(containerId, options, mode) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = '';
  options.forEach(opt => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pz-chip';
    b.dataset.value = opt.value;
    b.textContent = opt.label;
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', () => {
      if (mode === 'single') {
        const wasSel = b.classList.contains('pz-chip--selected');
        el.querySelectorAll('.pz-chip').forEach(c => {
          c.classList.remove('pz-chip--selected');
          c.setAttribute('aria-pressed', 'false');
        });
        if (!wasSel) { b.classList.add('pz-chip--selected'); b.setAttribute('aria-pressed', 'true'); }
      } else {
        const sel = b.classList.toggle('pz-chip--selected');
        b.setAttribute('aria-pressed', String(sel));
      }
    });
    el.appendChild(b);
  });
}

function setChipSelection(containerId, values) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.querySelectorAll('.pz-chip').forEach(c => {
    const on = values.includes(c.dataset.value);
    c.classList.toggle('pz-chip--selected', on);
    c.setAttribute('aria-pressed', String(on));
  });
}
function selectedValues(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return [];
  return [...el.querySelectorAll('.pz-chip--selected')].map(c => c.dataset.value);
}

function syncPanelToProfile() {
  const p = state.profile;
  setChipSelection('pz-stage',  p && p.stage ? [p.stage] : []);
  setChipSelection('pz-fields', p && p.fields ? p.fields : []);
  setChipSelection('pz-region', p && p.region ? [p.region] : []);
}

function saveProfileFromPanel() {
  const profile = {
    stage:  selectedValues('pz-stage')[0] || '',
    fields: selectedValues('pz-fields'),
    region: selectedValues('pz-region')[0] || '',
  };
  state.profile = profile;
  saveProfile(profile);
  updatePersonalizeLabel();
}

function updatePersonalizeLabel() {
  const label = document.getElementById('personalize-label');
  const btn   = document.getElementById('personalize-toggle');
  const p = state.profile;
  if (hasAnyProfile(p)) {
    const bits = [];
    const stageLabel = (STAGE_OPTIONS.find(o => o.value === p.stage) || {}).label;
    if (stageLabel) bits.push(stageLabel);
    if (p.fields && p.fields.length) {
      bits.push(p.fields.slice(0, 2).join(', ') + (p.fields.length > 2 ? '…' : ''));
    }
    if (p.region && p.region !== 'any') bits.push(p.region);
    label.textContent = bits.length ? 'Personalised · ' + bits.join(' · ') : 'Personalise my feed';
    btn.classList.add('btn-personalize--active');
  } else {
    label.textContent = 'Personalise my feed';
    btn.classList.remove('btn-personalize--active');
  }
}

// ── Scoring ───────────────────────────────────────────────────────────────
function globalPrior(g) {
  return typeof g._rank_score === 'number' ? g._rank_score : 0.6;
}

function stageMatch(grant, stage) {
  const orgTypes = (grant.organisation_types || []).join(' ').toLowerCase();
  if (stage === 'nonprofit') {
    return /non.?profit|ngo|charit|civil society|foundation|community/.test(orgTypes) ? 1.0 : 0.45;
  }
  if (stage === 'industry') {
    const hay = orgTypes + ' ' + (grant.grant_types || []).join(' ').toLowerCase();
    return /sme|business|compan|startup|start-up|industr|for.?profit|enterprise|innovation|commerc/.test(hay) ? 1.0 : 0.40;
  }
  const hay = [
    ...(grant.grant_types || []),
    ...(grant.individual_eligibility || []),
    ...(grant.organisation_types || []),
    grant.grant_title || '',
  ].join(' ').toLowerCase();
  const kws = STAGE_KEYWORDS[stage] || [];
  const hits = kws.filter(k => hay.includes(k)).length;
  if (hits >= 2) return 1.0;
  if (hits === 1) return 0.75;
  return 0.45;
}

function affinityBoost(grant, affinity) {
  if (!hasAffinity(affinity)) return 0.4;
  const secW = affinity.sectors || {};
  const funW = affinity.funders || {};
  const sumSec = Object.values(secW).reduce((a, b) => a + b, 0) || 1;
  let s = 0;
  (grant.thematic_sectors || []).forEach(sec => { if (secW[sec]) s += secW[sec] / sumSec; });
  s = Math.min(1, s);
  const sumFun = Object.values(funW).reduce((a, b) => a + b, 0) || 1;
  const f = grant.funder_name && funW[grant.funder_name]
    ? Math.min(1, funW[grant.funder_name] / sumFun) : 0;
  return Math.max(0.3, 0.7 * s + 0.3 * f);
}

// Returns 0..1 personal match, or null when there's nothing to personalise on.
function personalMatch(grant, profile, affinity) {
  const profilePresent  = hasAnyProfile(profile);
  const affinityPresent = hasAffinity(affinity);
  if (!profilePresent && !affinityPresent) return null;

  let pm = null;
  if (profilePresent) {
    // Field overlap
    let fieldScore = 0.5;
    if (profile.fields && profile.fields.length) {
      const sectors = grant.thematic_sectors || [];
      const hit = sectors.filter(s => profile.fields.includes(s)).length;
      fieldScore = hit > 0 ? Math.min(1, 0.65 + 0.18 * hit) : 0.20;
    }
    // Region
    let regionScore = 0.5;
    if (profile.region && profile.region !== 'any') {
      const regions = [...(grant.applicant_base_regions || []),
                       ...(grant.geographic_focus_regions || [])];
      if (regions.includes(profile.region)) regionScore = 1.0;
      else if (!regions.length || regions.includes('Global')) regionScore = 0.6;
      else regionScore = 0.25;
    }
    // Career stage / eligibility
    const stageScore = profile.stage ? stageMatch(grant, profile.stage) : 0.5;
    pm = 0.42 * fieldScore + 0.30 * stageScore + 0.28 * regionScore;
  }

  const ab = affinityBoost(grant, affinity);
  if (profilePresent && affinityPresent) return 0.8 * pm + 0.2 * ab;
  if (profilePresent) return pm;
  return ab; // affinity only
}

// ── Ordering ────────────────────────────────────────────────────────────────
function deadlineKey(g) {
  if (!g.application_deadline) return Number.MAX_SAFE_INTEGER;
  const t = Date.parse(g.application_deadline + 'T00:00:00');
  return isNaN(t) ? Number.MAX_SAFE_INTEGER : t;
}
function fundingUsd(g) {
  const amt = g.funding_amount_max || g.funding_amount_min;
  if (!amt) return -1;
  return Number(amt) * (FX_USD[(g.currency || 'USD').toUpperCase()] || 1);
}
function idHash(g) {
  const s = String(g.id || '');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}
function clearForYou(arr) { arr.forEach(g => { g._forYou = false; }); }

function orderGrants(list) {
  const arr = list.slice();

  if (state.sortMode === 'deadline') {
    clearForYou(arr);
    return arr.sort((a, b) => deadlineKey(a) - deadlineKey(b));
  }
  if (state.sortMode === 'funding') {
    clearForYou(arr);
    return arr.sort((a, b) => fundingUsd(b) - fundingUsd(a));
  }
  if (state.sortMode === 'toprated') {
    clearForYou(arr);
    return arr.sort((a, b) => globalPrior(b) - globalPrior(a) || idHash(a) - idHash(b));
  }

  // 'recommended' — blend the global prior with the personal match.
  const personalised = hasAnyProfile(state.profile) || hasAffinity(state.affinity);
  arr.forEach(g => {
    const pm = personalMatch(g, state.profile, state.affinity);
    if (pm == null) {
      g._score  = globalPrior(g);
      g._forYou = false;
    } else {
      g._score  = 0.45 * globalPrior(g) + 0.55 * pm;
      g._forYou = personalised && pm >= 0.78;
    }
  });
  arr.sort((a, b) => b._score - a._score || idHash(a) - idHash(b));
  return arr;
}
