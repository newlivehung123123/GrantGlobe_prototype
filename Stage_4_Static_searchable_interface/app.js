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
});

// ── Module-level state ──────────────────────────────────────────────────────
const state = {
  allGrants: [],   // full dataset, set once in init()
  filtered:  [],   // current filtered + searched subset
};

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
  state.filtered  = grants;
  populateDynamicFilters(grants);
  renderCards(grants);
  updateResultCount(grants.length, grants.length);
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

  // Status — add "Not specified" if any record has no current_status
  const knownStatuses = new Set(['Open', 'Upcoming', 'Rolling', 'Closed']);
  const hasNoStatus = grants.some(g => !g.current_status || !knownStatuses.has(g.current_status));
  if (hasNoStatus) maybeAddUnspecified(document.getElementById('filter-status'), true);
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
    const cls         = (grant.current_status || 'unknown').toLowerCase();
    const statusLabel = grant.current_status || 'Unknown';

    // Deadline text
    let deadlineText;
    if (grant.application_deadline) {
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
    const tmp = document.createElement('div');
    tmp.innerHTML =
      `<div class="grant-card${closedClass}" tabindex="0" data-id="${esc(grant.id)}">` +
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
  const cls         = (grant.current_status || 'unknown').toLowerCase();
  const statusLabel = grant.current_status || 'Unknown';

  // ── Deadline ────────────────────────────────────────────────────────
  const deadlineText = grant.application_deadline
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
  const knownStatuses = new Set(['Open', 'Upcoming', 'Rolling', 'Closed']);
  const hardFiltered = state.allGrants.filter(g => {
    // Status
    if (status === '__unspecified__') {
      if (g.current_status && knownStatuses.has(g.current_status)) return false;
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
    state.filtered = fuse.search(query).map(r => r.item);
  } else {
    // No query — preserve the original sort order from grants.json
    state.filtered = hardFiltered;
  }

  // Step 4 — render
  renderCards(state.filtered);
  updateResultCount(state.filtered.length, state.allGrants.length);
}
